import hashlib
import json
import base64
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy import inspect
from alembic import command
from alembic.config import Config

from backend.app.lecture_models import LectureCreate, LectureFinalize
from backend.app.lecture_pipeline import LectureWorker, configured_class_transcription_provider
from backend.app.lecture_provider import OpenAITranscriptionProvider, OpenRouterTranscriptionProvider, TranscribedSpan, TranscriptionFailure, TranscriptionResult, normalize_text
from backend.app.lecture_service import LectureError, LectureService
from backend.app.class_recording_service import ClassRecordingService
from backend.app.storage import Store
from backend.app.database import BACKEND_ROOT, create_database_engine
from backend.app.workspace_note_service import WorkspaceNoteService
from backend.app.workspace_note_models import WorkspaceNoteCreate, WorkspaceNoteUpdate
from backend.app.automatic_note_context import retrieve_relevant_notes
from backend.app.lecture_routes import build_lecture_router
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.usage.context import usage_scope


class FakeTranscriber:
    def transcribe_chunk(self, content, mime_type, duration_ms, previous_tail=""):
        return TranscriptionResult("fake", "lecture-test", [TranscribedSpan(0, duration_ms, "A cell has a membrane and a nucleus.")])


class FakeTextProvider:
    def complete_json(self, prompt, max_tokens):
        data = json.loads(prompt[prompt.index("\n") + 1:])
        if prompt.startswith("Group the following"):
            return {"sections": [{"title": "Cell structure", "sectionType": "new_concept", "summary": "Cell parts", "segmentIds": [item["id"] for item in data], "confidence": 0.9}]}
        if prompt.startswith("Extract concrete"):
            return {"entities": [{"kind": "concept", "title": "Cell parts", "content": "A cell has a membrane and a nucleus.", "segmentIds": [data["transcript"][0]["id"]], "sourceKind": "unknown", "confidence": 0.9}]}
        if prompt.startswith("Independently check"):
            return {"results": [{"index": item["index"], "status": "supported", "reason": "Stated in the transcript"} for item in data]}
        raise AssertionError(prompt[:70])


