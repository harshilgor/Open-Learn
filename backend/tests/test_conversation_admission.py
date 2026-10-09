import json
import pytest
from sqlalchemy import text
from backend.tests.test_agent_execution import env
from backend.app.agent_execution.admission import plan_message
from backend.app.agent_execution.contracts import Message
from backend.app.agent_execution.coordinator import Coordinator
from backend.app.browser_assistant.intent import compile_intent


@pytest.mark.parametrize('message,target', [
    ('can you check my canvas out', 'browser'), ('open YouTube', 'browser'),
    ('visit example.org', 'browser'), ('open my company portal', 'browser'),
    ('go through my courses on Canvas', 'browser'), ('research spaced repetition', 'research'),
    ('remind me tomorrow at 7 to study', 'reminder'), ('make flashcards from this lesson', 'flashcards'),
    ('analyze my lab results', 'analysis'), ('draft an email to my professor', 'connected_action'),
    ("What's on my calendar tomorrow?", 'calendar_read'), ('What meetings do I have next week?', 'calendar_read'),
    ('Show my schedule today', 'calendar_read'), ("What's my calendar look like tomorrow?", 'calendar_read'),
    ('Create a calendar event tomorrow', 'connected_action'),
    ('Explain gravity', 'direct'), ('Explain how to open YouTube', 'direct'),
    ("Don't open YouTube", 'direct'), ('Open the lesson', 'direct'),
])
def test_shared_routing(message, target):
    assert plan_message(message).kind == target


def test_known_public_origin_and_unknown_private_origin():
    assert plan_message('open youtube').source_url == 'https://www.youtube.com'
    assert plan_message('visit example.org').source_url == 'https://example.org'
    assert plan_message('open my university portal').source_url is None


def test_new_websites_use_selected_local_companion(env, monkeypatch):
    from backend.app.browser_assistant.connections import Connections
    from backend.app.browser_assistant.intent import fallback_intent
    store, _, _ = env
    monkeypatch.setenv('OPENLEARN_BROWSER_DEFAULT_EXECUTOR', 'local')
    connections = Connections(store)
    site = connections.resolve('alice', {'message':'open YouTube'}, fallback_intent('open YouTube'))
    assert site['executor'] == 'local'
    assert site['status'] == 'unpaired'
    assert site['origin'] == 'https://www.youtube.com'
    assert connections.resolve('alice', {'message':'open YouTube'}, fallback_intent('open YouTube'))['id'] == site['id']


def test_invalid_default_executor_cannot_silently_fall_back(env, monkeypatch):
    from backend.app.browser_assistant.connections import Connections
    from backend.app.browser_assistant.intent import fallback_intent
    from fastapi import HTTPException
    store, _, _ = env
    monkeypatch.setenv('OPENLEARN_BROWSER_DEFAULT_EXECUTOR', 'typo')
    with pytest.raises(HTTPException) as error:
        Connections(store).resolve('alice', {'message':'open YouTube'}, fallback_intent('open YouTube'))
    assert error.value.status_code == 503


def test_explicit_browser_request_cannot_be_vetoed_by_classifier():
    class Provider:
        def complete_json(self, *args, **kwargs):
            raise AssertionError('An explicit browser request must not need classification.')
    canvas = compile_intent('can you check my canvas out', Provider())
    assert canvas.handled and 'discover_courses' in canvas.operations
    assert not canvas.save
    youtube = compile_intent('open YouTube', Provider())
    assert youtube.handled and youtube.source_url == 'https://www.youtube.com'


def test_browser_admission_owns_one_message_and_one_legacy_task(env):
    store, _, _ = env
    coordinator = Coordinator(store)
    message = Message(clientMessageId='browser-request', sessionId='session', text='open YouTube')
    first = coordinator.admit('alice', message, 'browser-key')
    assert first['handled'] and first['runtimeOwner'] == 'browser_legacy'
    assert coordinator.admit('alice', message, 'browser-key') == first
    with store.engine.connect() as connection:
        task = connection.execute(text('SELECT runtime_owner,payload FROM assistant_runs WHERE id=:id'), {'id': first['references'][0]['id']}).mappings().one()
        assert task['runtime_owner'] == 'browser_legacy'
        assert json.loads(task['payload'])['message'] == 'open YouTube'
        assert connection.execute(text('SELECT COUNT(*) FROM agent_messages')).scalar_one() == 1


