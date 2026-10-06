import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from . import media
from .contracts import SessionCreate, TurnCreate, Focus, Confirmation, Playback
from .store import VoiceStore, encode, fingerprint, identifier
from .coordinator import Coordinator
from .tools import Tools
from ..identity import fail, Principal, principal_context, assert_owner_active
from ..material_routes import material_owner
from ..material_service import MaterialService
from ..workflow_store import WorkflowStore
from ..execution import schedule_local
from .worker import run_voice_job
from ..usage.ledger import Ledger, UsageError
from ..usage.operations import configured_rate
from ..usage.policy import Policy

VOICE_SLICE_SECONDS = min(60, max(15, int(os.getenv('OPENLEARN_VOICE_SLICE_SECONDS', '15'))))
VOICE_SLICE_RENEWAL_LEAD_SECONDS = 30 if VOICE_SLICE_SECONDS == 60 else 5
VOICE_SLICE_MILLISECONDS = VOICE_SLICE_SECONDS * 1000


def _voice_acceptance_mode():
    try:
        seconds = int(os.getenv('OPENLEARN_VOICE_SESSION_SECONDS', '1800'))
    except ValueError:
        return False
    return (os.getenv('OPENLEARN_VOICE_ACCEPTANCE_MODE') == 'true' and
            bool(os.getenv('OPENLEARN_VOICE_TEST_EMAILS', '').strip()) and
            os.getenv('OPENLEARN_VOICE_MAX_CONCURRENT') == '1' and
            60 <= seconds <= 120)


def _voice_account_allowed():
    if not _voice_acceptance_mode():
        return os.getenv('OPENLEARN_VOICE_LIFECYCLE_VERIFIED') == 'true'
    principal = principal_context.get()
    allowed = {value.strip().lower() for value in os.getenv('OPENLEARN_VOICE_TEST_EMAILS', '').split(',') if value.strip()}
    return bool(principal and principal.kind == 'web' and principal.email in allowed)


def _voice_usage_ready():
    """Voice requires accounting plus an operator-verified bounded shutdown path."""
    if (os.getenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED') != 'true' or
            os.getenv('OPENLEARN_VOICE_ENABLED') != 'true' or
            (os.getenv('OPENLEARN_VOICE_LIFECYCLE_VERIFIED') != 'true' and not _voice_acceptance_mode())):
        return False
    try:
        if Policy.load().mode != 'enforce':
            return False
        for name in ('OPENLEARN_DEEPGRAM_USD_PER_MINUTE',
                     'OPENLEARN_ELEVENLABS_USD_PER_1000_CHARACTERS',
                     'OPENLEARN_LIVEKIT_AGENT_USD_PER_MINUTE'):
            configured_rate(name)
    except (RuntimeError, UsageError):
        return False
    return media.configured()


def _reservation(ledger, owner, key):
    with ledger.store.engine.connect() as conn:
        row = conn.execute(text('SELECT * FROM usage_reservations WHERE owner_id=:owner AND operation_key=:key'),
                           {'owner': owner, 'key': key}).mappings().first()
    return dict(row) if row else None


def _reserve_idempotently(ledger, owner, key, component, milliseconds, liability, root, provider_rates):
    row = ledger.reserve(owner, key, component, {'milliseconds': milliseconds}, liability=liability,
                         root=root, seconds=240, provider='livekit' if component == 'voice' else 'deepgram',
                         provider_rates=provider_rates)
    if row['state'] not in {'reserved', 'dispatched', 'settled'}:
        raise UsageError('usage_operation_conflict', 'This voice interval cannot be retried.', 409)
    return row


def _voice_slice_keys(sid, index):
    prefix = f'voice:{sid}:slice:{index}:'
    return prefix + 'runtime', prefix + 'speech'


def _settle_voice_slice(ledger, owner, sid, index):
    for key in _voice_slice_keys(sid, index):
        row = _reservation(ledger, owner, key)
        if row and row['state'] == 'dispatched':
            # Provider receipts are not available from these media adapters;
            # settle the full, conservatively reserved interval bound.
            ledger.settle(owner, row['id'], cost=row['liability_nano'], source='estimated')