def test_class_transcription_uses_configured_openrouter_provider(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.delenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = configured_class_transcription_provider()

    assert isinstance(provider, OpenRouterTranscriptionProvider)
    assert provider.model == "openai/whisper-large-v3"


def test_class_transcription_honors_explicit_provider_override(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    provider = configured_class_transcription_provider()

    assert isinstance(provider, OpenAITranscriptionProvider)


@pytest.fixture
def lecture(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_NOTE_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("AI_TUTOR_RECORDINGS_DIR", str(tmp_path / "recordings"))
    store = Store(tmp_path / "lecture.db")
    service = LectureService(store)
    command = LectureCreate(id="rec_" + "a" * 32, title="Biology", startedAtMs=1000)
    created = service.create("alice", command)
    yield store, service, created
    store.close()


def upload(service, sequence, start=0, end=8000):
    audio = b"\x1a\x45\xdf\xa3" + bytes([sequence % 256]) * 50
    return service.put_chunk("alice", "rec_" + "a" * 32, sequence, audio, start_ms=start, end_ms=end, media_type="audio/webm", checksum=hashlib.sha256(audio).hexdigest())


def test_audio_manifest_and_followup_job_rollback_together(lecture, monkeypatch):
    store, service, created = lecture
    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("simulated database failure before job insert")
    monkeypatch.setattr(service.jobs, "enqueue", fail_enqueue)
    with pytest.raises(RuntimeError):
        upload(service, 0)
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM lecture_audio_chunks WHERE recording_id=:id"), {"id": created["id"]}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM learning_jobs WHERE target_id=:id"), {"id": created["id"]}).scalar_one() == 0
    assert not list(service.objects.root.rglob("chunk_*"))


def test_chunk_idempotency_scope_gaps_and_final_notes(lecture):
    store, service, created = lecture
    rid = created["id"]
    assert service.create("alice", LectureCreate(id=rid, title="Biology", startedAtMs=1000))["noteId"] == created["noteId"]
    with pytest.raises(LectureError) as denied:
        service.status("bob", rid)
    assert denied.value.status_code == 404
    first = upload(service, 0)
    assert first["duplicate"] is False
    assert upload(service, 0)["duplicate"] is True
    with pytest.raises(LectureError) as conflict:
        service.put_chunk("alice", rid, 0, b"\x1a\x45\xdf\xa3other", start_ms=0, end_ms=8000, media_type="audio/webm", checksum=hashlib.sha256(b"\x1a\x45\xdf\xa3other").hexdigest())
    assert conflict.value.code == "chunk_conflict"
    service.finalize("alice", rid, LectureFinalize(expectedChunkCount=2, durationMs=16000))
    assert service.status("alice", rid)["chunks"]["missing"] == [1]
    worker = LectureWorker(store, lambda: FakeTextProvider(), FakeTranscriber())
    worker.drain()
    assert service.status("alice", rid)["recordingStatus"] != "completed"
    upload(service, 1, 8000, 16000)
    worker.drain()
    status = service.status("alice", rid)
    assert status["recordingStatus"] == "completed", status
    assert status["chunks"]["transcribed"] == 2
    assert len(service.transcript("alice", rid)) == 2
    blocks = service.note_blocks("alice", rid)["blocks"]
    assert blocks and blocks[0]["verificationStatus"] == "supported"
    assert blocks[0]["evidence"][0]["startMs"] == 0
    related = retrieve_relevant_notes(store, "alice", "cell membrane", None, set())
    assert related and related[0]["noteId"] == created["noteId"]
    assert "Transcript evidence" in related[0]["text"]
    note = WorkspaceNoteService(store).get("alice", created["noteId"])
    assert note.body == ""


def test_chunk_checksum_and_finalization_are_recoverable(lecture):
    _, service, created = lecture
    rid = created["id"]
    with pytest.raises(LectureError) as bad:
        service.put_chunk("alice", rid, 0, b"\x1a\x45\xdf\xa3audio", start_ms=0, end_ms=8000, media_type="audio/webm", checksum="0" * 64)
    assert bad.value.code == "checksum_mismatch"
    service.finalize("alice", rid, LectureFinalize(expectedChunkCount=1, durationMs=8000, captureInterrupted=True))
    assert service.status("alice", rid)["captureInterrupted"] is True
    assert service.status("alice", rid)["chunks"]["missing"] == [0]
    upload(service, 0)
    assert service.status("alice", rid)["chunks"]["missing"] == []
    with pytest.raises(LectureError) as bad_count:
        service.finalize("alice", rid, LectureFinalize(expectedChunkCount=2, durationMs=16000))
    assert bad_count.value.code == "finalization_conflict"


def test_missing_transcription_key_is_explained_in_recording_status(lecture, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", "openai")
    store, service, created = lecture
    upload(service, 0)
    service.finalize("alice", created["id"], LectureFinalize(expectedChunkCount=1, durationMs=8000))
    LectureWorker(store, lambda: None).drain()
    status = service.status("alice", created["id"])
    assert status["recordingStatus"] == "failed"
    assert status["error"] == "Connect an OpenAI API key to transcribe this lecture."


def test_openrouter_key_retries_saved_lecture_without_openai(monkeypatch, lecture):
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.delenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store, service, created = lecture
    for sequence in range(13):
        upload(service, sequence, sequence * 8000, (sequence + 1) * 8000)
    service.finalize("alice", created["id"], LectureFinalize(expectedChunkCount=13, durationMs=104000))
    worker = LectureWorker(store, lambda: FakeTextProvider())
    worker.drain()
    assert service.status("alice", created["id"])["chunks"]["failed"] == 13

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE", "0.006")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"text": "A cell has a membrane and a nucleus."})

    monkeypatch.setattr(httpx, "post", post)
    service.retry_failed("alice", created["id"])
    worker.drain()
    status = service.status("alice", created["id"])
    assert status["recordingStatus"] == "completed"
    assert status["chunks"]["transcribed"] == 13
    assert calls[0][0] == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-router-key"
    assert calls[0][1]["json"]["model"] == "openai/whisper-large-v3"
    assert base64.b64decode(calls[0][1]["json"]["input_audio"]["data"]).startswith(b"\x1a\x45\xdf\xa3")
    assert service.transcript("alice", created["id"])[0]["provider"] == "openrouter"


def test_openrouter_large_recording_uses_supported_multipart_upload(monkeypatch):
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    monkeypatch.setenv("OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE", "0.006")
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"text": "Recorded lecture."})

    monkeypatch.setattr(httpx, "post", post)
    store_path = Path(__file__).resolve().parents[1] / "data" / f"test_transcription_{uuid4().hex}.db"
    store = Store(store_path)
    try:
        with usage_scope(store, "alice", "recording-test"):
            result = OpenRouterTranscriptionProvider(key="test-router-key").transcribe_chunk(
                b"RIFF" + b"x" * (4 * 1024 * 1024), "audio/wav", 1000)
        with store.engine.connect() as conn:
            event = conn.execute(text("SELECT component,cost_nano,source FROM usage_events WHERE owner_id='alice'")).one()
        assert event.component == "stt"
        assert event.cost_nano == 100_000  # $0.006/min prorated over the 1-second slice.
        assert event.source == "estimated"
    finally:
        store.close()
        store_path.unlink(missing_ok=True)
        Path(str(store_path) + "-wal").unlink(missing_ok=True)
        Path(str(store_path) + "-shm").unlink(missing_ok=True)
    assert captured["data"]["model"] == "openai/whisper-large-v3"
    assert captured["files"]["file"][0] == "recording.wav"
    assert result.spans[0].text == "Recorded lecture."


