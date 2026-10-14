"""Authenticated, bounded AssemblyAI live relay with wall-time usage accounting."""
import asyncio
import hashlib
import json
import os
import time
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, Header, Request, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from .class_live_notes import authorize_capture
from .identity import current_principal, principal_context, Principal, assert_principal_active
from .material_routes import material_owner
from .usage.ledger import Ledger
from .usage.operations import configured_rate
from .usage.policy import Policy

MAX_SECONDS = 60
RESERVATION_SECONDS = 75


def configuration():
    secret = os.getenv('OPENLEARN_CLASS_STREAM_SECRET', '')
    model = os.getenv('OPENLEARN_CLASS_STREAMING_MODEL', 'universal-3-6-pro')
    policy = Policy.load()
    if (os.getenv('OPENLEARN_CLASS_STREAMING_ENABLED') != 'true' or not os.getenv('ASSEMBLYAI_API_KEY')
            or len(secret) < 32 or model not in {'universal-3-6-pro', 'universal-3-5-pro'}
            or policy.mode != 'enforce' or not policy.paid):
        raise HTTPException(503, {'code': 'class_stream_unavailable', 'message': 'Class live captions are not configured.'})
    return secret, model, policy, configured_rate('OPENLEARN_ASSEMBLYAI_STREAMING_USD_PER_MINUTE')


class StreamInput(BaseModel):
    anchorMs: int = Field(ge=0, le=24 * 60 * 60 * 1000)


