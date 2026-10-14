import asyncio
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.class_streaming import build_class_streaming_router
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.in_class_models import ClassCreate
from backend.app.in_class_service import InClassService
from backend.app.storage import Store


class Upstream:
    async def __aenter__(self):
        self.events = asyncio.Queue()
        await self.events.put(json.dumps({'type': 'Begin', 'configuration': {'model': 'universal-3-6-pro'}}))
        return self
    async def __aexit__(self, *args):
        return False
    def __aiter__(self):
        return self
    async def __anext__(self):
        value = await self.events.get()
        if value is None:
            raise StopAsyncIteration
        return value
    async def send(self, frame):
        if isinstance(frame, bytes):
            await self.events.put(json.dumps({'type': 'Turn', 'turn_order': 1, 'end_of_turn': True, 'transcript': 'A cell has a membrane.', 'words': [{'start': 0, 'end': 90}]}))
        else:
            await self.events.put(None)


def test_live_relay_auth_persistence_and_ticket_replay(monkeypatch):
    root = Path('work') / ('class-stream-' + uuid4().hex)
    root.mkdir(parents=True)
    for name, value in {'AI_TUTOR_NOTE_VAULT_DIR': str(root / 'notes'), 'AI_TUTOR_RECORDINGS_DIR': str(root / 'audio'),
                        'OPENLEARN_CLASS_STREAMING_ENABLED': 'true', 'OPENLEARN_CLASS_STREAM_SECRET': 's' * 64,
                        'ASSEMBLYAI_API_KEY': 'private-key', 'OPENLEARN_USAGE_PAID_ROUTES_ENABLED': 'true',
                        'OPENLEARN_PROVIDER_RATE_VERSION': 'test-rates', 'OPENLEARN_ASSEMBLYAI_STREAMING_USD_PER_MINUTE': '.0075'}.items():
        monkeypatch.setenv(name, value)
    store = Store(root / 'data.sqlite')
    try:
        body = ClassCreate(recording={'id': 'rec_' + uuid4().hex, 'title': 'Biology', 'startedAtMs': 1}, deviceId='phone', captureCapability='c' * 64)
        snapshot = InClassService(store).create('alice', body)
        class_id = snapshot['session']['id']
        app = FastAPI()
        app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
        def connect(url, **kwargs):
            assert 'speech_model=universal-3-6-pro' in url
            assert kwargs['additional_headers']['Authorization'] == 'private-key'
            return Upstream()
        app.include_router(build_class_streaming_router(lambda: store, connect))
        with TestClient(app) as client:
            headers = {'X-Dev-Learner-Id': 'alice', 'X-Capture-Capability': 'c' * 64, 'Idempotency-Key': 'start-one'}
            path = '/v1/class-sessions/' + class_id
            result = client.post(path + '/transcription-sessions', headers=headers, json={'anchorMs': 1000})
            assert result.status_code == 200, result.text
            ticket = result.json()['ticket']
            with client.websocket_connect(path + '/audio-stream') as websocket:
                websocket.send_json({'ticket': ticket})
                assert websocket.receive_json()['type'] == 'ready'
                websocket.send_bytes(b'\0' * 3200)
                assert websocket.receive_json()['text'] == 'A cell has a membrane.'
            with client.websocket_connect(path + '/audio-stream') as websocket:
                websocket.send_json({'ticket': ticket})
                assert websocket.receive_json()['type'] == 'error'
        with store.engine.connect() as conn:
            segment = conn.execute(text('SELECT transcript,start_ms,end_ms FROM class_live_transcript_segments WHERE class_id=:class'), {'class': class_id}).mappings().one()
            assert segment['start_ms'] == 1000 and segment['end_ms'] == 1090
            assert conn.execute(text("SELECT COUNT(*) FROM usage_events WHERE owner_id='alice' AND component='stt'")).scalar_one() == 1
    finally:
        store.close()
