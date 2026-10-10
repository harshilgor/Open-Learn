import hashlib
import json
import time
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.identity import Principal, principal_context
from backend.app.storage import Store
from backend.app.voice.store import VoiceStore, encode, fingerprint
from backend.app.voice.coordinator import Coordinator
from backend.app.voice.routes import build_voice_router
from backend.app.voice.tools import Tools

def test_workspace_voice_actions_use_owned_selected_note(env,monkeypatch,tmp_path):
    store,_,_=env
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(tmp_path/'notes'))
    from backend.app.workspace_note_service import WorkspaceNoteService
    from backend.app.workspace_note_models import WorkspaceNoteCreate
    monkeypatch.setattr('backend.app.voice.tools.MaterialService.session',lambda *args: {})
    note=WorkspaceNoteService(store).create('alice',WorkspaceNoteCreate(title='Biology',body='Photosynthesis stores energy.'))
    tools=Tools(store,None)
    session={'chat_id':'chat-test','context':{'focus':{'note_id':note.id,'expected_revision':1,'selection_start':0,'selection_end':14}}}
    assert tools.execute('alice',session,'workspace_focus',{'focused':True},'focus')['uiIntent']['action']=='focus_workspace'
    result=tools.execute('alice',session,'side_chat_open',{},'side')
    assert result['result']['excerpt']=='Photosynthesis'
    session['context']['focus']['expected_revision']=2
    with pytest.raises(HTTPException) as error:tools.execute('alice',session,'side_chat_open',{},'stale')
    assert error.value.status_code==409


@pytest.fixture
def env(monkeypatch):
    from pathlib import Path
    path = Path('work') / ('voice-' + uuid4().hex + '.db')
    store = Store(path)
    token = principal_context.set(Principal('alice', 'local'))
    records = VoiceStore(store)
    sid = 'voice-test'
    context = {'chat_id': 'chat-test', 'timezone': 'America/Los_Angeles', 'language': 'en', 'consent': True, 'focus': {'revision': 0}}
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO voice_sessions(id,owner_id,chat_id,command_key,request_hash,status,created_at,expires_at,last_seen,capability_hash,payload) VALUES(:id,'alice','chat-test','key',:hash,'active',:now,:expires,:now,:cap,:payload)"), {'id': sid, 'hash': fingerprint(context), 'now': time.time(), 'expires': time.time()+1800, 'cap': hashlib.sha256(b'test-capability').hexdigest(), 'payload': encode(context)})
        conn.execute(text("INSERT INTO voice_usage(id,owner_id,session_id,created_at,reserved_seconds) VALUES('usage','alice',:id,:now,1800)"), {'id': sid, 'now': time.time()})
    yield store, records, sid
    principal_context.reset(token)
    store.close()
    path.unlink(missing_ok=True)


def test_owner_replay_and_conflicting_utterance(env):
    store, records, sid = env
    with pytest.raises(HTTPException): records.session('bob', sid)
    with store.transaction() as conn:
        first, fresh = records.record(conn, 'turns', 'alice', sid, 'utterance', {'text': 'Create quiz'})
        replay, fresh_again = records.record(conn, 'turns', 'alice', sid, 'utterance', {'text': 'Create quiz'})
        assert fresh and not fresh_again and replay['id'] == first['id']
    with pytest.raises(HTTPException):
        with store.transaction() as conn: records.record(conn, 'turns', 'alice', sid, 'utterance', {'text': 'Delete quiz'})


def test_ordered_events_and_atomic_rollback(env):
    store, records, sid = env
    with store.transaction() as conn:
        assert records.emit(conn, 'alice', sid, 'first', {})['sequence'] == 1
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            records.emit(conn, 'alice', sid, 'rollback', {})
            raise RuntimeError()
    with store.transaction() as conn:
        assert records.emit(conn, 'alice', sid, 'second', {})['sequence'] == 2
    assert [event['type'] for event in records.events('alice', sid, 1)] == ['second']


