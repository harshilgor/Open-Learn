"""Bounded transcription-only sessions; provider credentials never leave the server."""
import asyncio
import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING

import jwt
from fastapi import APIRouter, Depends, Header, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import text
from .identity import current_principal, assert_principal_active, Principal, fail
from .material_routes import material_owner
from .usage.ledger import Ledger
from .usage.policy import Policy
from .usage.operations import configured_rate

MAX_SECONDS = 90
MAX_BYTES = 9_000_000
MODEL = 'nova-3'


def configuration():
    secret = os.getenv('OPENLEARN_DICTATION_SECRET', '')
    if os.getenv('OPENLEARN_DICTATION_ENABLED') != 'true' or len(secret) < 32 or not os.getenv('DEEPGRAM_API_KEY'):
        fail('dictation_unavailable', 'Dictation is not configured yet. You can still type or talk to Buddy.', 503)
    policy = Policy.load()
    if policy.mode != 'enforce' or not policy.paid:
        fail('dictation_unavailable', 'Dictation requires enforced speech usage accounting.', 503)
    return secret, policy, configured_rate('OPENLEARN_DICTATION_USD_PER_MINUTE')


class SessionInput(BaseModel):
    sampleRate: int = Field(ge=8000, le=48000)


def build_dictation_router(get_store, connect_provider=None):
    router = APIRouter(prefix='/v1/dictation', tags=['dictation'])

    @router.get('/capability')
    def capability(owner=Depends(material_owner)):
        try:
            configuration()
            return {'available': True, 'maxSeconds': MAX_SECONDS}
        except Exception:
            return {'available': False, 'maxSeconds': MAX_SECONDS}

    @router.post('/sessions')
    def create(body: SessionInput, request: Request, owner=Depends(material_owner), idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
        secret, policy, rate = configuration()
        principal = current_principal()
        if principal.kind not in {'web', 'local', 'desktop'}:
            fail('device_scope_denied', 'Sign in to dictate a message.', 403)
        ledger = Ledger(get_store(), policy)
        reservation = ledger.reserve(owner, 'dictation:' + idempotency_key, 'stt', {'milliseconds': MAX_SECONDS * 1000},
            liability=(rate * MAX_SECONDS + 59) // 60, root='dictation:' + idempotency_key, seconds=150,
            provider='deepgram', model=MODEL, provider_rates={'providerRateVersion': policy.provider_rate_version, 'provider': 'deepgram', 'unit': 'usd_per_minute', 'rateNanoUsd': rate, 'quantityUnit': 'millisecond'})
        try:
            with ledger.transaction() as conn:
                ledger.lock(conn, 'usage_accounts', 'owner_id', owner)
                busy = conn.execute(text("SELECT 1 FROM usage_reservations WHERE owner_id=:owner AND id<>:id AND operation_key LIKE 'dictation:%' AND state IN ('reserved','dispatched') AND deadline>:now LIMIT 1"), {'owner': owner, 'id': reservation['id'], 'now': ledger.now(conn)}).first()
                if busy:
                    fail('dictation_busy', 'Finish the current dictation before starting another.', 409)
        except Exception:
            if reservation['state'] == 'reserved':
                ledger.settle(owner, reservation['id'], cost=0, release=True)
            raise
        if reservation['state'] != 'reserved':
            fail('dictation_already_used', 'This dictation attempt was already used. Start a new recording.', 409)
        now = time.time()
        ticket = jwt.encode({'sub': owner, 'rid': reservation['id'], 'rate': body.sampleRate,
            'kind': principal.kind, 'device': principal.device_id, 'session_exp': principal.expires_at,
            'iat': now, 'exp': min(now + 120, principal.expires_at or now + 120), 'aud': 'dictation'}, secret, algorithm='HS256')
        base = os.getenv('OPENLEARN_DICTATION_WS_URL') or str(request.base_url).rstrip('/') + '/v1/dictation/stream'
        base = base.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        return {'id': reservation['id'], 'ticket': ticket, 'url': base, 'maxSeconds': MAX_SECONDS}

    @router.post('/sessions/{rid}/cancel')
    def cancel(rid: str, owner=Depends(material_owner)):
        ledger = Ledger(get_store())
        with ledger.store.engine.connect() as conn:
            row = conn.execute(text('SELECT state FROM usage_reservations WHERE id=:id AND owner_id=:owner'), {'id': rid, 'owner': owner}).first()
        if row and row[0] == 'reserved':
            ledger.settle(owner, rid, cost=0, release=True)
        return {'status': 'cancelled'}

    @router.websocket('/stream')
    async def stream(ws: WebSocket):
        await ws.accept()
        ledger = None
        owner = rid = None
        dispatched = False
        liability = 0
        receipt = None
        rate = 0
        try:
            secret, policy, _ = configuration()
            auth = await asyncio.wait_for(ws.receive_json(), 5)
            claims = jwt.decode(auth.get('ticket', ''), secret, algorithms=['HS256'], audience='dictation')
            owner, rid = claims['sub'], claims['rid']
            principal = Principal(owner, claims['kind'], claims.get('device'), expires_at=claims.get('session_exp'))
            ledger = Ledger(get_store(), policy)
            with ledger.store.engine.connect() as conn:
                assert_principal_active(conn, principal)
                row = conn.execute(text('SELECT * FROM usage_reservations WHERE id=:id AND owner_id=:owner AND component=\'stt\' AND model=:model'), {'id': rid, 'owner': owner, 'model': MODEL}).mappings().one()
                liability = row['liability_nano']
                rate = json.loads(row['payload'])['providerRates']['rateNanoUsd']
            ledger.dispatch(owner, rid)  # Durable single-use claim across processes.
            dispatched = True
            if connect_provider is None:
                from websockets.asyncio.client import connect
                connector = connect
            else:
                connector = connect_provider
            url = f'wss://api.deepgram.com/v1/listen?model={MODEL}&encoding=linear16&sample_rate={claims["rate"]}&channels=1&interim_results=true&smart_format=true&language=en-US'
            async with connector(url, additional_headers={'Authorization': 'Token ' + os.environ['DEEPGRAM_API_KEY']}, open_timeout=8, close_timeout=2, max_size=1_000_000) as upstream:
                await ws.send_json({'type': 'ready', 'sessionId': rid})
                finishing = asyncio.Event()
                received = 0
                segments = set()

                async def capture():
                    nonlocal received
                    last_identity_check = 0
                    while True:
                        if time.monotonic() - last_identity_check >= 1:
                            with ledger.store.engine.connect() as conn:
                                assert_principal_active(conn, principal)
                            last_identity_check = time.monotonic()
                        message = await asyncio.wait_for(ws.receive(), 12)
                        if message['type'] == 'websocket.disconnect':
                            raise WebSocketDisconnect()
                        if message.get('bytes') is not None:
                            audio = message['bytes']
                            received += len(audio)
                            if len(audio) > 65536 or received > min(MAX_BYTES, claims['rate'] * 2 * MAX_SECONDS):
                                raise ValueError('Recording limit reached.')
                            await upstream.send(audio)
                        else:
                            command = json.loads(message.get('text') or '{}').get('type')
                            if command == 'cancel':
                                return
                            if command == 'finish':
                                finishing.set()
                                await upstream.send(json.dumps({'type': 'CloseStream'}))
                                await asyncio.sleep(5)
                                return
                            raise ValueError('Unsupported dictation command.')

                async def transcript():
                    nonlocal receipt
                    sequence = 0
                    async for raw in upstream:
                        data = json.loads(raw)
                        if data.get('type') == 'Error':
                            raise ValueError('Transcription is unavailable. Your draft is safe.')
                        if data.get('type') == 'Metadata':
                            duration = data.get('duration')
                            identifier = data.get('request_id')
                            try:
                                seconds = Decimal(str(duration))
                                if isinstance(duration, bool) or not seconds.is_finite() or not 0 <= seconds <= MAX_SECONDS or not isinstance(identifier, str) or not 1 <= len(identifier) <= 160:
                                    raise ValueError('Invalid provider receipt.')
                                milliseconds = int((seconds * 1000).to_integral_value(rounding=ROUND_CEILING))
                                receipt = {'milliseconds': milliseconds, 'id': identifier}
                            except (InvalidOperation, ValueError):
                                raise ValueError('Invalid provider receipt.') from None
                            continue
                        if data.get('type') != 'Results':
                            continue
                        value = data.get('channel', {}).get('alternatives', [{}])[0].get('transcript', '')
                        if not value:
                            continue
                        segment = f'{data.get("start", 0)}:{data.get("duration", 0)}'
                        final = data.get('is_final', False)
                        if final and segment in segments:
                            continue
                        if final:
                            segments.add(segment)
                        sequence += 1
                        await ws.send_json({'type': 'transcript.final' if final else 'transcript.interim', 'text': value, 'segmentId': segment, 'sequence': sequence, 'sessionId': rid})
                    if finishing.is_set():
                        await ws.send_json({'type': 'completed', 'sessionId': rid})

                tasks = [asyncio.create_task(capture()), asyncio.create_task(transcript())]
                try:
                    done, pending = await asyncio.wait(tasks, timeout=MAX_SECONDS + 5, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        raise TimeoutError('Recording limit reached.')
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except Exception:
            try:
                await ws.send_json({'type': 'error', 'message': 'Dictation could not finish. Your original draft and received text are preserved.'})
            except Exception:
                pass
        finally:
            if ledger and dispatched:
                # Conservatively charge the bounded reservation when provider usage is uncertain.
                try:
                    if receipt:
                        cost = (rate * receipt['milliseconds'] + 59_999) // 60_000
                        ledger.settle(owner, rid, quantities={'milliseconds': receipt['milliseconds']}, cost=cost,
                                      source='exact', provider='deepgram', model=MODEL, receipt_id=receipt['id'])
                    else:
                        ledger.settle(owner, rid, cost=liability, source='estimated')
                except Exception:
                    # The durable reservation remains for the existing reconciler.
                    import logging
                    logging.getLogger(__name__).error('Dictation usage settlement requires reconciliation.')
            try:
                await ws.close()
            except Exception:
                pass

    return router
