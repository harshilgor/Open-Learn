import hashlib
import io
import json
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.assemblyai_transcription import AssemblyTranscript, AssemblyWord
from backend.app.class_audio_windows import assemble_window
from backend.app.class_verification import ClassVerificationService
from backend.app.in_class_models import ClassCreate
from backend.app.in_class_service import InClassService
from backend.app.lecture_models import LectureFinalize
from backend.app.lecture_provider import TranscriptionFailure
from backend.app.lecture_service import LectureService
from backend.app.storage import Store


@pytest.fixture
def setup(monkeypatch):
    root = Path('work') / ('class-verification-' + uuid4().hex)
    root.mkdir(parents=True)
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR', str(root / 'notes'))
    monkeypatch.setenv('AI_TUTOR_RECORDINGS_DIR', str(root / 'audio'))
    monkeypatch.setenv('OPENLEARN_CLASS_VERIFICATION_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_CLASS_VERIFICATION_MODEL', 'universal-3-5-pro')
    store = Store(root / 'data.sqlite')
    body = ClassCreate(recording={'id': 'rec_' + uuid4().hex, 'title': 'Biology', 'startedAtMs': 1}, deviceId='phone')
    snapshot = InClassService(store).create('alice', body)
    lecture = LectureService(store)
    yield store, lecture, body.recording.id, snapshot['session']['id']
    store.close()


def upload(lecture, recording, sequence):
    content = b'\x1a\x45\xdf\xa3' + bytes([sequence]) * 50
    lecture.put_chunk('alice', recording, sequence, content, start_ms=sequence * 5000, end_ms=(sequence + 1) * 5000,
                      media_type='audio/webm', checksum=hashlib.sha256(content).hexdigest())


class Provider:
    submissions = 0
    def __init__(self, **kwargs):
        pass
    def upload(self, content):
        return 'https://cdn.assemblyai.com/upload/audio'
    def submit(self, *args, **kwargs):
        Provider.submissions += 1
        return 'provider-request'
    def get(self, *args):
        return AssemblyTranscript('provider-request', 'completed', 'A cell.', (AssemblyWord('A', 100, 200, None, 'A'), AssemblyWord('cell.', 200, 800, .8, 'A')), 'universal-3-5-pro', .9)
    def delete(self, *args):
        pass
    def verify_request_source(self,identifier,url):
        assert identifier=='provider-request' and url=='https://cdn.assemblyai.com/upload/audio'
        return identifier


def service(store, provider=Provider):
    return ClassVerificationService(store, provider, lambda chunks, read: b'validated-wav')


def test_window_buffers_until_context_and_flushes_on_stop(setup):
    store, lecture, recording, _class = setup
    upload(lecture, recording, 0)
    assert service(store).plan('alice', recording)['buffering']
    lecture.finalize('alice', recording, LectureFinalize(expectedChunkCount=1, durationMs=5000))
    assert service(store).plan('alice', recording)['scheduled']


def test_request_survives_service_restart_and_publishes_timed_evidence(setup):
    store, lecture, recording, _class = setup
    for sequence in range(6):
        upload(lecture, recording, sequence)
    Provider.submissions = 0
    identifier = service(store).plan('alice', recording)['requestId']
    assert service(store).step('alice', identifier)['state'] == 'uploaded'
    assert service(store).step('alice', identifier)['state'] == 'submitted'
    assert service(store).step('alice', identifier)['state'] == 'cleanup'
    assert service(store).step('alice', identifier)['state'] == 'deleted'
    assert Provider.submissions == 1
    with store.engine.connect() as conn:
        segment = conn.execute(text('SELECT id,start_ms,normalized_text,speaker,confidence FROM lecture_transcript_segments WHERE recording_id=:id'), {'id': recording}).mappings().one()
        assert segment['start_ms'] == 100 and segment['normalized_text'] == 'A cell.'
        assert segment['speaker'] == 'unknown'  # Provider label A is not professor.
        manifest = json.loads(conn.execute(text('SELECT payload FROM class_evidence_words WHERE segment_id=:id'), {'id': segment['id']}).scalar_one())
        assert manifest['words'][0]['confidence'] is None
        assert manifest['words'][0]['speakerId'] == 'A'
        assert conn.execute(text("SELECT COUNT(*) FROM lecture_audio_chunks WHERE transcription_status='completed' AND recording_id=:id"), {'id': recording}).scalar_one() == 6


def test_crash_during_submission_cannot_dispatch_a_second_paid_request(setup):
    store, lecture, recording, class_id = setup
    for sequence in range(6):
        upload(lecture, recording, sequence)
    verifier = service(store)
    identifier = verifier.plan('alice', recording)['requestId']
    verifier.step('alice', identifier)
    verifier.transition(verifier.read('alice', identifier), 'submitting', schedule=False)
    Provider.submissions = 0
    assert service(store).step('alice', identifier)['state'] == 'submission_unknown'
    assert Provider.submissions == 0
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        verifier.retry('alice', class_id, identifier, verifier.read('alice', identifier)['revision'])
    assert error.value.detail['code'] == 'provider_submission_unknown'


def test_window_integrity_and_gap_alignment():
    content = b'bytes'
    chunks = [{'start_ms': 0, 'end_ms': 1000, 'sha256': hashlib.sha256(content).hexdigest()},
              {'start_ms': 1500, 'end_ms': 2500, 'sha256': hashlib.sha256(content).hexdigest()}]
    wav = assemble_window(chunks, lambda chunk: content, lambda content, duration: b'\1\0' * (duration * 16))
    with wave.open(io.BytesIO(wav), 'rb') as reader:
        assert reader.getnframes() == 40000 and reader.getframerate() == 16000
        reader.setpos(16000)
        assert reader.readframes(8000) == b'\0' * 16000
    with pytest.raises(TranscriptionFailure):
        assemble_window(chunks, lambda chunk: b'corrupted', lambda content, duration: b'')


def test_receipt_reconciliation_resumes_without_second_submission(setup):
    store,lecture,recording,class_id=setup
    for sequence in range(6):upload(lecture,recording,sequence)
    verifier=service(store);identifier=verifier.plan('alice',recording)['requestId']
    verifier.step('alice',identifier)
    verifier.transition(verifier.read('alice',identifier),'submission_unknown',schedule=False)
    row=verifier.read('alice',identifier);Provider.submissions=0
    verifier.associate_receipt('alice',class_id,identifier,row['revision'],'provider-request')
    assert verifier.step('alice',identifier)['state']=='cleanup' and Provider.submissions==0


def test_economical_mode_buffers_longer_windows(setup):
    from backend.app.in_class_service import InClassService
    store,lecture,recording,class_id=setup
    with store.transaction() as conn:
        classes=InClassService(store);item=classes.row(conn,'alice',class_id,True)
        item['policy']['speechQuality']='economical';classes.save(conn,item)
    for sequence in range(6):upload(lecture,recording,sequence)
    assert service(store).plan('alice',recording)['buffering']
    for sequence in range(6,18):upload(lecture,recording,sequence)
    result=service(store).plan('alice',recording)
    assert service(store).read('alice',result['requestId'])['payload']['endMs']==90000