def test_end_revokes_work_and_settles_usage(env):
    store, records, sid = env
    with store.transaction() as conn: records.record(conn, 'actions', 'alice', sid, 'action', {}, 'awaiting_confirmation')
    records.end('alice', sid)
    records.end('alice', sid)
    with pytest.raises(HTTPException): records.session('alice', sid, active=True)
    assert records.records('alice', sid, 'actions')[0]['status'] == 'cancelled'
    assert len([e for e in records.events('alice', sid) if e['type'] == 'session.ended']) == 1
    with store.engine.connect() as conn: assert conn.execute(text('SELECT settled_seconds FROM voice_usage')).scalar_one() is not None


def test_janitor_retries_room_close_after_ending(env, monkeypatch):
    from backend.app.voice.maintenance import tick
    store, records, sid = env
    with store.transaction() as conn:
        conn.execute(text('UPDATE voice_sessions SET expires_at=0 WHERE id=:id'), {'id': sid})
    attempts = []
    settlements = []
    async def close(room):
        attempts.append(room)
        if len(attempts) == 1:
            raise RuntimeError('temporary provider failure')
    monkeypatch.setattr('backend.app.voice.media.control_configured', lambda: True)
    monkeypatch.setattr('backend.app.voice.media.close', close)
    monkeypatch.setattr('backend.app.voice.routes._settle_voice_session', lambda ledger, owner, room: settlements.append(room))
    assert tick(store, prune_events=False) == 1
    assert records.session('alice', sid)['status'] == 'ended'
    assert records.session('alice', sid)['room_closed_at'] is None
    assert tick(store, prune_events=False) == 1
    assert records.session('alice', sid)['room_closed_at'] is not None
    assert tick(store, prune_events=False) == 0
    assert attempts == [sid, sid] and settlements == [sid, sid]


def test_janitor_closes_media_even_when_accounting_fails(env, monkeypatch):
    from backend.app.voice.maintenance import tick
    store, records, sid = env
    records.end('alice', sid)
    closed = []
    async def close(room):
        closed.append(room)
    def unavailable(*args):
        raise RuntimeError('accounting unavailable')
    monkeypatch.setattr('backend.app.voice.media.control_configured', lambda: True)
    monkeypatch.setattr('backend.app.voice.media.close', close)
    monkeypatch.setattr('backend.app.voice.routes._settle_voice_session', unavailable)
    assert tick(store, prune_events=False) == 1
    assert closed == [sid]


@pytest.mark.parametrize('code,accepted', [('not_found', True), ('bad_route', False)])
def test_room_delete_only_accepts_known_absent_room(monkeypatch, code, accepted):
    import asyncio
    import httpx
    from backend.app.voice import media
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return httpx.Response(404, json={'code': code})
    monkeypatch.setenv('LIVEKIT_URL', 'https://example.test')
    monkeypatch.setattr(media, 'token', lambda *args, **kwargs: 'test-token')
    monkeypatch.setattr(media.httpx, 'AsyncClient', Client)
    if accepted:
        assert asyncio.run(media.close('voice-test')) == {}
    else:
        with pytest.raises(HTTPException):
            asyncio.run(media.close('voice-test'))


def test_executed_action_not_replayed(env, monkeypatch):
    store, records, sid = env
    coordinator = Coordinator(store, None)
    seen = []
    monkeypatch.setattr(coordinator.tools, 'execute', lambda *args: seen.append(args) or {'status': 'succeeded', 'userMessage': 'Scheduled.'})
    with store.transaction() as conn:
        action, _ = records.record(conn, 'actions', 'alice', sid, 'reminder', {'tool': 'reminder_create', 'arguments': {}, 'focus': {}, 'expiresAt': time.time()+120})
    coordinator.execute('alice', records.session('alice', sid), action)
    coordinator.execute('alice', records.session('alice', sid), action)
    assert len(seen) == 1
    assert records.records('alice', sid, 'actions')[0]['status'] == 'succeeded'


def test_unknown_effect_is_not_retried(env, monkeypatch):
    store, records, sid = env
    coordinator = Coordinator(store, None)
    def fail_after_effect(*args): raise RuntimeError('private provider error')
    monkeypatch.setattr(coordinator.tools, 'execute', fail_after_effect)
    with store.transaction() as conn: action, _ = records.record(conn, 'actions', 'alice', sid, 'note', {'tool': 'note_create', 'arguments': {}, 'focus': {}})
    coordinator.execute('alice', records.session('alice', sid), action)
    saved = records.records('alice', sid, 'actions')[0]
    assert saved['status'] == 'unknown'
    assert 'private' not in encode(saved['data'])