def _current_voice_slice(store, owner, sid):
    prefix = f'voice:{sid}:slice:'
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT operation_key,created_at,state FROM usage_reservations WHERE owner_id=:owner AND root_id=:root AND operation_key LIKE :prefix AND component IN ('voice','stt')"),
                            {'owner': owner, 'root': sid, 'prefix': prefix + '%'}).mappings().all()
    groups = {}
    for row in rows:
        suffix = row['operation_key'][len(prefix):].split(':')
        if len(suffix) != 2 or not suffix[0].isdigit() or suffix[1] not in {'runtime', 'speech'}:
            continue
        index = int(suffix[0])
        groups.setdefault(index, {})[suffix[1]] = row
    if not groups:
        return None
    # Renewal reserves and dispatches two providers in separate transactions.
    # A poll may see only the first new hold, or two undispatched holds. Keep
    # enforcing the preceding fully admitted interval until the new pair is
    # dispatched; never let an incomplete future hold authorize provider work.
    admitted = [index for index, group in groups.items()
                if set(group) == {'runtime', 'speech'} and
                all(row['state'] in {'dispatched', 'settled'} for row in group.values())]
    if not admitted:
        return None
    index = max(admitted)
    group = groups[index]
    if not group:
        return None
    started = max(row['created_at'] for row in group.values())
    states = tuple(group.get(name, {}).get('state', 'missing') for name in ('runtime', 'speech'))
    return {'index': index, 'startedAt': started, 'nextAt': started + VOICE_SLICE_SECONDS,
            'states': states, 'incomplete': set(group) != {'runtime', 'speech'}}


def _settle_voice_session(ledger, owner, sid):
    with ledger.store.engine.connect() as conn:
        rows = conn.execute(text("SELECT id,operation_key FROM usage_reservations WHERE owner_id=:owner AND root_id=:root AND state='dispatched' AND operation_key LIKE :prefix"),
                            {'owner': owner, 'root': sid, 'prefix': f'voice:{sid}:%'}).mappings().all()
    for row in rows:
        current = _reservation(ledger, owner, row['operation_key'])
        if current and current['state'] == 'dispatched':
            ledger.settle(owner, current['id'], cost=current['liability_nano'], source='estimated')