@pytest.mark.parametrize(
    ("provider", "key_name", "rate_name"),
    [
        ("openai", "OPENAI_API_KEY", "OPENLEARN_OPENAI_STT_USD_PER_MINUTE"),
        ("openrouter", "OPENROUTER_API_KEY", "OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE"),
    ],
)
def test_transcription_requires_rate_before_provider_request(monkeypatch, provider, key_name, rate_name):
    monkeypatch.setenv(key_name, "test-provider-key")
    monkeypatch.delenv(rate_name, raising=False)
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: calls.append(args))
    client = OpenAITranscriptionProvider(key="test-provider-key") if provider == "openai" else OpenRouterTranscriptionProvider(key="test-provider-key")

    with pytest.raises(TranscriptionFailure) as unavailable:
        client.transcribe_chunk(b"audio", "audio/webm", 8000)

    assert unavailable.value.code == "usage_provider_unavailable"
    assert "rate configured" in str(unavailable.value)
    assert calls == []


def test_legacy_class_recording_uses_openrouter_for_transcription(monkeypatch, lecture):
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE", "0.006")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", raising=False)
    store, _, _ = lecture
    notes = WorkspaceNoteService(store)
    note = notes.create("alice", WorkspaceNoteCreate(title="Old class", body="", frontmatter={"class_recording_id": "pending"}))

    def post(url, **kwargs):
        assert url == "https://openrouter.ai/api/v1/audio/transcriptions"
        return httpx.Response(200, request=httpx.Request("POST", url), json={"text": "The lecture covered cells."})

    monkeypatch.setattr(httpx, "post", post)

    class TextProvider:
        def _complete(self, prompt, max_tokens):
            return [SimpleNamespace(heading="Cells", body="Cells were discussed.")]

    service = ClassRecordingService(store, TextProvider())
    recorded = service.upload("alice", note.id, b"\x1a\x45\xdf\xa3audio", "audio/webm", 8000, [])
    with usage_scope(store, "alice", recorded["id"]):
        service.process(recorded["id"], "alice")
    assert service.get("alice", recorded["id"])["status"] == "completed"
    assert "The lecture covered cells." in notes.get("alice", note.id).body


def test_legacy_notes_and_user_body_survive_generation(lecture):
    store, service, created = lecture
    rid = created["id"]
    notes = WorkspaceNoteService(store)
    original = notes.get("alice", created["noteId"])
    notes.update("alice", original.id, WorkspaceNoteUpdate(body="My own biology notes", expectedRevision=original.revision))
    upload(service, 0)
    service.finalize("alice", rid, LectureFinalize(expectedChunkCount=1, durationMs=8000))
    LectureWorker(store, lambda: FakeTextProvider(), FakeTranscriber()).drain()
    assert notes.get("alice", original.id).body == "My own biology notes"
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM workspace_notes WHERE id=:id"), {"id": original.id}).scalar_one() == 1


def test_simulated_hour_with_450_slices(lecture):
    store, service, created = lecture
    rid = created["id"]
    for sequence in range(450):
        upload(service, sequence, sequence * 8000, (sequence + 1) * 8000)
    service.finalize("alice", rid, LectureFinalize(expectedChunkCount=450, durationMs=3_600_000))
    worker = LectureWorker(store, lambda: FakeTextProvider(), FakeTranscriber())
    assert worker.drain() >= 450
    status = service.status("alice", rid)
    assert status["recordingStatus"] == "completed", status
    assert status["chunks"]["transcribed"] == 450
    assert len(service.transcript("alice", rid)) == 450
    assert service.note_blocks("alice", rid)["blocks"]


def test_http_ownership_and_upload_ack(lecture, monkeypatch):
    store, _, created = lecture
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    app = FastAPI()
    app.include_router(build_lecture_router(lambda: store, lambda: FakeTextProvider(), FakeTranscriber()))
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    rid = created["id"]
    audio = b"\x1a\x45\xdf\xa3test"
    headers = {"X-Dev-Learner-Id": "alice", "X-Chunk-Start-Ms": "0", "X-Chunk-End-Ms": "8000", "X-Chunk-Sha256": hashlib.sha256(audio).hexdigest(), "Content-Type": "audio/webm"}
    with TestClient(app) as client:
        assert client.get(f"/v1/learners/alice/lecture-recordings/{rid}", headers={"X-Dev-Learner-Id": "bob"}).status_code == 403
        sent = client.put(f"/v1/learners/alice/lecture-recordings/{rid}/chunks/0", headers=headers, content=audio)
        assert sent.status_code == 200, sent.text
        assert sent.json()["sha256"] == headers["X-Chunk-Sha256"]
        repeated = client.put(f"/v1/learners/alice/lecture-recordings/{rid}/chunks/0", headers=headers, content=audio)
        assert repeated.status_code == 200 and repeated.json()["duplicate"] is True
        finished = client.post(f"/v1/learners/alice/lecture-recordings/{rid}/finalize", headers={"X-Dev-Learner-Id": "alice"}, json={"expectedChunkCount": 1, "durationMs": 8000})
        assert finished.status_code == 200, finished.text
        assert client.get(f"/v1/learners/alice/lecture-recordings/{rid}/notes", headers={"X-Dev-Learner-Id": "alice"}).json()["blocks"]
        assert client.put(f"/v1/learners/alice/lecture-recordings/{rid}/chunks/0", headers=headers, content=audio).json()["duplicate"] is True