def test_agent_capability_is_session_scoped(env, monkeypatch):
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    from backend.app.voice.routes import _admit_voice_slice
    _admit_voice_slice(store, 'alice', sid, 0)
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    with TestClient(app) as client:
        assert client.get(f'/internal/voice/{sid}/poll').status_code == 401
        assert client.get('/internal/voice/other/poll', headers={'Authorization': 'Bearer test-capability'}).status_code == 401
        assert client.get(f'/internal/voice/{sid}/poll', headers={'Authorization': 'Bearer test-capability'}).status_code == 200


def test_slow_agent_authentication_does_not_block_the_server_loop(env, monkeypatch):
    import asyncio
    import httpx
    from contextlib import contextmanager
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    from backend.app.voice.routes import _admit_voice_slice
    _admit_voice_slice(store, 'alice', sid, 0)
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    original = store.engine.connect
    @contextmanager
    def slow_connect():
        time.sleep(.15)
        with original() as conn:
            yield conn
    monkeypatch.setattr(store.engine, 'connect', slow_connect)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            request = asyncio.create_task(client.get(f'/internal/voice/{sid}/poll', headers={'Authorization':'Bearer invalid'}))
            beats = 0
            while not request.done():
                await asyncio.sleep(.01)
                beats += 1
            response = await request
            assert response.status_code == 401
            assert beats >= 8, 'Synchronous database authentication blocked the event loop'
    asyncio.run(scenario())


def _enable_metered_voice(monkeypatch):
    monkeypatch.setenv('OPENLEARN_USAGE_MODE', 'enforce')
    monkeypatch.setenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_PROVIDER_RATE_VERSION', 'voice-test-rates-v1')
    monkeypatch.setenv('OPENLEARN_VOICE_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_VOICE_LIFECYCLE_VERIFIED', 'true')
    monkeypatch.setenv('OPENLEARN_DEEPGRAM_USD_PER_MINUTE', '0.04')
    monkeypatch.setenv('OPENLEARN_LIVEKIT_AGENT_USD_PER_MINUTE', '0.06')
    monkeypatch.setenv('OPENLEARN_ELEVENLABS_USD_PER_1000_CHARACTERS', '0.30')
    monkeypatch.setattr('backend.app.voice.routes.media.configured', lambda: True)


def test_acceptance_rollout_only_admits_configured_authenticated_email(env, monkeypatch):
    store, _, _ = env
    _enable_metered_voice(monkeypatch)
    monkeypatch.setenv('OPENLEARN_VOICE_LIFECYCLE_VERIFIED', 'false')
    monkeypatch.setenv('OPENLEARN_VOICE_ACCEPTANCE_MODE', 'true')
    monkeypatch.setenv('OPENLEARN_VOICE_TEST_EMAILS', 'tester@example.com')
    monkeypatch.setenv('OPENLEARN_VOICE_SESSION_SECONDS', '120')
    monkeypatch.setenv('OPENLEARN_VOICE_MAX_CONCURRENT', '1')
    from backend.app.voice.routes import _voice_usage_ready, _voice_account_allowed
    assert _voice_usage_ready()
    for principal, expected in [(Principal('alice', 'local', email='tester@example.com'), False),
                                (Principal('alice', 'web', email='other@example.com'), False),
                                (Principal('alice', 'web', email='tester@example.com'), True)]:
        token = principal_context.set(principal)
        try:
            assert _voice_account_allowed() is expected
        finally:
            principal_context.reset(token)
    monkeypatch.setenv('OPENLEARN_VOICE_MAX_CONCURRENT', '2')
    assert not _voice_usage_ready()
    monkeypatch.setenv('OPENLEARN_VOICE_MAX_CONCURRENT', '1')
    monkeypatch.setenv('OPENLEARN_VOICE_SESSION_SECONDS', 'invalid')
    assert not _voice_usage_ready()


