import asyncio
import json
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.tests.test_agent_execution import env
from backend.app.identity import Principal, principal_context
from backend.app.dictation_routes import build_dictation_router


class Provider:
    metadata = {'type': 'Metadata', 'request_id': 'test-provider-receipt', 'duration': 1}
    def __init__(self):
        self.events = asyncio.Queue()
        self.closed = False
        self.audio = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, value):
        if isinstance(value, bytes):
            self.audio.append(value)
        elif json.loads(value)['type'] == 'CloseStream':
            event = {'type': 'Results', 'is_final': True, 'start': 0, 'duration': 1, 'channel': {'alternatives': [{'transcript': 'Study physics.'}]}}
            await self.events.put(json.dumps(event))
            if self.metadata is not None:
                await self.events.put(json.dumps(self.metadata))
            await self.events.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.events.get()
        if value is None:
            raise StopAsyncIteration
        return value


@pytest.fixture
def client(env, monkeypatch):
    store, _, _ = env
    monkeypatch.setenv('OPENLEARN_DICTATION_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_DICTATION_SECRET', 'test-secret-' * 4)
    monkeypatch.setenv('DEEPGRAM_API_KEY', 'offline-test')
    monkeypatch.setenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_PROVIDER_RATE_VERSION', 'test-v1')
    monkeypatch.setenv('OPENLEARN_DICTATION_USD_PER_MINUTE', '0.01')
    providers = []
    def connect(*args, **kwargs):
        provider = Provider()
        providers.append(provider)
        return provider
    app = FastAPI()
    app.include_router(build_dictation_router(lambda: store, connect))
    token = principal_context.set(Principal('alice', 'local'))
    try:
        with TestClient(app) as session:
            yield session, store, providers
    finally:
        principal_context.reset(token)


def create(client, key='one'):
    response = client.post('/v1/dictation/sessions', json={'sampleRate': 48000}, headers={'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json()


def test_finalization_and_replay_use_one_provider_and_settle(client):
    http, store, providers = client
    session = create(http)
    assert create(http)['id'] == session['id']
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': session['ticket']})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_bytes(b'\0\0' * 256)
        ws.send_json({'type': 'finish'})
        assert ws.receive_json()['text'] == 'Study physics.'
        assert ws.receive_json()['type'] == 'completed'
    assert providers[0].closed
    assert providers[0].audio
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': session['ticket']})
        assert ws.receive_json()['type'] == 'error'
    assert len(providers) == 1
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT state FROM usage_reservations WHERE id=:id'), {'id': session['id']}).scalar_one() == 'settled'
        usage = conn.execute(text('SELECT source,cost_nano,receipt_id,payload FROM usage_events WHERE reservation_id=:id'), {'id': session['id']}).mappings().one()
        assert usage['source'] == 'exact'
        assert usage['receipt_id'] == 'test-provider-receipt'
        assert json.loads(usage['payload']) == {'milliseconds': 1000}
        assert usage['cost_nano'] == 166667


def test_cancel_releases_unused_reservation_and_cannot_stream(client):
    http, store, providers = client
    session = create(http)
    assert http.post(f'/v1/dictation/sessions/{session["id"]}/cancel').status_code == 200
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': session['ticket']})
        assert ws.receive_json()['type'] == 'error'
    assert not providers


def test_bad_ticket_and_oversized_frame_do_not_escape_limits(client):
    http, _, providers = client
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': 'invalid'})
        assert ws.receive_json()['type'] == 'error'
    assert not providers
    session = create(http)
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': session['ticket']})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_bytes(b'a' * 65537)
        assert ws.receive_json()['type'] == 'error'
    assert providers[0].closed
    assert not providers[0].audio


def test_capability_disabled_and_invalid_sample_rate(client, monkeypatch):
    http, _, _ = client
    assert http.post('/v1/dictation/sessions', json={'sampleRate': 96000}, headers={'Idempotency-Key': 'bad'}).status_code == 422
    monkeypatch.setenv('OPENLEARN_DICTATION_ENABLED', 'false')
    assert not http.get('/v1/dictation/capability').json()['available']
    assert http.post('/v1/dictation/sessions', json={'sampleRate': 48000}, headers={'Idempotency-Key': 'disabled'}).status_code == 503


def test_concurrent_reservation_and_expired_ticket(client):
    http, _, providers = client
    session = create(http)
    second = http.post('/v1/dictation/sessions', json={'sampleRate': 48000}, headers={'Idempotency-Key': 'second'})
    assert second.status_code == 409
    claims = jwt.decode(session['ticket'], 'test-secret-' * 4, algorithms=['HS256'], audience='dictation')
    claims['exp'] = 1
    expired = jwt.encode(claims, 'test-secret-' * 4, algorithm='HS256')
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': expired})
        assert ws.receive_json()['type'] == 'error'
    assert not providers


@pytest.mark.parametrize('metadata', [None, {'type': 'Metadata', 'request_id': 'invalid', 'duration': float('nan')}])
def test_uncertain_receipt_keeps_bounded_estimate(client, monkeypatch, metadata):
    http, store, providers = client
    monkeypatch.setattr(Provider, 'metadata', metadata)
    session = create(http)
    with http.websocket_connect('/v1/dictation/stream') as ws:
        ws.send_json({'ticket': session['ticket']})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_json({'type': 'finish'})
        assert ws.receive_json()['type'] == 'transcript.final'
        assert ws.receive_json()['type'] == ('completed' if metadata is None else 'error')
    with store.engine.connect() as conn:
        usage = conn.execute(text('SELECT source,cost_nano FROM usage_events WHERE reservation_id=:id'), {'id': session['id']}).mappings().one()
        assert usage['source'] == 'estimated'
        assert usage['cost_nano'] == 15_000_000
    assert providers[0].closed