def build_class_streaming_router(get_store, connect_provider=None):
    router = APIRouter(prefix='/v1/class-sessions', tags=['class-streaming'])

    @router.post('/{class_id}/transcription-sessions')
    def create(class_id: str, body: StreamInput, request: Request, owner=Depends(material_owner),
               capability: str = Header(alias='X-Capture-Capability', min_length=32, max_length=128),
               command: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
        secret, model, policy, rate = configuration()
        store = get_store()
        with store.engine.connect() as conn:
            item = authorize_capture(conn, owner, class_id, capability, active=True)
            if item.get('policy',{}).get('speechQuality')=='economical':
                raise HTTPException(409,{'code':'economical_captions_disabled','message':'Economical mode verifies saved audio without live streaming. Recording continues.'})
        model = item.get('speech', {}).get('streamingModel', model)
        principal = current_principal()
        ledger = Ledger(store, policy)
        reservation = ledger.reserve(owner, 'class-stream:' + class_id + ':' + command, 'stt', {'milliseconds': RESERVATION_SECONDS * 1000},
                                     liability=(rate * RESERVATION_SECONDS + 59) // 60, root=class_id, seconds=120, provider='assemblyai', model=model,
                                     provider_rates={'rateNanoUsd': rate, 'unit': 'usd_per_minute', 'billingBasis': 'session_wall_time', 'providerRateVersion': policy.provider_rate_version})
        if reservation['state'] != 'reserved':
            raise HTTPException(409, {'code': 'stream_already_used', 'message': 'This caption connection was already used.'})
        try:
            with ledger.transaction() as conn:
                ledger.lock(conn, 'usage_accounts', 'owner_id', owner)
                busy = conn.execute(text("SELECT 1 FROM usage_reservations WHERE owner_id=:owner AND id<>:id AND operation_key LIKE :prefix AND state IN ('reserved','dispatched') AND deadline>:now LIMIT 1"), {'owner': owner, 'id': reservation['id'], 'prefix': 'class-stream:' + class_id + ':%', 'now': ledger.now(conn)}).first()
                if busy:
                    raise HTTPException(409, {'code': 'class_stream_busy', 'message': 'This class already has a live caption connection.'})
        except Exception:
            ledger.settle(owner, reservation['id'], cost=0, release=True)
            raise
        now = time.time()
        ticket = jwt.encode({'sub': owner, 'rid': reservation['id'], 'class': class_id, 'epoch': item.get('captureEpoch', 1),
                             'cap': capability, 'anchor': body.anchorMs, 'model': model, 'region': item.get('speech', {}).get('region', 'us'), 'rate': rate, 'kind': principal.kind,
                             'device': principal.device_id, 'session_exp': principal.expires_at, 'aud': 'class-stream',
                             'iat': now, 'exp': min(now + 90, principal.expires_at or now + 90)}, secret, algorithm='HS256')
        url = str(request.url_for('class_audio_stream', class_id=class_id)).replace('https://', 'wss://').replace('http://', 'ws://')
        return {'ticket': ticket, 'url': url, 'maxSeconds': MAX_SECONDS, 'reservationId': reservation['id']}

    @router.post('/{class_id}/transcription-sessions/{reservation_id}/cancel')
    def cancel(class_id: str, reservation_id: str, owner=Depends(material_owner)):
        ledger = Ledger(get_store())
        with ledger.store.engine.connect() as conn:
            row = conn.execute(text('SELECT state,operation_key FROM usage_reservations WHERE id=:id AND owner_id=:owner'), {'id': reservation_id, 'owner': owner}).mappings().first()
        if row and row['state'] == 'reserved' and row['operation_key'].startswith('class-stream:' + class_id + ':'):
            ledger.settle(owner, reservation_id, cost=0, release=True)
        return {'status': 'cancelled'}

    @router.websocket('/{class_id}/audio-stream', name='class_audio_stream')
    async def stream(ws: WebSocket, class_id: str):
        await ws.accept()
        ledger = None
        owner = rid = token = None
        connected_at = None
        dispatched = False
        rate = 0
        try:
            secret, _model, policy, _rate = configuration()
            auth = await asyncio.wait_for(ws.receive_json(), 5)
            claims = jwt.decode(auth.get('ticket', ''), secret, algorithms=['HS256'], audience='class-stream')
            if claims['class'] != class_id:
                raise ValueError('Wrong class')
            owner, rid, rate = claims['sub'], claims['rid'], claims['rate']
            principal = Principal(owner, claims['kind'], claims.get('device'), expires_at=claims.get('session_exp'))
            store = get_store()
            token = principal_context.set(principal)
            with store.engine.connect() as conn:
                assert_principal_active(conn, principal)
                item = authorize_capture(conn, owner, class_id, claims['cap'], active=True)
                if item.get('captureEpoch', 1) != claims['epoch']:
                    raise ValueError('Stale capture')
            ledger = Ledger(store, policy)
            ledger.dispatch(owner, rid)  # Atomic single-use claim across processes.
            dispatched = True
            if connect_provider is None:
                from websockets.asyncio.client import connect
                connector = connect
            else:
                connector = connect_provider
            from .lecture_pipeline import _course_vocabulary
            terms = [part.strip()[:50] for part in _course_vocabulary(store, owner, item.get('courseId')).split(',') if part.strip()][:100]
            params = {'sample_rate': 16000, 'encoding': 'pcm_s16le', 'speech_model': claims['model'], 'mode': 'max_accuracy'}
            if terms:
                params['keyterms_prompt'] = json.dumps(terms)
            host = 'streaming.eu.assemblyai.com' if claims.get('region') == 'eu' else 'streaming.us.assemblyai.com'
            async with connector('wss://' + host + '/v3/ws?' + urlencode(params), additional_headers={'Authorization': os.environ['ASSEMBLYAI_API_KEY']}, open_timeout=10, close_timeout=3, max_size=1_000_000) as upstream:
                connected_at = time.monotonic()
                stream_id = hashlib.sha256((rid + class_id).encode()).hexdigest()
                sequence = 0
                turns = {}
                total_bytes = 0
                await ws.send_json({'type': 'ready', 'maxSeconds': MAX_SECONDS, 'streamId': stream_id})

                async def capture():
                    nonlocal total_bytes
                    last_check = 0
                    while True:
                        message = await asyncio.wait_for(ws.receive(), 10)
                        if message['type'] == 'websocket.disconnect':
                            return
                        frame = message.get('bytes')
                        if frame is None:
                            return
                        if len(frame) % 2 or not 1600 <= len(frame) <= 32000:
                            raise ValueError('Invalid audio frame')
                        total_bytes += len(frame)
                        elapsed = time.monotonic() - connected_at
                        if total_bytes > (MAX_SECONDS * 32000) or total_bytes > (elapsed + 2) * 32000:
                            raise ValueError('Audio buffer exceeded realtime bounds')
                        if elapsed - last_check > 1:
                            with store.engine.connect() as conn:
                                assert_principal_active(conn, principal)
                                latest = authorize_capture(conn, owner, class_id, claims['cap'], active=True)
                                if latest.get('captureEpoch', 1) != claims['epoch']:
                                    raise ValueError('Capture changed')
                            last_check = elapsed
                        await upstream.send(frame)

                async def receive():
                    nonlocal sequence
                    async for raw in upstream:
                        event = json.loads(raw)
                        if event.get('type') == 'Begin':
                            actual = event.get('configuration', {}).get('model')
                            if actual and actual != claims['model']:
                                raise ValueError('Provider model mismatch')
                        if event.get('type') != 'Turn':
                            continue
                        body = event.get('transcript', '')
                        if not isinstance(body, str) or len(body) > 6000:
                            raise ValueError('Invalid live transcript')
                        final = event.get('end_of_turn') is True
                        provider_item = stream_id + ':' + str(event.get('turn_order', sequence + 1))
                        if final and body.strip():
                            from .in_class_models import ClassLiveTranscriptSegmentCreate
                            from .in_class_service import InClassService
                            words = event.get('words') or []
                            first = min((w.get('start', 0) for w in words), default=0)
                            last = max((w.get('end', first + 1) for w in words), default=max(1, int(total_bytes / 32)))
                            previous = turns.get(provider_item)
                            if previous and previous['text'] == body:
                                continue
                            if previous is None:
                                sequence += 1
                            current_sequence = previous['sequence'] if previous else sequence
                            version = previous['version'] + 1 if previous else 1
                            command = ClassLiveTranscriptSegmentCreate(streamId=stream_id, streamSequence=current_sequence,
                                providerItemId=provider_item, transcript=body, transcriptionVersion=version,
                                startMs=claims['anchor'] + max(0, int(first)), endMs=claims['anchor'] + max(1, int(last), int(first) + 1))
                            await asyncio.to_thread(InClassService(store).append_live_transcript, owner, class_id, claims['cap'], command)
                            turns[provider_item] = {'text': body, 'sequence': current_sequence, 'version': version}
                        await ws.send_json({'type': 'caption', 'text': body, 'final': final, 'sequence': sequence, 'itemId': provider_item})

                capture_task = asyncio.create_task(capture())
                receive_task = asyncio.create_task(receive())
                try:
                    done, _pending = await asyncio.wait({capture_task, receive_task}, timeout=MAX_SECONDS, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    await upstream.send(json.dumps({'type': 'Terminate'}))
                    if not receive_task.done():
                        await asyncio.wait({receive_task}, timeout=2)
                finally:
                    for task in (capture_task, receive_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(capture_task, receive_task, return_exceptions=True)
                await ws.send_json({'type': 'rotate'})
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            try:
                await ws.send_json({'type': 'error', 'message': 'Live captions disconnected. Saved audio continues recording and can recover.'})
            except Exception:
                pass
        finally:
            try:
                if ledger is not None and dispatched:
                    if connected_at is None:
                        ledger.settle(owner, rid, cost=0, release=True)
                    else:
                        # Streaming is billed by socket lifetime, including silence.
                        seconds = min(RESERVATION_SECONDS, int(time.monotonic() - connected_at + 1))
                        ledger.settle(owner, rid, cost=(rate * seconds + 59) // 60, source='estimated')
            finally:
                if token is not None:
                    principal_context.reset(token)
                try:
                    await ws.close()
                except Exception:
                    pass
    return router