def test_local_voice_acceptance_is_explicitly_development_only(env, monkeypatch):
    _enable_metered_voice(monkeypatch)
    monkeypatch.setenv('OPENLEARN_VOICE_LIFECYCLE_VERIFIED', 'false')
    monkeypatch.setenv('OPENLEARN_VOICE_ACCEPTANCE_MODE', 'true')
    monkeypatch.setenv('OPENLEARN_VOICE_SESSION_SECONDS', '90')
    monkeypatch.setenv('OPENLEARN_VOICE_MAX_CONCURRENT', '1')
    monkeypatch.setenv('OPENLEARN_VOICE_LOCAL_TEST_ENABLED', 'false')
    monkeypatch.setenv('AI_TUTOR_ENV', 'development')
    monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY', 'true')
    from backend.app.voice.routes import _voice_account_allowed, _voice_usage_ready
    token = principal_context.set(Principal('local', 'local'))
    try:
        assert not _voice_account_allowed()
        monkeypatch.setenv('OPENLEARN_VOICE_LOCAL_TEST_ENABLED', 'true')
        assert _voice_usage_ready()
        assert _voice_account_allowed()
        monkeypatch.setenv('AI_TUTOR_ENV', 'production')
        assert not _voice_account_allowed()
    finally:
        principal_context.reset(token)


def test_voice_dispatch_uses_configured_agent_name(monkeypatch):
    from backend.app.voice import media
    monkeypatch.setenv('OPENLEARN_VOICE_AGENT_NAME', 'openlearn-voice-local')
    assert media.configured_agent_name() == 'openlearn-voice-local'


@pytest.mark.parametrize('kind', ['voice_turn', 'voice_action', 'voice_teach'])
def test_interactive_worker_dispatches_durable_voice_jobs_to_correct_executor(env, monkeypatch, kind):
    store, _, sid = env
    from backend.app.execution_worker import ExecutionWorker
    from backend.app.workflow_store import WorkflowStore
    monkeypatch.setattr('backend.app.usage.ledger.Ledger.reconcile', lambda self: 0)
    monkeypatch.setattr('backend.app.worker.monitor_usage_if_due', lambda *args: None)
    monkeypatch.setattr('backend.app.voice.maintenance.tick', lambda *args: 0)
    monkeypatch.setattr('backend.app.execution_outbox.ExecutionOutbox.drain', lambda *args: 0)
    jobs = WorkflowStore(store)
    job = jobs.enqueue('alice', sid, kind, {}, 'worker-voice:' + kind)
    dispatched = []
    monkeypatch.setattr('backend.app.voice.worker.run_voice_job', lambda s, p, j: dispatched.append(('voice', j)))
    monkeypatch.setattr('backend.app.learning_routes.run_job', lambda s, p, j: dispatched.append(('learning', j)))
    ExecutionWorker(store, lambda: None).tick()
    assert dispatched == [('learning' if kind == 'voice_teach' else 'voice', job['id'])]


def test_voice_slices_are_reserved_once_and_replayed_with_same_deadline(env, monkeypatch):
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    headers = {'Authorization': 'Bearer test-capability'}
    with TestClient(app) as client:
        first = client.post(f'/internal/voice/{sid}/slice', json={'slice_index': 0}, headers=headers)
        replay = client.post(f'/internal/voice/{sid}/slice', json={'slice_index': 0}, headers=headers)
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()['replayed'] is True
    assert replay.json()['nextAt'] == first.json()['nextAt']
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT component,state,payload FROM usage_reservations WHERE owner_id='alice' AND root_id=:sid ORDER BY component"), {'sid': sid}).mappings().all()
    assert [(row['component'], row['state']) for row in rows] == [('stt', 'dispatched'), ('voice', 'dispatched')]
    assert all(json.loads(row['payload'])['providerRates']['providerRateVersion'] == 'voice-test-rates-v1' for row in rows)


def test_voice_renewal_overlap_is_bounded_and_metered(env, monkeypatch):
    from backend.app.voice.routes import _admit_voice_slice
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    first = _admit_voice_slice(store, 'alice', sid, 0)
    with pytest.raises(HTTPException) as early:
        _admit_voice_slice(store, 'alice', sid, 1)
    assert early.value.detail['code'] == 'voice_slice_early'
    with store.engine.begin() as conn:
        conn.execute(text('UPDATE usage_reservations SET created_at=created_at-11 WHERE root_id=:sid'), {'sid': sid})
    second = _admit_voice_slice(store, 'alice', sid, 1)
    replay = _admit_voice_slice(store, 'alice', sid, 1)
    assert second['nextAt'] > first['nextAt']-11
    assert replay['nextAt'] == second['nextAt']
    with store.engine.connect() as conn:
        rows = conn.execute(text('SELECT state FROM usage_reservations WHERE root_id=:sid'), {'sid': sid}).scalars().all()
    assert sorted(rows) == ['dispatched', 'dispatched', 'settled', 'settled']


