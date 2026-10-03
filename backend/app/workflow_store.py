"""Owned versioned artifacts and durable commands for interactive learning."""
import hashlib
import json
import time
import random
from uuid import uuid4

from sqlalchemy import text
from .material_service import problem


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class WorkflowStore:
    def __init__(self, store):
        self.store = store

    def read(self, owner, record_id, kind=None, connection=None):
        if connection is None:
            with self.store.engine.connect() as conn:
                return self.read(owner, record_id, kind, conn)
        row = connection.execute(text("SELECT * FROM practice_records WHERE id=:id AND owner_id=:owner"),
                                 {"id": record_id, "owner": owner}).mappings().first()
        if row is None or (kind and row["kind"] != kind):
            problem("not_found", "This learning activity is not available.", 404)
        return {**json.loads(row["payload"]), "id": row["id"], "revision": row["revision"]}

    def put(self, conn, owner, kind, data, parent=None, expected=None):
        values = {"id": data["id"], "owner": owner, "kind": kind, "parent": parent, "payload": encoded(data)}
        if expected is None:
            conn.execute(text("INSERT INTO practice_records(id,owner_id,kind,parent_id,revision,payload) VALUES(:id,:owner,:kind,:parent,1,:payload)"), values)
        else:
            result = conn.execute(text("UPDATE practice_records SET payload=:payload, revision=revision+1 WHERE id=:id AND owner_id=:owner AND revision=:expected"), {**values, "expected": expected})
            if result.rowcount != 1:
                problem("revision_conflict", "This activity changed. Reload it before continuing.", 409)

    def listing(self, owner, kind):
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT id FROM practice_records WHERE owner_id=:owner AND kind=:kind ORDER BY id"), {"owner": owner, "kind": kind}).all()
            return [self.read(owner, row[0], kind, conn) for row in rows]

    def enqueue(self, owner, target, kind, payload, key, connection=None):
        if connection is not None:
            return self._enqueue(connection, owner, target, kind, payload, key)
        with self.store.transaction() as conn:
            return self._enqueue(conn, owner, target, kind, payload, key)

    def _enqueue(self, conn, owner, target, kind, payload, key):
        request_hash = hashlib.sha256(encoded([target, kind, payload]).encode()).hexdigest()
        values = {"id": uid("job"), "owner": owner, "target": target, "kind": kind, "key": key,
                  "hash": request_hash, "payload": encoded(payload)}
        values["revision"] = payload.get("expected_revision")
        inserted = conn.execute(text("INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,payload,input_revision) VALUES(:id,:owner,:target,:kind,:key,:hash,'queued',:payload,:revision) ON CONFLICT(owner_id,command_key) DO NOTHING"), values)
        if inserted.rowcount != 1:
            row = conn.execute(text("SELECT id,request_hash FROM learning_jobs WHERE owner_id=:owner AND command_key=:key"), values).first()
            if not row or row[1] != request_hash:
                problem("idempotency_conflict", "This request key was already used for another action.", 409)
            values["id"] = row[0]
        row = conn.execute(text("SELECT id,status,result FROM learning_jobs WHERE id=:id"), values).mappings().one()
        return {"id": row["id"], "status": row["status"], "result": json.loads(row["result"]) if row["result"] else None}

    def job(self, owner, job_id):
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT id,status,result,attempt_count,next_retry_at,progress,error_code FROM learning_jobs WHERE id=:id AND owner_id=:owner"), {"id": job_id, "owner": owner}).mappings().first()
        if not row:
            problem("not_found", "This operation is not available.", 404)
        return {**row, "result": json.loads(row["result"]) if row["result"] else None}

    def claim(self, job_id):
        lease = uid("lease")
        with self.store.transaction() as conn:
            conn.execute(text("""UPDATE learning_jobs SET status='failed',error_code='attempts_exhausted',lease=NULL,expires=NULL
                WHERE id=:id AND attempt_count>=max_attempts AND (status='queued' OR (status='running' AND expires<:now))"""), {"id": job_id, "now": time.time()})
            changed = conn.execute(text("UPDATE learning_jobs SET status='running',lease=:lease,expires=:expires,attempt_count=attempt_count+1 WHERE id=:id AND cancellation_requested=false AND next_retry_at<=:now AND (status='queued' OR (status='running' AND expires<:now))"),
                                   {"id": job_id, "lease": lease, "expires": time.time() + 900, "now": time.time()})
            if changed.rowcount != 1:
                return None
            row = conn.execute(text("SELECT * FROM learning_jobs WHERE id=:id"), {"id": job_id}).mappings().one()
            return {**row, "payload": json.loads(row["payload"])}

    def finish(self, conn, job, result, status="completed"):
        changed = conn.execute(text("UPDATE learning_jobs SET status=:status,result=:result,lease=NULL,expires=NULL,progress=1 WHERE id=:id AND lease=:lease AND status='running' AND expires>:now AND cancellation_requested=false"),
                               {"id": job["id"], "lease": job["lease"], "status": status, "result": encoded(result), "now": time.time()})
        if changed.rowcount != 1:
            problem("lease_lost", "This operation was resumed elsewhere.", 409)

    def cancel(self, owner, job_id):
        self.job(owner, job_id)
        with self.store.transaction() as conn:
            conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,lease=NULL,expires=NULL WHERE id=:id AND owner_id=:owner AND status IN ('queued','running')"), {"id": job_id, "owner": owner})
        return self.job(owner, job_id)

    def fail(self, job, error_code, *, retryable=False):
        retry = retryable and job["attempt_count"] < job["max_attempts"]
        delay = min(300, 2 ** min(job["attempt_count"], 8)) * random.uniform(.75, 1.25)
        with self.store.transaction() as conn:
            conn.execute(text("""UPDATE learning_jobs SET status=:status,error_code=:error,
                result=:result,next_retry_at=:retry,lease=NULL,expires=NULL
                WHERE id=:id AND lease=:lease AND status='running' AND expires>:now"""),
                {"status": "queued" if retry else "failed", "error": error_code,
                 "result": encoded({"message": "Temporary failure; retry scheduled." if retry else "This operation needs attention before retrying.", "code": error_code}),
                 "retry": time.time() + delay if retry else 0, "id": job["id"], "lease": job["lease"], "now": time.time()})

    def validate_lease(self, conn, job):
        changed = conn.execute(text("""UPDATE learning_jobs SET progress=progress WHERE id=:id AND owner_id=:owner
            AND lease=:lease AND status='running' AND expires>:now AND cancellation_requested=false"""),
            {"id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "now": time.time()})
        if changed.rowcount != 1:
            problem("lease_lost", "This operation was resumed elsewhere.", 409)

    def heartbeat(self, job, progress=0):
        with self.store.transaction() as conn:
            self.validate_lease(conn, job)
            conn.execute(text("UPDATE learning_jobs SET expires=:expires,progress=:progress WHERE id=:id"),
                         {"id": job["id"], "expires": time.time() + 900, "progress": max(0, min(1, progress))})

    def validate_input(self, conn, job):
        if job["input_revision"] is None:
            return
        revision = conn.execute(text("SELECT revision FROM practice_records WHERE id=:id AND owner_id=:owner"),
                                {"id": job["target_id"], "owner": job["owner_id"]}).scalar_one_or_none()
        if revision is not None and revision != job["input_revision"]:
            problem("revision_conflict", "The source changed while this operation was running. Reload and retry.", 409)