def test_recording_delete_removes_owned_audio_and_rows(lecture):
    store, service, created = lecture
    rid = created["id"]
    upload(service, 0)
    with store.engine.connect() as connection:
        storage_key = connection.execute(text("SELECT storage_key FROM lecture_audio_chunks WHERE recording_id=:id"), {"id": rid}).scalar_one()
    path = service.objects.path("alice", rid, storage_key)
    assert path.is_file()
    service.delete("alice", created["noteId"])
    assert not path.exists()
    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM lecture_recordings WHERE id=:id"), {"id": rid}).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM lecture_audio_chunks WHERE recording_id=:id"), {"id": rid}).scalar_one() == 0


def test_migration_downgrade_keeps_legacy_recordings(tmp_path):
    database = tmp_path / "migration.db"
    store = Store(database)
    store.close()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}".replace("%", "%%"))
    command.downgrade(config, "0025_class_recordings")
    engine = create_database_engine(f"sqlite+pysqlite:///{database}")
    try:
        tables = set(inspect(engine).get_table_names())
        assert "class_recordings" in tables
        assert "lecture_recordings" not in tables
    finally:
        engine.dispose()
    command.upgrade(config, "head")


def test_migration_repairs_recording_column_missing_from_older_0026(tmp_path):
    database = tmp_path / "lecture-schema-drift.db"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}".replace("%", "%%"))
    command.upgrade(config, "0026_lecture_pipeline")
    engine = create_database_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE lecture_recordings DROP COLUMN capture_interrupted"))
        assert "capture_interrupted" not in {column["name"] for column in inspect(engine).get_columns("lecture_recordings")}
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    repaired = create_database_engine(f"sqlite+pysqlite:///{database}")
    try:
        assert "capture_interrupted" in {column["name"] for column in inspect(repaired).get_columns("lecture_recordings")}
    finally:
        repaired.dispose()


def test_unsupported_claim_is_not_rendered(lecture):
    store, service, created = lecture
    class UnsupportedProvider(FakeTextProvider):
        def complete_json(self, prompt, max_tokens):
            response = super().complete_json(prompt, max_tokens)
            if prompt.startswith("Independently check"):
                for item in response["results"]:
                    item["status"] = "unsupported"
            return response
    upload(service, 0)
    service.finalize("alice", created["id"], LectureFinalize(expectedChunkCount=1, durationMs=8000))
    LectureWorker(store, lambda: UnsupportedProvider(), FakeTranscriber()).drain()
    assert service.status("alice", created["id"])["recordingStatus"] == "completed"
    assert service.note_blocks("alice", created["id"])["blocks"] == []


def test_out_of_order_arrival_and_transcription_retry(lecture):
    store, service, created = lecture
    rid = created["id"]
    service.finalize("alice", rid, LectureFinalize(expectedChunkCount=2, durationMs=16000))
    upload(service, 1, 8000, 16000)
    assert service.status("alice", rid)["chunks"]["missing"] == [0]
    upload(service, 0)

    class FailOnce(FakeTranscriber):
        failed = False
        def transcribe_chunk(self, content, mime_type, duration_ms, previous_tail=""):
            if not self.failed:
                self.failed = True
                raise RuntimeError("temporary upstream error")
            return super().transcribe_chunk(content, mime_type, duration_ms, previous_tail)

    transcriber = FailOnce()
    worker = LectureWorker(store, lambda: FakeTextProvider(), transcriber)
    worker.drain()
    assert service.status("alice", rid)["chunks"]["failed"] == 1
    service.retry_failed("alice", rid)
    worker.drain()
    assert service.status("alice", rid)["recordingStatus"] == "completed"


def test_boundary_normalization_preserves_new_speech():
    raw = "characteristic equation gives lambda equals three"
    assert normalize_text(raw, "substituting into the characteristic equation gives") == "lambda equals three"
    assert normalize_text("equation gives lambda equals three", "characteristic") == "equation gives lambda equals three"