def test_poll_keeps_current_paid_interval_during_partial_renewal_and_still_expires(env, monkeypatch):
    from backend.app.voice.routes import _admit_voice_slice, _current_voice_slice, _voice_slice_keys
    from backend.app.usage.ledger import Ledger
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    first = _admit_voice_slice(store, 'alice', sid, 0)
    ledger = Ledger(store)
    pending = ledger.reserve('alice', _voice_slice_keys(sid,1)[0], 'voice', {'milliseconds':15000}, root=sid)
    with store.engine.begin() as conn:
        conn.execute(text('UPDATE usage_reservations SET created_at=:started WHERE id=:id'), {'started':first['startedAt']+2,'id':pending['id']})
    assert _current_voice_slice(store,'alice',sid)['index'] == 0
    ledger.dispatch('alice',pending['id'])
    assert _current_voice_slice(store,'alice',sid)['index'] == 0
    import backend.app.voice.routes as routes
    app=FastAPI();app.include_router(build_voice_router(lambda:store,lambda:None))
    with TestClient(app) as client:
        monkeypatch.setattr(routes.time,'time',lambda:first['startedAt']+10)
        assert client.get(f'/internal/voice/{sid}/poll',headers={'Authorization':'Bearer test-capability'}).status_code == 200
        monkeypatch.setattr(routes.time,'time',lambda:first['nextAt']+3)
        assert client.get(f'/internal/voice/{sid}/poll',headers={'Authorization':'Bearer test-capability'}).status_code == 409


def test_voice_slice_cannot_be_replayed_after_its_reserved_interval(env, monkeypatch):
    store, records, sid = env
    _enable_metered_voice(monkeypatch)
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    headers = {'Authorization': 'Bearer test-capability'}
    with TestClient(app) as client:
        first = client.post(f'/internal/voice/{sid}/slice', json={'slice_index': 0}, headers=headers)
        assert first.status_code == 200, first.text
        import backend.app.voice.routes as voice_routes
        original = voice_routes.time.time
        monkeypatch.setattr(voice_routes.time, 'time', lambda: original() + 20)
        expired_replay = client.post(f'/internal/voice/{sid}/slice', json={'slice_index': 0}, headers=headers)
    assert expired_replay.status_code == 409
    assert records.session('alice', sid)['status'] == 'ended'
    with store.engine.connect() as conn:
        states = conn.execute(text('SELECT DISTINCT state FROM usage_reservations WHERE root_id=:sid'), {'sid': sid}).scalars().all()
    assert states == ['settled']


def test_hosted_voice_interval_reserves_full_bound_and_returns_renewal_lead(env, monkeypatch):
    import backend.app.voice.routes as routes
    store, _, sid = env
    _enable_metered_voice(monkeypatch)
    monkeypatch.setenv('OPENLEARN_FREE_CREDITS_MICRO', '1000000000')
    monkeypatch.setattr(routes, 'VOICE_SLICE_SECONDS', 60)
    monkeypatch.setattr(routes, 'VOICE_SLICE_MILLISECONDS', 60000)
    monkeypatch.setattr(routes, 'VOICE_SLICE_RENEWAL_LEAD_SECONDS', 30)
    first = routes._admit_voice_slice(store, 'alice', sid, 0)
    assert first['nextAt']-first['startedAt'] == 60
    assert first['renewalLeadSeconds'] == 30
    replay = routes._admit_voice_slice(store, 'alice', sid, 0)
    assert replay['nextAt'] == first['nextAt']
    assert replay['renewalLeadSeconds'] == 30
    with store.engine.connect() as conn:
        rows = conn.execute(text('SELECT payload FROM usage_reservations WHERE root_id=:sid'), {'sid': sid}).scalars().all()
    assert len(rows) == 2
    assert all(json.loads(row)['maximumQuantities'] == {'milliseconds':60000} for row in rows)