def _admit_voice_slice(store, owner, sid, index, *, active=True):
    if not _voice_usage_ready():
        raise UsageError('voice_unavailable', 'Voice usage accounting is not ready. You can continue typing.', 503)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 120:
        raise UsageError('voice_slice_invalid', 'This voice interval is unavailable.', 422)
    records = VoiceStore(store)
    session = records.session(owner, sid, active=active)
    now = time.time()
    renewal_seconds = VOICE_SLICE_SECONDS - VOICE_SLICE_RENEWAL_LEAD_SECONDS
    max_slices = max(1, min(120, int((session['expires_at'] - session['created_at'] + renewal_seconds - 1) // renewal_seconds)))
    if index >= max_slices:
        raise UsageError('voice_slice_limit', 'This voice session has reached its time limit.', 429)

    ledger = Ledger(store, Policy.load())
    runtime_key, speech_key = _voice_slice_keys(sid, index)
    existing_runtime = _reservation(ledger, owner, runtime_key)
    existing_speech = _reservation(ledger, owner, speech_key)
    if existing_runtime or existing_speech:
        if not existing_runtime or not existing_speech:
            raise UsageError('usage_operation_conflict', 'This voice interval is being reconciled.', 409)
        # A replay returns the exact original authorization without admitting
        # another charge or refreshing its original deadline.
        if existing_runtime['state'] != 'dispatched' or existing_speech['state'] != 'dispatched':
            raise UsageError('usage_operation_conflict', 'This voice interval cannot be retried.', 409)
        started = max(existing_runtime['created_at'], existing_speech['created_at'])
        if now >= started + VOICE_SLICE_SECONDS:
            _settle_voice_slice(ledger, owner, sid, index)
            raise UsageError('voice_slice_expired', 'This voice interval has ended.', 409)
        return {'sliceIndex': index, 'startedAt': started, 'nextAt': started + VOICE_SLICE_SECONDS, 'renewalLeadSeconds': VOICE_SLICE_RENEWAL_LEAD_SECONDS,
                'remainingSeconds': max(0, int(session['expires_at'] - now)), 'replayed': True}

    if index > 0:
        previous = index - 1
        previous_keys = _voice_slice_keys(sid, previous)
        previous_rows = [_reservation(ledger, owner, key) for key in previous_keys]
        if any(row is None or row['state'] not in {'dispatched', 'settled'} for row in previous_rows):
            raise UsageError('voice_slice_order', 'Voice intervals must be admitted in order.', 409)
        prior_started = max(row['created_at'] for row in previous_rows)
        ready_at = prior_started + VOICE_SLICE_SECONDS
        # Renew before the current deadline so a hosted database round trip
        # cannot strand healthy media. Each overlapping interval is fully
        # reserved and charged; this never grants unmetered provider time.
        if now < ready_at - VOICE_SLICE_RENEWAL_LEAD_SECONDS:
            raise UsageError('voice_slice_early', 'The next voice interval is not ready yet.', 409, reset=ready_at)
        _settle_voice_slice(ledger, owner, sid, previous)

    quantities = VOICE_SLICE_MILLISECONDS
    runtime_rate = configured_rate('OPENLEARN_LIVEKIT_AGENT_USD_PER_MINUTE')
    speech_rate = configured_rate('OPENLEARN_DEEPGRAM_USD_PER_MINUTE')
    runtime_liability = max(1, (runtime_rate * quantities + 59_999) // 60_000)
    speech_liability = max(1, (speech_rate * quantities + 59_999) // 60_000)
    provider_rate_version = Policy.load().provider_rate_version
    reserved = []
    try:
        # Create both holds before dispatching either. If the second provider's
        # liability does not fit, no interval is authorized to start.
        for key, component, liability, provider, rate in ((runtime_key, 'voice', runtime_liability, 'livekit', runtime_rate),
                                                          (speech_key, 'stt', speech_liability, 'deepgram', speech_rate)):
            reserved.append(_reserve_idempotently(ledger, owner, key, component, quantities, liability, sid,
                                                   {'providerRateVersion': provider_rate_version,
                                                    'provider': provider,
                                                    'unit': 'usd_per_minute',
                                                    'rateNanoUsd': rate,
                                                    'quantityUnit': 'millisecond'}))
    except Exception:
        for row in reserved:
            current = _reservation(ledger, owner, row['operation_key'])
            if current and current['state'] == 'reserved':
                try:
                    ledger.settle(owner, current['id'], release=True, source='estimated')
                except Exception:
                    pass
        raise

    # Dispatch each operation only after all component reservations exist.
    # A retry can observe an already dispatched row and safely reuse it.
    for row in reserved:
        current = _reservation(ledger, owner, row['operation_key'])
        if current and current['state'] == 'reserved':
            try:
                ledger.dispatch(owner, current['id'])
            except UsageError:
                # Concurrent retries may both observe reserved. Accept only
                # the winner's durable dispatch; never run without a hold.
                current = _reservation(ledger, owner, row['operation_key'])
                if not current or current['state'] not in {'dispatched', 'settled'}:
                    raise
    rows = [_reservation(ledger, owner, key) for key in (runtime_key, speech_key)]
    if any(row is None or row['state'] not in {'dispatched', 'settled'} for row in rows):
        raise UsageError('usage_operation_conflict', 'Voice interval could not be authorized.', 503)
    started = max(row['created_at'] for row in rows)
    return {'sliceIndex': index, 'startedAt': started, 'nextAt': started + VOICE_SLICE_SECONDS, 'renewalLeadSeconds': VOICE_SLICE_RENEWAL_LEAD_SECONDS,
            'remainingSeconds': max(0, int(session['expires_at'] - now)), 'replayed': False}


def _speech_tts_key(sid, segment_id):
    return f'voice:{sid}:tts:{segment_id}'


def _prepare_speech_tts(store, owner, sid, segment_id, attempt_id, supplied_characters):
    if not _voice_usage_ready():
        raise UsageError('voice_unavailable', 'Voice usage accounting is not ready. You can continue typing.', 503)
    if not segment_id or len(segment_id) > 160 or not isinstance(attempt_id, str) or len(attempt_id) != 32 or any(c not in '0123456789abcdef' for c in attempt_id):
        raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 422)
    session = VoiceStore(store).session(owner, sid, active=True)
    with store.engine.connect() as conn:
        segment = conn.execute(text('SELECT id,status,payload FROM voice_speech_segments WHERE id=:id AND session_id=:sid AND owner_id=:owner'),
                               {'id': segment_id, 'sid': sid, 'owner': owner}).mappings().first()
    if not segment:
        raise UsageError('not_found', 'This spoken response is unavailable.', 404)
    try:
        payload = json.loads(segment['payload'])
        spoken_text = payload.get('text', '')
        characters = len(spoken_text)
    except Exception:
        raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 409) from None
    if not isinstance(spoken_text, str) or not characters or supplied_characters != characters:
        raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 409)
    key = _speech_tts_key(sid, segment_id)
    ledger = Ledger(store, Policy.load())
    existing = _reservation(ledger, owner, key)
    current_attempt = payload.get('ttsAttemptId')
    if segment['status'] == 'speaking':
        if current_attempt != attempt_id or not existing or existing['state'] not in {'dispatched', 'settled'}:
            raise UsageError('voice_tts_in_progress', 'This spoken response is already being delivered.', 409)
        return {'reservationId': existing['id'], 'characters': characters}
    if segment['status'] != 'released':
        raise UsageError('voice_tts_consumed', 'This spoken response has already been delivered.', 409)

    unit_rate = configured_rate('OPENLEARN_ELEVENLABS_USD_PER_1000_CHARACTERS')
    liability = max(1, (unit_rate * characters + 999) // 1000)
    reservation = ledger.reserve(owner, key, 'tts', {'characters': characters}, liability=liability,
                                 root=sid, seconds=240, provider='elevenlabs',
                                 provider_rates={'providerRateVersion': Policy.load().provider_rate_version,
                                                 'provider': 'elevenlabs',
                                                 'unit': 'usd_per_1000_characters',
                                                 'rateNanoUsd': unit_rate,
                                                 'quantityUnit': 'character'})
    if reservation['state'] != 'reserved':
        raise UsageError('voice_tts_consumed', 'This spoken response has already been delivered.', 409)
    payload = {**payload, 'ttsAttemptId': attempt_id}
    with store.transaction() as conn:
        changed = conn.execute(text("UPDATE voice_speech_segments SET status='speaking',payload=:payload WHERE id=:id AND session_id=:sid AND owner_id=:owner AND status='released'"),
                               {'payload': encode(payload), 'id': segment_id, 'sid': sid, 'owner': owner}).rowcount
    if not changed:
        with store.engine.connect() as conn:
            latest = conn.execute(text('SELECT status,payload FROM voice_speech_segments WHERE id=:id AND session_id=:sid AND owner_id=:owner'),
                                  {'id': segment_id, 'sid': sid, 'owner': owner}).mappings().first()
        latest_payload = json.loads(latest['payload']) if latest else {}
        if not latest or latest['status'] != 'speaking' or latest_payload.get('ttsAttemptId') != attempt_id:
            # This request didn't claim the utterance, so a still-unstarted
            # reservation is safe to release. Never release a dispatched call.
            current = _reservation(ledger, owner, key)
            if current and current['state'] == 'reserved':
                ledger.settle(owner, current['id'], release=True, source='estimated')
            raise UsageError('voice_tts_in_progress', 'This spoken response is already being delivered.', 409)
    current = _reservation(ledger, owner, key)
    if current and current['state'] == 'reserved':
        try:
            ledger.dispatch(owner, current['id'])
        except UsageError:
            current = _reservation(ledger, owner, key)
            if not current or current['state'] not in {'dispatched', 'settled'}:
                with store.transaction() as conn:
                    conn.execute(text("UPDATE voice_speech_segments SET status='released',payload=:payload WHERE id=:id AND session_id=:sid AND owner_id=:owner AND status='speaking'"),
                                 {'payload': encode({k: v for k, v in payload.items() if k != 'ttsAttemptId'}), 'id': segment_id, 'sid': sid, 'owner': owner})
                raise
    current = _reservation(ledger, owner, key)
    if not current or current['state'] not in {'dispatched', 'settled'}:
        raise UsageError('voice_tts_unavailable', 'Speech usage could not be authorized.', 503)
    return {'reservationId': current['id'], 'characters': characters}


def build_voice_router(get_store, provider_getter):
    router = APIRouter(tags=['voice'])
    records = VoiceStore(get_store())

    @router.get('/v1/voice/capabilities')
    def capabilities(owner=Depends(material_owner)):
        ready = _voice_usage_ready() and _voice_account_allowed()
        return {'enabled': ready, 'configured': ready, 'languages': ['en'],
                'message': 'Talk to Buddy is ready.' if ready else 'Voice is not enabled on this server yet. You can continue typing.'}

    @router.post('/v1/voice/sessions', status_code=201)
    async def create(body: SessionCreate, key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160), owner=Depends(material_owner)):
        # The control flow contains synchronous SQL and a request-local async
        # media client. Keep both on a worker's isolated loop so pool waits
        # cannot block health checks, event streams, or other voice requests.
        return await asyncio.to_thread(lambda: asyncio.run(create_session(body, key, owner)))

    async def create_session(body, key, owner):
        if not _voice_usage_ready() or not _voice_account_allowed():
            fail('voice_unavailable', 'Voice providers are not configured. You can continue typing.', 503)
        if not body.consent:
            fail('voice_consent_required', 'Accept microphone processing before starting.', 422)
        chat = MaterialService(get_store()).session(owner, body.chat_id)
        Tools(get_store(), provider_getter()).validate_focus(owner, body.focus.model_dump())
        now = time.time()
        with get_store().engine.connect() as conn:
            expired = conn.execute(text("SELECT id FROM voice_sessions WHERE owner_id=:owner AND status IN ('active','connecting') AND expires_at<=:now"), {'owner': owner, 'now': now}).scalars().all()
        for expired_id in expired:
            _settle_voice_session(Ledger(get_store(), Policy.load()), owner, expired_id)
            records.end(owner, expired_id, 'expired')
            try:
                await media.close(expired_id)
            except Exception:
                pass
        capability = secrets.token_urlsafe(48)
        sid = identifier('voice')
        seconds = min(1800, max(60, int(os.getenv('OPENLEARN_VOICE_SESSION_SECONDS', '1800'))))
        with get_store().transaction() as conn:
            assert_owner_active(conn, owner)
            if conn.dialect.name == 'postgresql':
                conn.execute(text('SELECT pg_advisory_xact_lock(782199441)'))
            previous = conn.execute(text('SELECT id,request_hash FROM voice_sessions WHERE owner_id=:owner AND command_key=:key'), {'owner': owner, 'key': key}).mappings().first()
            if previous:
                if previous['request_hash'] != fingerprint(body.model_dump()):
                    fail('idempotency_conflict', 'This request key has different content.', 409)
                session = records.session(owner, previous['id'], conn, active=True)
                return public(session, token=True)
            active = conn.execute(text("SELECT count(*) FROM voice_sessions WHERE status IN ('active','connecting') AND expires_at>:now"), {'now': now}).scalar_one()
            if active >= int(os.getenv('OPENLEARN_VOICE_MAX_CONCURRENT', '20')):
                fail('voice_capacity', 'Voice is busy. Please try shortly or continue typing.', 429)
            if conn.execute(text("SELECT 1 FROM voice_sessions WHERE owner_id=:owner AND status IN ('active','connecting')"), {'owner': owner}).first():
                fail('voice_already_active', 'End your other voice conversation first.', 409)
            conn.execute(text("INSERT INTO voice_sessions(id,owner_id,chat_id,command_key,request_hash,status,created_at,expires_at,last_seen,capability_hash,payload) VALUES(:id,:owner,:chat,:key,:hash,'connecting',:now,:expires,:now,:cap,:payload)"),
                         {'id': sid, 'owner': owner, 'chat': body.chat_id, 'key': key, 'hash': fingerprint(body.model_dump()), 'now': now, 'expires': now+seconds, 'cap': hashlib.sha256(capability.encode()).hexdigest(), 'payload': encode({**body.model_dump(), 'course_id': chat.course_id, 'buddy_id': chat.buddy_id, 'goal': chat.goal})})
            conn.execute(text('INSERT INTO voice_usage(id,owner_id,session_id,created_at,reserved_seconds) VALUES(:id,:owner,:sid,:now,:seconds)'), {'id': identifier('usage'), 'owner': owner, 'sid': sid, 'now': now, 'seconds': seconds})
        try:
            # Admission precedes room creation, so neither the media worker nor
            # Deepgram can start before the first shared-allowance slice is held.
            _admit_voice_slice(get_store(), owner, sid, 0, active=False)
        except Exception:
            records.end(owner, sid, 'usage_unavailable')
            raise
        try:
            await media.dispatch(sid, capability, now + seconds)
        except Exception:
            _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
            records.end(owner, sid, 'connection_failed')
            try:
                await media.close(sid)
            except Exception:
                pass
            raise
        with get_store().transaction() as conn:
            conn.execute(text("UPDATE voice_sessions SET status='active' WHERE id=:sid AND status='connecting'"), {'sid': sid})
            records.emit(conn, owner, sid, 'session.started', {})
        return public(records.session(owner, sid), token=True)

    def public(session, token=False):
        result = {'id': session['id'], 'chatId': session['chat_id'], 'status': session['status'], 'sequence': session['sequence'], 'epoch': session['epoch'], 'expiresAt': session['expires_at'], 'context': session['context']}
        if token:
            result.update(url=os.environ['LIVEKIT_URL'], token=media.token(session['id'], 'learner_'+session['id']))
        return result

    @router.get('/v1/voice/sessions/{sid}')
    def snapshot(sid: str, owner=Depends(material_owner)):
        Coordinator(get_store(), provider_getter()).reconcile(owner, sid)
        return {**public(records.session(owner, sid)), 'actions': records.records(owner, sid, 'actions'), 'turns': records.records(owner, sid, 'turns'), 'speech': records.records(owner, sid, 'speech_segments')}

    @router.post('/v1/voice/sessions/{sid}/token')
    def refresh_token(sid: str, owner=Depends(material_owner)):
        if not _voice_usage_ready():
            fail('voice_unavailable', 'Voice usage accounting is not ready. You can continue typing.', 503)
        records.session(owner, sid, active=True)
        return {'url': os.environ['LIVEKIT_URL'], 'token': media.token(sid, 'learner_'+sid)}

    @router.get('/v1/voice/sessions')
    def history(chat_id: str, owner=Depends(material_owner)):
        MaterialService(get_store()).session(owner, chat_id)
        with get_store().engine.connect() as conn:
            rows = conn.execute(text('SELECT id FROM voice_sessions WHERE owner_id=:owner AND chat_id=:chat ORDER BY created_at DESC LIMIT 20'), {'owner': owner, 'chat': chat_id}).scalars().all()
        return {'sessions': [public(records.session(owner, sid)) for sid in rows]}

    @router.post('/v1/voice/actions/{aid}/cancel')
    def cancel_action(aid: str, owner=Depends(material_owner)):
        with get_store().engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM voice_actions WHERE id=:id AND owner_id=:owner'), {'id': aid, 'owner': owner}).mappings().first()
        if not row:
            fail('not_found', 'Action unavailable.', 404)
        payload = json.loads(row['payload'])
        result = payload.get('result', {})
        if result.get('jobId'):
            WorkflowStore(get_store()).cancel(owner, result['jobId'])
            Coordinator(get_store(), provider_getter()).reconcile(owner, row['session_id'])
            return {'status': 'checked'}
        if row['status'] == 'awaiting_confirmation':
            with get_store().transaction() as conn:
                conn.execute(text("UPDATE voice_actions SET status='cancelled' WHERE id=:id AND owner_id=:owner AND status='awaiting_confirmation'"), {'id': aid, 'owner': owner})
                records.emit(conn, owner, row['session_id'], 'action.updated', {'callId': aid, 'status': 'cancelled', 'userMessage': 'Cancelled the pending action.'})
            return {'status': 'cancelled'}
        fail('voice_action_committed', 'This action is already saved or managed in its study task. Open it to make changes.', 409)

    @router.patch('/v1/voice/sessions/{sid}/context')
    def focus(sid: str, body: Focus, owner=Depends(material_owner)):
        Tools(get_store(), provider_getter()).validate_focus(owner, body.model_dump())
        with get_store().transaction() as conn:
            session = records.session(owner, sid, conn, active=True)
            if body.revision <= session['context']['focus']['revision']:
                fail('revision_conflict', 'Voice focus changed.', 409)
            context = {**session['context'], 'focus': body.model_dump()}
            changed = conn.execute(text('UPDATE voice_sessions SET payload=:payload WHERE id=:id AND owner_id=:owner AND payload=:previous'), {'id': sid, 'owner': owner, 'previous': session['payload'], 'payload': encode(context)}).rowcount
            if changed != 1:
                fail('revision_conflict', 'Voice focus changed. Please select the current item again.', 409)
        if body.quiz_id and body.presentation_id:
            from ..quiz_service import QuizService
            quiz = QuizService(get_store(), provider_getter()).public(owner, body.quiz_id)
            question = quiz.get('current')
            if question and question['id'] == body.presentation_id and not question.get('attemptId'):
                spoken = question['stem'] + ' ' + ' '.join(f"{chr(65+i)}. {option['label']}" for i, option in enumerate(question.get('options', [])))
                Coordinator(get_store(), provider_getter()).speech(owner, sid, 'question:'+question['id'], spoken)
        return {'revision': body.revision}

    @router.get('/v1/voice/sessions/{sid}/events')
    async def events(sid: str, after: int = 0, owner=Depends(material_owner)):
        await asyncio.to_thread(records.session, owner, sid)
        async def stream():
            cursor = max(0, after)
            while True:
                values = await asyncio.to_thread(records.events, owner, sid, cursor)
                for event in values:
                    cursor = event['sequence']
                    yield f'id: {cursor}\ndata: {encode(event)}\n\n'
                session = await asyncio.to_thread(records.session, owner, sid)
                if session['status'] == 'ended':
                    return
                yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})

    def submit(owner, sid, body, tasks):
        with get_store().transaction() as conn:
            session = records.session(owner, sid, conn, active=True)
            count = conn.execute(text('SELECT count(*) FROM voice_turns WHERE session_id=:sid'), {'sid': sid}).scalar_one()
            replay = conn.execute(text('SELECT 1 FROM voice_turns WHERE session_id=:sid AND command_key=:key'), {'sid': sid, 'key': body.utterance_id}).first()
            if count >= 120 and not replay:
                fail('voice_turn_limit', 'This conversation has reached its turn limit. End it and start a new session.', 429)
            turn, fresh = records.record(conn, 'turns', owner, sid, body.utterance_id, {'text': body.text})
            if fresh:
                records.update(conn, 'turns', owner, turn['id'], 'queued', {**turn['data'], 'focus': session['context']['focus'], 'epoch': session['epoch']})
            job = WorkflowStore(get_store()).enqueue(owner, sid, 'voice_turn', {'turn_id': turn['id']}, turn['id'], connection=conn, max_attempts=1)
            if fresh:
                records.emit(conn, owner, sid, 'turn.started', {'turnId': turn['id'], 'text': body.text})
        schedule_local(tasks, run_voice_job, get_store(), provider_getter(), job['id'])
        return {'turnId': turn['id'], 'jobId': job['id']}

    @router.post('/v1/voice/sessions/{sid}/turns', status_code=202)
    def turn(sid: str, body: TurnCreate, tasks: BackgroundTasks, owner=Depends(material_owner)):
        return submit(owner, sid, body, tasks)

    @router.post('/v1/voice/actions/{aid}/confirm')
    def confirm(aid: str, body: Confirmation, tasks: BackgroundTasks, owner=Depends(material_owner)):
        with get_store().transaction() as conn:
            row = conn.execute(text('SELECT * FROM voice_actions WHERE id=:id AND owner_id=:owner'), {'id': aid, 'owner': owner}).mappings().first()
            if not row:
                fail('not_found', 'Action unavailable.', 404)
            data = json.loads(row['payload'])
            session = records.session(owner, row['session_id'], conn, active=True)
            if row['status'] != 'awaiting_confirmation' or data['expiresAt'] < time.time() or not hmac.compare_digest(body.arguments_hash, fingerprint(data['arguments'])):
                fail('confirmation_expired', 'Review this action again.', 409)
            records.update(conn, 'actions', owner, aid, 'queued' if body.approve else 'cancelled', data)
            job = WorkflowStore(get_store()).enqueue(owner, row['session_id'], 'voice_action', {'action_id': aid}, aid+':confirm', connection=conn, max_attempts=1) if body.approve else None
            records.emit(conn, owner, row['session_id'], 'action.updated', {
                'callId': aid, 'tool': data.get('tool'), 'status': 'queued' if body.approve else 'cancelled',
                'confirmationMessage': data.get('confirmationMessage'),
                'userMessage': 'Action approved. Processing.' if body.approve else 'Action cancelled.',
            })
        if body.approve:
            schedule_local(tasks, run_voice_job, get_store(), provider_getter(), job['id'])
        return {'status': 'queued' if body.approve else 'cancelled'}

    def interrupt_session(owner, sid):
        with get_store().transaction() as conn:
            records.session(owner, sid, conn, active=True)
            epoch = conn.execute(text('UPDATE voice_sessions SET epoch=epoch+1 WHERE id=:id RETURNING epoch'), {'id': sid}).scalar_one()
            records.emit(conn, owner, sid, 'speech.interrupted', {'epoch': epoch})
        return {'epoch': epoch}

    @router.post('/v1/voice/sessions/{sid}/interrupt')
    def interrupt(sid: str, owner=Depends(material_owner)):
        return interrupt_session(owner, sid)

    @router.post('/v1/voice/sessions/{sid}/end')
    async def end(sid: str, owner=Depends(material_owner)):
        return await asyncio.to_thread(lambda: asyncio.run(end_session(sid, owner)))

    async def end_session(sid, owner):
        _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
        result = records.end(owner, sid)
        if media.configured():
            await media.close(sid)
        return public(result)

    def validate_agent(sid, supplied):
        with get_store().engine.connect() as conn:
            row = conn.execute(text('SELECT owner_id,capability_hash,status,expires_at FROM voice_sessions WHERE id=:id'), {'id': sid}).mappings().first()
            if not row or not hmac.compare_digest(row['capability_hash'], hashlib.sha256(supplied.encode()).hexdigest()):
                fail('authentication_required', 'Invalid voice capability.', 401)
            assert_owner_active(conn, row['owner_id'])
            if row['status'] not in {'active', 'connecting'} or row['expires_at'] <= time.time():
                fail('voice_ended', 'Voice session ended.', 403)
            return dict(row)

    async def agent_identity(sid: str, request: Request):
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        row = await asyncio.to_thread(validate_agent, sid, supplied)
        token = principal_context.set(Principal(row['owner_id'], 'voice_agent', expires_at=row['expires_at']))
        try:
            yield row['owner_id']
        finally:
            principal_context.reset(token)

    @router.post('/internal/voice/{sid}/turns', status_code=202)
    def agent_turn(sid: str, body: TurnCreate, tasks: BackgroundTasks, owner=Depends(agent_identity)):
        return submit(owner, sid, body, tasks)

    @router.get('/internal/voice/{sid}/poll')
    def agent_poll(sid: str, after: int = 0, owner=Depends(agent_identity)):
        if not _voice_usage_ready():
            _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
            records.end(owner, sid, 'voice_disabled')
            fail('voice_ended', 'Voice is disabled on this server.', 409)
        slice_state = _current_voice_slice(get_store(), owner, sid)
        now = time.time()
        slice_expired = (not slice_state or
                         (slice_state['incomplete'] and now > slice_state['startedAt'] + 2) or
                         (not slice_state['incomplete'] and any(state not in {'dispatched', 'settled'} for state in slice_state['states'])) or
                         (not slice_state['incomplete'] and now > slice_state['nextAt'] + 2))
        if slice_expired:
            _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
            records.end(owner, sid, 'usage_interval_expired')
            fail('voice_ended', 'The reserved voice interval ended. You can continue typing.', 409)
        Coordinator(get_store(), provider_getter()).reconcile(owner, sid)
        with get_store().transaction() as conn:
            # agent_identity has already fenced this capability to the
            # connecting/active window; LiveKit can start polling before the
            # room-creation RPC flips connecting to active.
            session = records.session(owner, sid, conn, active=False)
            if not session['context'].get('agent_ready'):
                conn.execute(text('UPDATE voice_sessions SET payload=:payload WHERE id=:sid'), {'sid': sid, 'payload': encode({**session['context'], 'agent_ready': True})})
                records.emit(conn, owner, sid, 'session.ready', {})
            conn.execute(text('UPDATE voice_sessions SET last_seen=:now WHERE id=:sid'), {'now': time.time(), 'sid': sid})
        return {**public(records.session(owner, sid)), 'events': records.events(owner, sid, max(0, after))}

    @router.post('/internal/voice/{sid}/slice')
    def agent_slice(sid: str, body: dict, owner=Depends(agent_identity)):
        index = body.get('slice_index') if isinstance(body, dict) else None
        try:
            # The media provider can start the agent before CreateRoom returns
            # and flips connecting to active; the capability dependency still
            # limits this to a live connecting/active session.
            return _admit_voice_slice(get_store(), owner, sid, index, active=False)
        except UsageError as exc:
            code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
            if exc.status_code in {429, 503} or code == 'voice_slice_expired':
                try:
                    _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
                except Exception:
                    pass
                records.end(owner, sid, 'usage_unavailable')
            raise

    @router.post('/internal/voice/{sid}/speech/{segment_id}/tts-preflight')
    def agent_tts_preflight(sid: str, segment_id: str, body: dict, owner=Depends(agent_identity)):
        if not isinstance(body, dict):
            raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 422)
        attempt_id = body.get('attempt_id')
        characters = body.get('characters')
        if isinstance(characters, bool) or not isinstance(characters, int) or not 1 <= characters <= 2400:
            raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 422)
        return _prepare_speech_tts(get_store(), owner, sid, segment_id, attempt_id, characters)

    @router.post('/internal/voice/{sid}/speech/{segment_id}/tts-complete')
    def agent_tts_complete(sid: str, segment_id: str, body: dict, owner=Depends(agent_identity)):
        if not isinstance(body, dict) or not isinstance(body.get('reservation_id'), str):
            raise UsageError('voice_tts_invalid', 'This spoken response is unavailable.', 422)
        records.session(owner, sid, active=True)
        ledger = Ledger(get_store(), Policy.load())
        expected_key = _speech_tts_key(sid, segment_id)
        reservation = _reservation(ledger, owner, expected_key)
        if (not reservation or reservation['id'] != body['reservation_id'] or reservation['component'] != 'tts'
                or reservation['root_id'] != sid):
            raise UsageError('usage_operation_conflict', 'This speech reservation is unavailable.', 409)
        if reservation['state'] == 'dispatched':
            ledger.settle(owner, reservation['id'], cost=reservation['liability_nano'], source='estimated')
        elif reservation['state'] != 'settled':
            raise UsageError('usage_operation_conflict', 'This speech reservation is not ready to settle.', 409)
        with get_store().transaction() as conn:
            row = conn.execute(text('SELECT payload,status FROM voice_speech_segments WHERE id=:id AND session_id=:sid AND owner_id=:owner'),
                               {'id': segment_id, 'sid': sid, 'owner': owner}).mappings().first()
            if row and row['status'] == 'speaking':
                payload = json.loads(row['payload'])
                payload.pop('ttsAttemptId', None)
                conn.execute(text("UPDATE voice_speech_segments SET status='synthesized',payload=:payload WHERE id=:id AND session_id=:sid AND owner_id=:owner AND status='speaking'"),
                             {'payload': encode(payload), 'id': segment_id, 'sid': sid, 'owner': owner})
        return {'settled': True}

    @router.post('/internal/voice/{sid}/playback')
    def playback(sid: str, body: Playback, owner=Depends(agent_identity)):
        with get_store().transaction() as conn:
            session = records.session(owner, sid, conn, active=True)
            conn.execute(text('UPDATE voice_speech_segments SET status=:status WHERE id=:id AND session_id=:sid AND owner_id=:owner'), {'status': body.status if body.epoch == session['epoch'] else 'interrupted', 'id': body.segment_id, 'sid': sid, 'owner': owner})
        return {'ok': True}

    @router.post('/internal/voice/{sid}/end')
    def agent_end(sid: str, owner=Depends(agent_identity)):
        _settle_voice_session(Ledger(get_store(), Policy.load()), owner, sid)
        return public(records.end(owner, sid, 'agent_disconnected'))

    @router.post('/internal/voice/{sid}/interrupt')
    def agent_interrupt(sid: str, owner=Depends(agent_identity)):
        return interrupt_session(owner, sid)

    @router.post('/internal/voice/{sid}/idle-warning')
    def idle_warning(sid: str, owner=Depends(agent_identity)):
        with get_store().transaction() as conn:
            records.session(owner, sid, conn, active=True)
            records.emit(conn, owner, sid, 'session.idle_warning', {'message': 'Still studying? Voice will end in one minute unless you speak.'})
        return {'ok': True}

    return router
