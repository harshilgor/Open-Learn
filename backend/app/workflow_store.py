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

    def enqueue(self, owner, target, kind, payload, key, *, connection=None, input_revision=None, queue=None, max_attempts=3):
        if queue not in {None, "interactive", "batch"} or not 1 <= max_attempts <= 10:
            raise ValueError("Invalid execution policy")
        queue = queue or ("batch" if kind.startswith("lecture_") else "interactive")
        request_hash = hashlib.sha256(encoded([target, kind, payload, input_revision]).encode()).hexdigest()
        values = {"id": uid("job"), "owner": owner, "target": target, "kind": kind, "key": key,
                  "hash": request_hash, "payload": encoded(payload), "revision": input_revision,
                  "queue": queue, "max_attempts": max_attempts}
        def write(conn):
            # ON CONFLICT preserves the surrounding command transaction on both
            # PostgreSQL and SQLite; an IntegrityError would abort PostgreSQL.
            conn.execute(text("""INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,payload,input_revision,queue,max_attempts)
                VALUES(:id,:owner,:target,:kind,:key,:hash,'queued',:payload,:revision,:queue,:max_attempts)
                ON CONFLICT(owner_id,command_key) DO NOTHING"""), values)
            row = conn.execute(text("SELECT id,request_hash FROM learning_jobs WHERE owner_id=:owner AND command_key=:key"), values).one()
            # Legacy request hashes did not include input_revision. Match only
            # when the new caller also supplies no revision.
            legacy_hash = hashlib.sha256(encoded([target, kind, payload]).encode()).hexdigest()
            if row[1] != request_hash and not (input_revision is None and row[1] == legacy_hash):
                problem("idempotency_conflict", "This request key was already used for another action.", 409)
            values["id"] = row[0]
            return self.job(owner, values["id"], connection=conn)
        if connection is not None:
            return write(connection)
        with self.store.transaction() as conn:
            result = write(conn)
        return result

    def job(self, owner, job_id, connection=None):
        if connection is None:
            with self.store.engine.connect() as conn:
                return self.job(owner, job_id, conn)
        row = connection.execute(text("SELECT id,status,result,attempt_count,next_retry_at,progress,cancel_requested,safe_error_code FROM learning_jobs WHERE id=:id AND owner_id=:owner"), {"id": job_id, "owner": owner}).mappings().first()
        if not row:
            problem("not_found", "This operation is not available.", 404)
        return {**row, "result": json.loads(row["result"]) if row["result"] else None}

    def claim(self, job_id, *, lease_seconds=900):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        lease = uid("lease")
        with self.store.transaction() as conn:
            now = time.time()
            # Expired final attempts become visible failures, not stuck jobs.
            conn.execute(text("""UPDATE learning_jobs SET status='failed',safe_error_code='attempts_exhausted',lease=NULL,expires=NULL
                WHERE id=:id AND status='running' AND expires<=:now AND attempt_count>=max_attempts"""), {"id": job_id, "now": now})
            changed = conn.execute(text("""UPDATE learning_jobs SET status='running',lease=:lease,expires=:expires,attempt_count=attempt_count+1,safe_error_code=NULL
                WHERE id=:id AND cancel_requested=false AND attempt_count<max_attempts AND next_retry_at<=:now
                AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now))"""),
                                   {"id": job_id, "lease": lease, "expires": now + lease_seconds, "now": now})
            if changed.rowcount != 1:
                return None
            row = conn.execute(text("SELECT * FROM learning_jobs WHERE id=:id"), {"id": job_id}).mappings().one()
            return {**row, "payload": json.loads(row["payload"])}

    def finish(self, conn, job, result, status="completed"):
        if status not in {"completed", "failed"}:
            raise ValueError("Invalid terminal state")
        changed = conn.execute(text("""UPDATE learning_jobs SET status=:status,result=:result,lease=NULL,expires=NULL,progress=:progress
            WHERE id=:id AND owner_id=:owner AND lease=:lease AND status='running' AND expires>:now AND cancel_requested=false
            AND (input_revision=:revision OR (input_revision IS NULL AND :revision IS NULL))"""),
                               {"id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "status": status, "result": encoded(result),
                                "revision": job["input_revision"], "now": time.time(), "progress": 100 if status == "completed" else job["progress"]})
        if changed.rowcount != 1:
            problem("lease_lost", "This operation was resumed elsewhere.", 409)

    def cancel(self, owner, job_id):
        self.job(owner, job_id)
        with self.store.transaction() as conn:
            conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancel_requested=true,lease=NULL,expires=NULL WHERE id=:id AND owner_id=:owner AND status IN ('queued','running','retry_wait')"), {"id": job_id, "owner": owner})
        return self.job(owner, job_id)

    def heartbeat(self, job, progress, *, lease_seconds=900):
        if not 0 <= progress <= 99 or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease update")
        now = time.time()
        with self.store.transaction() as conn:
            changed = conn.execute(text("""UPDATE learning_jobs SET expires=:expires,progress=:progress
                WHERE id=:id AND owner_id=:owner AND lease=:lease AND status='running' AND expires>:now AND cancel_requested=false"""),
                {"id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "expires": now + lease_seconds, "now": now, "progress": progress})
            return changed.rowcount == 1

    def fail(self, job, code, *, transient=False):
        if code not in {"provider_unavailable", "needs_authentication", "unsupported_file", "permission_denied", "invalid_input", "worker_failed"}:
            raise ValueError("Unsafe error code")
        retry = transient and code in {"provider_unavailable", "worker_failed"} and job["attempt_count"] < job["max_attempts"]
        now = time.time()
        with self.store.transaction() as conn:
            changed = conn.execute(text("""UPDATE learning_jobs SET status=:status,safe_error_code=:code,next_retry_at=:retry_at,lease=NULL,expires=NULL
                WHERE id=:id AND owner_id=:owner AND lease=:lease AND status='running' AND expires>:now AND cancel_requested=false"""),
                {"id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "now": now, "code": code,
                 "status": "retry_wait" if retry else "failed", "retry_at": now + min(300, 2 ** job["attempt_count"]) * random.uniform(.8, 1.2) if retry else 0})
            return changed.rowcount == 1

    def ready_ids(self, queue, kinds, limit=20):
        if queue not in {"interactive", "batch"} or not 1 <= limit <= 100 or not kinds:
            raise ValueError("Invalid ready-job scope")
        from sqlalchemy import bindparam
        query = text("""SELECT id FROM learning_jobs WHERE queue=:queue AND kind IN :kinds AND cancel_requested=false
            AND next_retry_at<=:now AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now)) ORDER BY id LIMIT :limit""").bindparams(bindparam("kinds", expanding=True))
        with self.store.engine.connect() as conn:
            return list(conn.execute(query, {"queue": queue, "kinds": list(kinds), "now": time.time(), "limit": limit}).scalars())