def test_browser_failure_does_not_route_into_ordinary_tutoring(env, monkeypatch):
    store, _, _ = env
    monkeypatch.setenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'false')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        Coordinator(store).admit('alice', Message(clientMessageId='disabled', sessionId='session', text='open YouTube'), 'disabled')
    assert failure.value.status_code == 503


def test_course_scope_is_checked_before_browser_creation(env):
    store, _, _ = env
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        Coordinator(store).admit('alice', Message(clientMessageId='foreign', sessionId='session', courseId='foreign-course', text='open YouTube'), 'foreign')


def test_research_no_longer_requires_a_capability_selector(env):
    store, _, _ = env
    result = Coordinator(store).admit('alice', Message(clientMessageId='research', sessionId='session', text='research spaced repetition'), 'research')
    assert result['handled'] and result['status'] == 'queued'


def test_missing_analysis_input_does_not_run_sample_data(env):
    store, _, _ = env
    result = Coordinator(store).admit('alice', Message(clientMessageId='analysis', sessionId='session', text='analyze my lab results'), 'analysis')
    assert result['handled'] and result['status'] == 'needs_input'
    assert not result['references']
    assert 'Attach the dataset' in result['question']


def test_chat_preference_commits_once_and_never_saves_credentials(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.agent_execution.routes import build_agent_router
    from backend.app.identity import Principal, principal_context
    store, _, _ = env
    app = FastAPI(); app.include_router(build_agent_router(lambda:store))
    token = principal_context.set(Principal('alice','local'))
    try:
        with TestClient(app) as client:
            body = {'clientMessageId':'memory','sessionId':'session','text':'Remember that I prefer worked examples'}
            first = client.post('/v1/assistant/messages',json=body,headers={'Idempotency-Key':'memory'})
            assert first.status_code == 202, first.text
            assert first.json()['memorySourceId']
            assert client.post('/v1/assistant/messages',json=body,headers={'Idempotency-Key':'memory'}).json() == first.json()
            with store.engine.connect() as conn:
                assert conn.execute(text("SELECT COUNT(*) FROM memory_derived WHERE kind='preference'")).scalar_one() == 1
            rejected = client.post('/v1/assistant/messages',json={**body,'clientMessageId':'secret','text':'Remember that my password is not-a-real-password'},headers={'Idempotency-Key':'secret'})
            assert rejected.status_code == 422
            with store.engine.connect() as conn:
                assert conn.execute(text("SELECT COUNT(*) FROM agent_messages WHERE client_message_id='secret'")).scalar_one() == 0
    finally:
        principal_context.reset(token)


def test_execution_memory_excludes_unrequested_other_chat_text(env):
    from backend.app.source_memory import SourceMemory
    store, _, _ = env
    memory = SourceMemory(store)
    memory.revise('alice','other-chat','private unrelated discussion',kind='conversation')
    with store.engine.connect() as conn:
        assert not memory.retrieve(conn,'alice',purpose='execution')
        assert memory.retrieve(conn,'alice',required_ids=['other-chat'],purpose='execution')


def test_single_task_stop_routes_to_the_existing_execution_owner(env):
    store, _, _ = env
    coordinator = Coordinator(store)
    created = coordinator.admit('alice',Message(clientMessageId='start',sessionId='session',text='research learning'),'start')
    stopped = coordinator.admit('alice',Message(clientMessageId='stop',sessionId='session',text='stop'),'stop')
    assert stopped['handled'] and stopped['references'][0]['id'] == created['references'][0]['id']
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM assistant_runs WHERE id=:id'),{'id':created['references'][0]['id']}).scalar_one() == 'cancelled'