def test_voice_tts_is_preflighted_idempotently_and_settled(env, monkeypatch):
    store, records, sid = env
    _enable_metered_voice(monkeypatch)
    with store.transaction() as conn:
        segment, fresh = records.record(conn, 'speech_segments', 'alice', sid, 'test-speech', {'text': 'Hello Buddy.', 'epoch': 0}, 'released')
    assert fresh
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    headers = {'Authorization': 'Bearer test-capability'}
    path = f'/internal/voice/{sid}/speech/{segment["id"]}/tts-preflight'
    attempt = 'a' * 32
    with TestClient(app) as client:
        first = client.post(path, json={'attempt_id': attempt, 'characters': len('Hello Buddy.')}, headers=headers)
        replay = client.post(path, json={'attempt_id': attempt, 'characters': len('Hello Buddy.')}, headers=headers)
        other_attempt = client.post(path, json={'attempt_id': 'b' * 32, 'characters': len('Hello Buddy.')}, headers=headers)
        assert first.status_code == 200, first.text
        assert replay.status_code == 200 and replay.json()['reservationId'] == first.json()['reservationId']
        assert other_attempt.status_code == 409
        complete_path = f'/internal/voice/{sid}/speech/{segment["id"]}/tts-complete'
        complete = {'reservation_id': first.json()['reservationId']}
        assert client.post(complete_path, json=complete, headers=headers).status_code == 200
        assert client.post(complete_path, json=complete, headers=headers).status_code == 200
    with store.engine.connect() as conn:
        state = conn.execute(text('SELECT state FROM usage_reservations WHERE id=:id'), {'id': first.json()['reservationId']}).scalar_one()
        status = conn.execute(text('SELECT status FROM voice_speech_segments WHERE id=:id'), {'id': segment['id']}).scalar_one()
    assert state == 'settled'
    assert status == 'synthesized'


def test_voice_usage_rates_are_required_before_slice_admission(env, monkeypatch):
    store, records, sid = env
    _enable_metered_voice(monkeypatch)
    monkeypatch.delenv('OPENLEARN_DEEPGRAM_USD_PER_MINUTE')
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    with TestClient(app) as client:
        response = client.post(f'/internal/voice/{sid}/slice', json={'slice_index': 0}, headers={'Authorization': 'Bearer test-capability'})
    assert response.status_code == 503
    assert records.session('alice', sid)['status'] == 'ended'
    with store.engine.connect() as conn:
        count = conn.execute(text('SELECT count(*) FROM usage_reservations WHERE root_id=:sid'), {'sid': sid}).scalar_one()
    assert count == 0


def test_quiz_requires_current_revision(env, monkeypatch):
    store, records, sid = env
    service = Tools(store, None)
    monkeypatch.setattr('backend.app.voice.tools.MaterialService.session', lambda *args: None)
    monkeypatch.setattr(service, 'validate_focus', lambda *args: None)
    monkeypatch.setattr(service, 'quiz', lambda *args: {'id': 'quiz', 'revision': 4, 'current': {'id': 'presentation'}})
    session = records.session('alice', sid)
    session['context']['focus'] = {'quiz_id': 'quiz', 'expected_revision': 3, 'presentation_id': 'presentation'}
    with pytest.raises(HTTPException) as exc: service.execute('alice', session, 'quiz_answer', {'response': 'B'}, 'answer')
    assert exc.value.status_code == 409


def test_schema_rejects_untrusted_owner_or_arbitrary_code():
    from backend.app.voice.tools import REGISTRY
    from pydantic import ValidationError
    with pytest.raises(ValidationError): REGISTRY['quiz_create'][0].model_validate({'topic': 'biology', 'owner': 'bob'})
    with pytest.raises(ValidationError): REGISTRY['visual_update'][0].model_validate({'parameter_id': 'rate', 'value': 1, 'script': 'alert(1)'})


