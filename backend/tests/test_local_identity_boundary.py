import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.local_identity import authorize_local
from backend.app.privacy_routes import build_privacy_router
from backend.app.storage import Store
from backend.app.identity_middleware import IdentityMiddleware


@pytest.mark.parametrize("environment", ["production", "deployed", "unknown"])
def test_development_header_does_not_authorize_hosted_profile(monkeypatch, environment):
    monkeypatch.setenv("AI_TUTOR_ENV", environment)
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    with pytest.raises(HTTPException) as denied:
        authorize_local("alice", "alice")
    assert denied.value.status_code == 503


def test_local_profiles_require_matching_header(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV", "local")
    authorize_local("alice", "alice")
    with pytest.raises(HTTPException):
        authorize_local("bob", "alice")


def test_legacy_device_export_and_delete_are_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV", "local")
    store = Store(tmp_path / "privacy.db")
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,payload) VALUES('job-bob','bob','quiz-bob','answer','key','hash','completed','{}')"))
    app = FastAPI()
    app.include_router(build_privacy_router(lambda: store))
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    client = TestClient(app)
    for method, path in [(client.get, "/v1/learners/alice/export"), (client.delete, "/v1/learners/alice/data")]:
        response = method(path, headers={"X-Dev-Learner-Id": "alice"})
        assert response.status_code == 200
        assert "job-bob" not in response.text
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM learning_jobs WHERE id='job-bob'")).scalar_one() == 1
    deleted = client.delete("/v1/learners/alice/data", headers={"X-Dev-Learner-Id": "alice"})
    assert deleted.status_code == 200
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM learning_jobs WHERE id='job-bob'")).scalar_one() == 1
    store.close()


def test_hosted_middleware_blocks_legacy_global_routes(monkeypatch):
    from backend.app.main import app
    monkeypatch.setenv("AI_TUTOR_ENV", "production")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    client = TestClient(app)
    for path in ["/v1/topic-scopes/test", "/v1/learners/alice/state", "/v1/provider-settings", "/v1/learning-jobs/test", "/v1/courses"]:
        response = client.get(path, headers={"X-Dev-Learner-Id": "alice"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "authentication_unconfigured"


def test_single_profile_deletion_keeps_foreign_keys_and_removes_audio(tmp_path, monkeypatch):
    import hashlib
    from backend.app.lecture_service import LectureService
    from backend.app.lecture_models import LectureCreate
    monkeypatch.setenv("AI_TUTOR_ENV", "local")
    monkeypatch.setenv("AI_TUTOR_RECORDINGS_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("AI_TUTOR_NOTE_VAULT_DIR", str(tmp_path / "notes"))
    store = Store(tmp_path / "privacy.db")
    lecture = LectureService(store)
    recording_id = "rec_" + "b" * 32
    lecture.create("local", LectureCreate(id=recording_id, title="Synthetic lecture", startedAtMs=1000))
    content = b"\x1a\x45\xdf\xa3synthetic-audio"
    lecture.put_chunk("local", recording_id, 0, content, start_ms=0, end_ms=1000, media_type="audio/webm", checksum=hashlib.sha256(content).hexdigest())
    app = FastAPI()
    app.include_router(build_privacy_router(lambda: store))
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    client = TestClient(app)
    export = client.get("/v1/learners/local/export")
    assert export.status_code == 200
    assert len(export.json()["tables"]["lecture_audio_chunks"]) == 1
    response = client.delete("/v1/learners/local/data")
    assert response.status_code == 200, response.text
    with store.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.execute(text("SELECT count(*) FROM learning_jobs")).scalar_one() == 0
    from backend.app.identity_data import cleanup_objects
    cleanup_objects(store)
    assert not list(lecture.objects.root.rglob("chunk_*"))
    store.close()
