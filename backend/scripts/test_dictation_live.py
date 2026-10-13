"""Explicit, paid local acceptance against the actual Deepgram streaming service."""
import json
import os
import logging
import sys
import time
import wave
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / 'backend/.env')
# Isolate this STT acceptance process from unrelated paid capabilities.
os.environ.update(OPENLEARN_USAGE_PAID_ROUTES_ENABLED='true', OPENLEARN_SANDBOX_ENABLED='false', AI_TUTOR_WEB_EVIDENCE='false', OPENLEARN_VOICE_ENABLED='false', OPENLEARN_CLOUD_BROWSER_ENABLED='false', AI_TUTOR_MODE_CLASSIFICATION='rules', AI_TUTOR_EMBEDDING_MODEL='off')
logging.getLogger('alembic').setLevel(logging.ERROR)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.identity import Principal, principal_context
from backend.app.dictation_routes import build_dictation_router


def main():
    directory = ROOT / 'work/dictation-live'
    directory.mkdir(parents=True, exist_ok=True)
    with wave.open(str(directory / 'test-speech.wav'), 'rb') as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        assert channels == 1 and width == 2, 'Test audio must be mono 16-bit PCM.'
        audio = wav.readframes(wav.getnframes())
    store = Store(directory / f'acceptance-{time.time_ns()}.sqlite')
    app = FastAPI()
    app.include_router(build_dictation_router(lambda: store))
    identity = principal_context.set(Principal('dictation_local_acceptance', 'local'))
    started = time.monotonic()
    try:
        with TestClient(app) as client:
            capability = client.get('/v1/dictation/capability').json()
            assert capability['available'], 'Local dictation configuration is unavailable.'
            response = client.post('/v1/dictation/sessions', json={'sampleRate': rate}, headers={'Idempotency-Key': f'live-{time.time_ns()}'})
            assert response.status_code == 200, f'Session admission failed: HTTP {response.status_code}'
            session = response.json()
            events = []
            with client.websocket_connect('/v1/dictation/stream') as socket:
                socket.send_json({'ticket': session['ticket']})
                ready = socket.receive_json()
                assert ready['type'] == 'ready', 'The speech provider could not connect; check the local key and network.'
                for offset in range(0, len(audio), 4096):
                    socket.send_bytes(audio[offset:offset+4096])
                    time.sleep(4096 / (rate * 2))
                socket.send_json({'type': 'finish'})
                while True:
                    event = socket.receive_json()
                    events.append(event)
                    if event['type'] in {'completed', 'error'}:
                        break
            transcript = ' '.join(event['text'] for event in events if event['type'] == 'transcript.final')
            assert events[-1]['type'] == 'completed', 'Live dictation did not finalize.'
            assert 'gravity' in transcript.lower(), 'Expected test phrase was not recognized.'
            with store.engine.connect() as connection:
                receipt = dict(connection.execute(text('SELECT source,cost_nano,receipt_id,payload FROM usage_events WHERE reservation_id=:id'), {'id': session['id']}).mappings().one())
                state = connection.execute(text('SELECT state FROM usage_reservations WHERE id=:id'), {'id': session['id']}).scalar_one()
            assert state == 'settled' and receipt['source'] == 'exact' and receipt['receipt_id'], 'Provider-duration accounting was not settled.'
            with client.websocket_connect('/v1/dictation/stream') as replay:
                replay.send_json({'ticket': session['ticket']})
                assert replay.receive_json()['type'] == 'error', 'Used tickets must not start another paid stream.'
            cancelled_response = client.post('/v1/dictation/sessions', json={'sampleRate': rate}, headers={'Idempotency-Key': f'cancel-{time.time_ns()}'})
            assert cancelled_response.status_code == 200
            cancelled = cancelled_response.json()
            with client.websocket_connect('/v1/dictation/stream') as cancellation:
                cancellation.send_json({'ticket': cancelled['ticket']})
                assert cancellation.receive_json()['type'] == 'ready'
                cancellation.send_bytes(audio[:4096])
                cancellation.send_json({'type': 'cancel'})
            with store.engine.connect() as connection:
                cancelled_state = connection.execute(text('SELECT state FROM usage_reservations WHERE id=:id'), {'id': cancelled['id']}).scalar_one()
            assert cancelled_state == 'settled', 'Cancelled provider work must stop and settle its reservation.'
            report = {'status': 'passed', 'audioSeconds': len(audio) / (rate * 2), 'transcript': transcript,
                      'completed': True, 'replayRejected': True, 'cancelledSessionSettled': True, 'usage': receipt, 'elapsedSeconds': round(time.monotonic() - started, 2),
                      'scope': 'Real Deepgram provider through local backend routes; browser microphone capture is separate.'}
            (directory / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
    finally:
        principal_context.reset(identity)
        store.close()


if __name__ == '__main__':
    main()