def test_real_quiz_grade_note_reminder_flow(env, monkeypatch):
    from backend.app.graph_generator import GraphGenerator
    from backend.app.models import TopicScope, utc_now
    from backend.app.session_models import LearningSession, LessonArtifact, LessonBlock, TeachingGear
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    from backend.app.learner_graph import LearnerGraphRepository
    from backend.app.learning_routes import run_job
    from backend.app.quiz_service import QuizService
    from backend.tests.test_learning_workflows import Provider
    from backend.app.workspace_note_service import WorkspaceNoteService
    store, records, sid = env
    monkeypatch.setenv('OPENLEARN_CHAT_REMINDERS', 'true')
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR', 'work/voice-notes-'+uuid4().hex)
    scope = TopicScope(id='scope-test', topic='probability', resolved_meaning='probability', objective='conditional probability', depth='introductory', created_at=utc_now())
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope); store.save_graph(graph)
    chat = LearningSession(id='chat-test', learner_id='alice', graph_id=graph.id, goal='conditional probability', created_at=utc_now(), updated_at=utc_now())
    store.save_session(chat); LearnerGraphRepository(store).import_topic_graph('alice', graph)
    material = MaterialService(store)
    content = b'Conditional probability restricts the population to the conditioning event. Probability uses the reference population.'
    source = material.create('alice', UploadRequest(title='Probability reference', media_type='text/plain', byte_count=len(content)))
    material.upload('alice', source['materialId'], source['versionId'], content); material.process_one(); material.attach('alice', chat.id, source['versionId'])
    provider = Provider(); tools = Tools(store, provider)
    session = records.session('alice', sid)
    created = tools.execute('alice', session, 'quiz_create', {'topic': 'conditional probability', 'count': 1}, 'quiz-create')
    run_job(store, provider, created['jobId'])
    from backend.app.workflow_store import WorkflowStore
    qid = WorkflowStore(store).job('alice', created['jobId'])['result']['quizId']
    quiz = QuizService(store, provider).public('alice', qid)
    session['context']['focus'] = {'quiz_id': qid, 'expected_revision': quiz['revision']}
    next_job = tools.execute('alice', session, 'quiz_next', {}, 'quiz-next'); run_job(store, provider, next_job['jobId'])
    quiz = QuizService(store, provider).public('alice', qid)
    session['context']['focus'].update(expected_revision=quiz['revision'], presentation_id=quiz['current']['id'])
    correct_index = next(index for index, option in enumerate(quiz['current']['options']) if option['id'] == 'b')
    answer = tools.execute('alice', session, 'quiz_answer', {'response': chr(ord('A') + correct_index)}, 'quiz-answer'); run_job(store, provider, answer['jobId'])
    graded = QuizService(store, provider).public('alice', qid)
    assert graded['attempts'][0]['score'] == 1
    artifact = LessonArtifact(id='lesson-test', session_id=chat.id, concept_id=graph.concepts[0].id, graph_revision=1, gear=TeachingGear.quick, title='Conditioning', generated_by='test', blocks=[LessonBlock(id='block-test', kind='explanation', heading='Conditioning', body='Conditioning restricts the population.', order=0)])
    store.save_artifact(artifact)
    session['context']['focus'] = {'lesson_id': artifact.id}
    note = tools.execute('alice', session, 'note_create', {}, 'note-command')
    replay = tools.execute('alice', session, 'note_create', {}, 'note-command')
    assert replay['artifactRef']['id'] == note['artifactRef']['id']
    assert WorkspaceNoteService(store).get('alice', note['artifactRef']['id']).body == 'Conditioning restricts the population.'
    reminder = tools.execute('alice', session, 'reminder_create', {'when': 'in 10 minutes', 'message': 'Review conditioning'}, 'reminder-command')
    assert reminder['status'] == 'succeeded' and reminder['result']['dueAt'] > time.time()


def test_expired_confirmation_rejected(env):
    store, records, sid = env
    with store.transaction() as conn:
        action, _ = records.record(conn, 'actions', 'alice', sid, 'cancel', {'tool': 'reminder_cancel', 'arguments': {'reminder_id': 'reminder'}, 'expiresAt': time.time()-1, 'focus': {}}, 'awaiting_confirmation')
    app = FastAPI(); app.include_router(build_voice_router(lambda: store, lambda: None))
    with TestClient(app) as client:
        result = client.post('/v1/voice/actions/'+action['id']+'/confirm', json={'arguments_hash': fingerprint({'reminder_id': 'reminder'}), 'approve': True})
        assert result.status_code == 409
