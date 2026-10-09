import base64
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.backup_routes import build_backup_router
from backend.app.evaluation_runner import run
from backend.app.storage import Store

def test_evaluation_runner_is_machine_readable():
    result=run()
    assert result["passed"] and result["suite"] == "openlearn-deterministic-evaluation"
    assert result["categories"] == {
        "existing_regression": {"passed": 6, "total": 6},
        "policy": {"passed": 8, "total": 8},
        "state_admission": {"passed": 3, "total": 3},
    }
    assert all(outcome["source"] == "labeled_synthetic" for outcome in result["outcomes"]
               if outcome["category"] in {"policy", "state_admission"})

def test_backup_round_trip_corruption_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV","test"); monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY","true")
    monkeypatch.setenv("FORMA_DB_PATH",str(tmp_path / "data" / "forma.db")); monkeypatch.setenv("AI_TUTOR_NOTE_VAULT_DIR",str(tmp_path / "data" / "notes")); monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR",str(tmp_path / "data" / "materials")); monkeypatch.setenv("FORMA_API_TOKEN", "secret-token-must-not-back-up")
    store=Store(tmp_path / "data" / "forma.db")
    try:
        with store.transaction() as c: c.exec_driver_sql("INSERT INTO topic_scopes(id,payload) VALUES('scope-backup','{}')")
        note=tmp_path / "data" / "notes" / "local" / "note_test1234.md"; note.parent.mkdir(parents=True); note.write_text("private learner note",encoding="utf-8")
        app=FastAPI(); app.include_router(build_backup_router(lambda:store))
        with TestClient(app) as client:
            archive=client.get("/v1/local-backup").json()["archiveBase64"]; raw=base64.b64decode(archive)
            assert b"secret-token-must-not-back-up" not in raw
            assert client.post("/v1/local-backup/preflight",json={"archiveBase64":archive}).status_code == 200
            assert client.post("/v1/local-backup/restore",json={"archiveBase64":archive}).status_code == 409
            assert client.post("/v1/local-backup/restore",json={"archiveBase64":archive,"confirmReplace":True}).status_code == 200
            assert client.post("/v1/local-backup/preflight",json={"archiveBase64":"broken"}).status_code == 422
        assert note.read_text(encoding="utf-8") == "private learner note"
    finally: store.close()


def test_identity_backup_restore_requires_independent_revocation_reconciliation(tmp_path, monkeypatch):
    from sqlalchemy import text
    from backend.app.backup_service import BackupError, BackupService
    from backend.app.identity_revocation import InMemoryRevocationJournal, device_revocation_record
    monkeypatch.setenv("AI_TUTOR_ENV", "test")
    monkeypatch.setenv("FORMA_DB_PATH", str(tmp_path / "data" / "forma.db"))
    monkeypatch.setenv("AI_TUTOR_NOTE_VAULT_DIR", str(tmp_path / "data" / "notes"))
    monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR", str(tmp_path / "data" / "materials"))
    monkeypatch.setenv("AI_TUTOR_RECORDINGS_DIR", str(tmp_path / "data" / "recordings"))
    store = Store(tmp_path / "data" / "forma.db")
    try:
        with store.transaction() as conn:
            conn.execute(text("INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at) VALUES('alice','subject','Alice','active',1)"))
            conn.execute(text("INSERT INTO identity_devices(id,owner_id,name,kind,token_hash,created_at,expires_at,sequence) VALUES('device_one','alice','Test','desktop','hash',1,9999999999,0)"))
        archive = BackupService(store).create()
        with pytest.raises(BackupError) as disabled:
            BackupService(store, identity_restore_enabled=False).restore(archive, confirm_replace=True)
        assert disabled.value.code == "identity_restore_disabled"

        journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z", (device_revocation_record("alice", "device_one", 1791504000),))
        restored = BackupService(store, revocation_journal=journal, identity_restore_enabled=True).restore(archive, confirm_replace=True)
        assert restored["restored"] > 0
        with store.engine.connect() as conn:
            revoked_at = conn.execute(text("SELECT revoked_at FROM identity_devices WHERE id='device_one'")).scalar_one()
        assert revoked_at == 1791504000
    finally:
        store.close()
