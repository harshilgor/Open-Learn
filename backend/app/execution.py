"""Shared transaction fencing and durable follow-up delivery.

Handlers execute within a short transaction and must never call providers.
External work is represented by another durable job in that transaction.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import time
import threading
from uuid import uuid4

from sqlalchemy import text

active_job = ContextVar("active_execution_job", default=None)


def embedded_execution():
    default = "external" if os.getenv("AI_TUTOR_ENV", "development").lower() in {"production", "deployed"} else "embedded"
    return os.getenv("OPENLEARN_WORKER_MODE", default) == "embedded"


def schedule_local(tasks, function, *args):
    """Optional latency shortcut; persistent worker polling is authoritative."""
    if embedded_execution():
        tasks.add_task(function, *args)


class LeaseHeartbeat:
    def __init__(self, store, job):
        self.stop = threading.Event()
        def renew():
            from .workflow_store import WorkflowStore
            while not self.stop.wait(60):
                try:
                    WorkflowStore(store).heartbeat(job)
                except Exception:
                    return  # Transaction fencing rejects any later output.
        self.thread = threading.Thread(target=renew, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()


def failure_policy(exc):
    """Only known transport failures retry; auth and validation need action."""
    import httpx
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError)):
            return "provider_transport", True
        if isinstance(current, httpx.HTTPStatusError):
            code = current.response.status_code
            if code in {408, 429} or code >= 500:
                return "provider_temporarily_unavailable", True
            if code in {401, 403}:
                return "provider_authorization_required", False
        current = current.__cause__ or current.__context__
    return "operation_failed", False


@contextmanager
def job_scope(job):
    token = active_job.set(job)
    try:
        yield
    finally:
        active_job.reset(token)


class Outbox:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def emit(conn, owner, topic, target, key, payload):
        data = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        conn.execute(text("""INSERT INTO execution_outbox(id,owner_id,topic,target_id,dedup_key,payload,created_at)
            VALUES(:id,:owner,:topic,:target,:key,:payload,:now)
            ON CONFLICT(owner_id,dedup_key) DO NOTHING"""),
            {"id": "event_" + uuid4().hex, "owner": owner, "topic": topic, "target": target,
             "key": key, "payload": data, "now": time.time()})
        existing = conn.execute(text("SELECT topic,target_id,payload FROM execution_outbox WHERE owner_id=:owner AND dedup_key=:key"), {"owner": owner, "key": key}).one()
        if tuple(existing) != (topic, target, data):
            raise ValueError("Outbox idempotency key was reused with different input")

    def deliver_one(self, handlers):
        if not handlers:
            return False
        with self.store.transaction() as conn:
            # PostgreSQL locks only the selected event; SQLite serializes the
            # selection and mutation before any handler can observe it.
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            names = {"topic" + str(i): name for i, name in enumerate(handlers)}
            topics = ",".join(":" + key for key in names)
            lock = " FOR UPDATE SKIP LOCKED" if conn.dialect.name == "postgresql" else ""
            row = conn.execute(text(f"SELECT * FROM execution_outbox WHERE delivered_at IS NULL AND topic IN ({topics}) ORDER BY created_at,id LIMIT 1" + lock), names).mappings().first()
            if row is None:
                return False
            handlers[row["topic"]](conn, row, json.loads(row["payload"]))
            conn.execute(text("UPDATE execution_outbox SET delivered_at=:now WHERE id=:id"), {"now": time.time(), "id": row["id"]})
        return True


class ProjectionWatermarks:
    @staticmethod
    def advance(conn, owner, projection, target, revision):
        conn.execute(text("""INSERT INTO projection_watermarks(owner_id,projection,target_id,revision,updated_at)
            VALUES(:owner,:projection,:target,:revision,:now)
            ON CONFLICT(owner_id,projection,target_id) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at
            WHERE projection_watermarks.revision<excluded.revision"""),
            {"owner": owner, "projection": projection, "target": target, "revision": revision, "now": time.time()})

    @staticmethod
    def status(conn, owner, projection, target, required_revision):
        revision = conn.execute(text("SELECT revision FROM projection_watermarks WHERE owner_id=:owner AND projection=:projection AND target_id=:target"),
            {"owner": owner, "projection": projection, "target": target}).scalar_one_or_none()
        return {"status": "ready" if revision is not None and revision >= required_revision else "pending_analysis",
                "revision": revision, "requiredRevision": required_revision}
