import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from alembic.config import Config
from alembic import command

from backend.app.database import BACKEND_ROOT
from backend.app.storage import Store
from backend.app.workflow_store import WorkflowStore
from backend.app.execution_outbox import ExecutionOutbox
from backend.app.execution_worker import ExecutionWorker


@pytest.fixture
def execution(tmp_path):
    store = Store(tmp_path / "execution.db")
    yield store, WorkflowStore(store)
    store.close()


def enqueue(records, key="one", **kwargs):
    return records.enqueue("alice", "target", "create", {"test": True}, key, **kwargs)


def expire(store, job):
    with store.transaction() as conn:
        conn.execute(text("UPDATE learning_jobs SET expires=:now WHERE id=:id"), {"now": time.time() - 1, "id": job["id"]})


def test_duplicate_command_conflict_and_owner_scope(execution):
    store, records = execution
    first = enqueue(records)
    assert enqueue(records)["id"] == first["id"]
    with pytest.raises(HTTPException) as conflict:
        records.enqueue("alice", "other", "create", {}, "one")
    assert conflict.value.detail["code"] == "idempotency_conflict"
    with pytest.raises(HTTPException) as denied:
        records.job("bob", first["id"])
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException):
        records.cancel("bob", first["id"])
    assert records.job("alice", first["id"])["status"] == "queued"


def test_expired_worker_cannot_commit_and_rolls_back_activity(execution):
    store, records = execution
    job = records.claim(enqueue(records)["id"])
    expire(store, job)
    with pytest.raises(HTTPException) as lost:
        with store.transaction() as conn:
            records.put(conn, "alice", "attempt", {"id": "attempt-old", "answer": "saved"})
            records.finish(conn, job, {"attemptId": "attempt-old"})
    assert lost.value.detail["code"] == "lease_lost"
    with pytest.raises(HTTPException):
        records.read("alice", "attempt-old")
    replacement = records.claim(job["id"])
    assert replacement["lease"] != job["lease"]
    with store.transaction() as conn:
        records.finish(conn, replacement, {"ok": True})
    assert records.job("alice", job["id"])["status"] == "completed"


def test_cancellation_fence_heartbeat_and_revision(execution):
    store, records = execution
    job = records.claim(enqueue(records, input_revision=7)["id"])
    assert records.heartbeat(job, 40)
    with store.transaction() as conn:
        conn.execute(text("UPDATE learning_jobs SET input_revision=8 WHERE id=:id"), {"id": job["id"]})
    with pytest.raises(HTTPException):
        with store.transaction() as conn:
            records.finish(conn, job, {})
    records.cancel("alice", job["id"])
    assert not records.heartbeat(job, 50)
    assert records.claim(job["id"]) is None


def test_retry_backoff_and_bounded_crash_recovery(execution):
    store, records = execution
    job = records.claim(enqueue(records, max_attempts=2)["id"])
    assert records.fail(job, "provider_unavailable", transient=True)
    public = records.job("alice", job["id"])
    assert public["status"] == "retry_wait" and public["next_retry_at"] > time.time()
    assert records.claim(job["id"]) is None
    with store.transaction() as conn:
        conn.execute(text("UPDATE learning_jobs SET next_retry_at=0 WHERE id=:id"), {"id": job["id"]})
    second = records.claim(job["id"])
    assert second["attempt_count"] == 2
    expire(store, second)
    assert records.claim(job["id"]) is None
    assert records.job("alice", job["id"])["safe_error_code"] == "attempts_exhausted"
    assert records.ready_ids("interactive", {"create"}) == []


def test_auth_failure_is_not_retryable(execution):
    store, records = execution
    job = records.claim(enqueue(records)["id"])
    records.fail(job, "needs_authentication", transient=True)
    assert records.job("alice", job["id"])["status"] == "failed"


def test_concurrent_sqlite_claim_has_one_winner(execution):
    store, records = execution
    job_id = enqueue(records)["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: records.claim(job_id), range(4)))
    assert sum(result is not None for result in results) == 1


def test_enqueue_and_outbox_are_atomic_with_command(execution):
    store, records = execution
    outbox = ExecutionOutbox(store)
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            enqueue(records, connection=conn)
            outbox.append(conn, "alice", "derived", "one", {"event": "e1"})
            raise RuntimeError("simulated crash")
    assert records.ready_ids("interactive", {"create"}) == []
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM execution_outbox")).scalar_one() == 0


def test_outbox_recovery_and_idempotent_consumer(execution):
    store, records = execution
    outbox = ExecutionOutbox(store)
    with store.transaction() as conn:
        message_id = outbox.append(conn, "alice", "derived", "one", {"event": "e1"})
        assert outbox.append(conn, "alice", "derived", "one", {"event": "e1"}) == message_id
    def fail(conn, owner, message_id, payload):
        records.put(conn, owner, "derived", {"id": "derived1"})
        raise RuntimeError("crash after effect before acknowledgment")
    with pytest.raises(RuntimeError):
        outbox.drain({"derived": fail})
    def succeed(conn, owner, message_id, payload):
        records.put(conn, owner, "derived", {"id": "derived1"})
    assert outbox.drain({"derived": succeed}) == 1
    assert outbox.drain({"derived": succeed}) == 0
    assert records.read("alice", "derived1")["revision"] == 1


def test_watermark_does_not_regress_and_requires_policy(execution):
    store, _ = execution
    outbox = ExecutionOutbox(store)
    with store.transaction() as conn:
        outbox.advance(conn, "alice", "state", 12, "policy1")
        outbox.advance(conn, "alice", "state", 10, "policy1")
    assert outbox.require("alice", "state", 12, "policy1") == 12
    for owner, seq, rev in [("bob", 1, "policy1"), ("alice", 13, "policy1"), ("alice", 12, "policy2")]:
        with pytest.raises(HTTPException) as pending:
            outbox.require(owner, "state", seq, rev)
        assert pending.value.detail["code"] == "analysis_pending"


def test_outbox_worker_dispatch_durable_after_restart(execution, monkeypatch):
    store, records = execution
    with store.transaction() as conn:
        ExecutionOutbox(store).append(conn, "alice", "execution.enqueue", "one", {"target": "target", "kind": "create", "input": {"test": True}})
    seen = []
    def executor(db, provider, job_id):
        job = WorkflowStore(db).claim(job_id)
        seen.append(job["owner_id"])
        with db.transaction() as conn:
            WorkflowStore(db).finish(conn, job, {"done": True})
    monkeypatch.setattr("backend.app.learning_routes.run_job", executor)
    assert ExecutionWorker(store, lambda: None).tick() == 1
    assert seen == ["alice"]
    assert ExecutionWorker(store, lambda: None).tick() == 0


def test_additive_migration_preserves_legacy_job_and_downgrades(tmp_path):
    from backend.app.database import create_database_engine
    url = f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0027_lecture_capture_interrupted_repair")
    engine = create_database_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,payload) VALUES('job-old','alice','quiz-old','answer','legacy','hash','completed','{}')"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT status,attempt_count FROM learning_jobs WHERE id='job-old'")).one()
        assert tuple(row) == ("completed", 0)
    command.downgrade(config, "0027_lecture_capture_interrupted_repair")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM learning_jobs WHERE id='job-old'")).scalar_one() == "completed"
    engine.dispose()
