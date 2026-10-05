"""Owned versioned artifacts and durable commands for interactive learning."""
import hashlib
import json
import time
import random
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from .material_service import problem


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def history_timestamp(value):
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except ValueError:
        return value


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
        indexed_activity = kind in {"quiz", "review_session"}
        indexed_attempt = kind == "attempt"
        indexed_challenge = kind == "challenge"
        values = {"id": data["id"], "owner": owner, "kind": kind, "parent": parent, "payload": encoded(data),
                  "history_updated_at": history_timestamp(data.get("updatedAt") or data.get("createdAt")) if kind == "quiz" else None,
                  "history_created_at": history_timestamp(data.get("createdAt")) if indexed_activity or indexed_attempt else None,
                  "history_session_id": (data.get("sessionId") or data.get("learnSessionId")) if indexed_activity else None,
                  "history_lesson_note_id": data.get("lessonNoteId") if kind == "quiz" else None,
                  "history_status": data.get("status") if indexed_activity or indexed_attempt or indexed_challenge else None,
                  "history_concept_id": data.get("conceptId") if indexed_attempt else None,
                  "history_presentation_id": data.get("presentationId") if indexed_attempt or indexed_challenge else None,
                  "history_is_retry": bool(data.get("retryOf")) if indexed_attempt else None,
                  "history_assisted": bool(data.get("assisted")) if indexed_attempt else None,
                  "history_outcome": data.get("outcome") if indexed_attempt else None}
        if expected is None:
            conn.execute(text("""INSERT INTO practice_records(id,owner_id,kind,parent_id,revision,payload,
                history_updated_at,history_created_at,history_session_id,history_lesson_note_id,history_status,
                history_concept_id,history_presentation_id,history_is_retry,history_assisted,history_outcome)
                VALUES(:id,:owner,:kind,:parent,1,:payload,:history_updated_at,:history_created_at,:history_session_id,
                :history_lesson_note_id,:history_status,:history_concept_id,:history_presentation_id,
                :history_is_retry,:history_assisted,:history_outcome)"""), values)
        else:
            result = conn.execute(text("""UPDATE practice_records SET payload=:payload, revision=revision+1,
                parent_id=COALESCE(parent_id,:parent), history_updated_at=COALESCE(:history_updated_at,history_updated_at),
                history_created_at=COALESCE(history_created_at,:history_created_at),
                history_session_id=COALESCE(:history_session_id,history_session_id),
                history_lesson_note_id=:history_lesson_note_id,history_status=:history_status,
                history_concept_id=COALESCE(:history_concept_id,history_concept_id),
                history_presentation_id=COALESCE(:history_presentation_id,history_presentation_id),
                history_is_retry=COALESCE(:history_is_retry,history_is_retry),
                history_assisted=COALESCE(:history_assisted,history_assisted),
                history_outcome=COALESCE(:history_outcome,history_outcome)
                WHERE id=:id AND owner_id=:owner AND revision=:expected"""), {**values, "expected": expected})
            if result.rowcount != 1:
                problem("revision_conflict", "This activity changed. Reload it before continuing.", 409)

    def listing(self, owner, kind):
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT id FROM practice_records WHERE owner_id=:owner AND kind=:kind ORDER BY id"), {"owner": owner, "kind": kind}).all()
            return [self.read(owner, row[0], kind, conn) for row in rows]

    def listing_by_parent(self, owner, kind, parent_id):
        """Read only the children of one learning artifact."""
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("""SELECT id,revision,payload FROM practice_records
                WHERE owner_id=:owner AND kind=:kind AND parent_id=:parent ORDER BY id"""),
                {"owner": owner, "kind": kind, "parent": parent_id}).all()
            return [{**json.loads(row[2]), "id": row[0], "revision": row[1]} for row in rows]

    def enqueue(self, owner, target, kind, payload, key, connection=None, *, input_revision=None, queue=None, priority=None, max_attempts=5):
        if connection is not None:
            return self._enqueue(connection, owner, target, kind, payload, key, input_revision=input_revision, queue=queue, priority=priority, max_attempts=max_attempts)
        with self.store.transaction() as conn:
            return self._enqueue(conn, owner, target, kind, payload, key, input_revision=input_revision, queue=queue, priority=priority, max_attempts=max_attempts)

    def _enqueue(self, conn, owner, target, kind, payload, key, *, input_revision=None, queue=None, priority=None, max_attempts=5):
        request_hash = hashlib.sha256(encoded([target, kind, payload]).encode()).hexdigest()
        queue_name=queue or ("batch" if kind.startswith("lecture_") else "interactive")
        default_priority = 20 if kind == "lecture_transcribe" else (50 if queue_name == "interactive" else 0)
        values = {"id": uid("job"), "owner": owner, "target": target, "kind": kind, "key": key,
                  "hash": request_hash, "payload": encoded(payload),
                  "revision": input_revision if input_revision is not None else payload.get("expected_revision"),
                  "queue": queue_name,"priority":int(priority if priority is not None else default_priority),
                  "created_at":time.time(),
                  "max_attempts": max(1, min(20, int(max_attempts)))}
        inserted = conn.execute(text("INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,payload,input_revision,queue,priority,created_at,max_attempts) VALUES(:id,:owner,:target,:kind,:key,:hash,'queued',:payload,:revision,:queue,:priority,:created_at,:max_attempts) ON CONFLICT(owner_id,command_key) DO NOTHING"), values)
        if inserted.rowcount != 1:
            row = conn.execute(text("SELECT id,request_hash FROM learning_jobs WHERE owner_id=:owner AND command_key=:key"), values).first()
            if not row or row[1] != request_hash:
                problem("idempotency_conflict", "This request key was already used for another action.", 409)
            values["id"] = row[0]
        row = conn.execute(text("SELECT id,status,result FROM learning_jobs WHERE id=:id"), values).mappings().one()
        return {"id": row["id"], "status": row["status"], "result": json.loads(row["result"]) if row["result"] else None}

    def job(self, owner, job_id, connection=None):
        if connection is not None:
            row = connection.execute(text("SELECT id,owner_id,status,result,attempt_count,next_retry_at,progress,error_code,safe_error_code,queue,input_revision FROM learning_jobs WHERE id=:id AND owner_id=:owner"), {"id": job_id, "owner": owner}).mappings().first()
        else:
            with self.store.engine.connect() as conn:
                return self.job(owner, job_id, conn)
        if not row:
            problem("not_found", "This operation is not available.", 404)
        result = dict(row)
        result["safe_error_code"] = result.get("safe_error_code") or result.get("error_code")
        return {**result, "result": json.loads(row["result"]) if row["result"] else None}

    def claim(self, job_id, *, lease_seconds=900):
        lease = uid("lease")
        with self.store.transaction() as conn:
            conn.execute(text("""UPDATE learning_jobs SET status='failed',error_code='attempts_exhausted',safe_error_code='attempts_exhausted',lease=NULL,expires=NULL
                WHERE id=:id AND attempt_count>=max_attempts AND (status IN ('queued','retry_wait') OR (status='running' AND expires<:now))"""), {"id": job_id, "now": time.time()})
            changed = conn.execute(text("UPDATE learning_jobs SET status='running',lease=:lease,expires=:expires,attempt_count=attempt_count+1 WHERE id=:id AND cancellation_requested=false AND cancel_requested=false AND next_retry_at<=:now AND (status IN ('queued','retry_wait') OR (status='running' AND expires<:now))"),
                                   {"id": job_id, "lease": lease, "expires": time.time() + lease_seconds, "now": time.time()})
            if changed.rowcount != 1:
                return None
            row = conn.execute(text("SELECT * FROM learning_jobs WHERE id=:id"), {"id": job_id}).mappings().one()
            return {**row, "payload": json.loads(row["payload"])}

    def claim_many(self, queue, kinds, limit, *, lease_seconds=900):
        """Claim a bounded batch atomically; PostgreSQL workers skip each other's rows."""
        if queue not in {"interactive", "batch"} or not kinds or not 1 <= limit <= 100:
            raise ValueError("Invalid job claim scope")
        from sqlalchemy import bindparam

        now = time.time()
        claimed = []
        with self.store.transaction() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            conn.execute(text("""UPDATE learning_jobs
                SET status='failed',error_code='attempts_exhausted',safe_error_code='attempts_exhausted',lease=NULL,expires=NULL
                WHERE queue=:queue AND kind IN :kinds AND attempt_count>=max_attempts
                  AND cancellation_requested=false AND cancel_requested=false
                  AND next_retry_at<=:now
                  AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now))""").bindparams(bindparam("kinds", expanding=True)),
                {"queue": queue, "kinds": list(kinds), "now": now})
            sql = """SELECT id FROM learning_jobs
                WHERE queue=:queue AND kind IN :kinds
                  AND cancellation_requested=false AND cancel_requested=false
                  AND next_retry_at<=:now AND attempt_count<max_attempts
                  AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now))
                ORDER BY CASE WHEN kind='lecture_transcribe' THEN 20 ELSE priority END DESC,created_at,id LIMIT :limit"""
            if conn.dialect.name == "postgresql":
                sql += " FOR UPDATE SKIP LOCKED"
            query = text(sql).bindparams(bindparam("kinds", expanding=True))
            candidates = conn.execute(query, {"queue": queue, "kinds": list(kinds), "now": now, "limit": limit}).scalars().all()
            for job_id in candidates:
                lease = uid("lease")
                changed = conn.execute(text("""UPDATE learning_jobs
                    SET status='running',lease=:lease,expires=:expires,attempt_count=attempt_count+1
                    WHERE id=:id AND queue=:queue AND cancellation_requested=false AND cancel_requested=false
                      AND next_retry_at<=:now AND attempt_count<max_attempts
                      AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now))"""),
                    {"id": job_id, "queue": queue, "lease": lease, "expires": now + lease_seconds, "now": now})
                if changed.rowcount != 1:
                    continue
                row = conn.execute(text("SELECT * FROM learning_jobs WHERE id=:id"), {"id": job_id}).mappings().one()
                claimed.append({**row, "payload": json.loads(row["payload"])})
        return claimed

    def finish(self, conn, job, result, status="completed"):
        if status not in {"completed", "failed"}:
            raise ValueError("Invalid terminal state")
        changed = conn.execute(text("UPDATE learning_jobs SET status=:status,result=:result,lease=NULL,expires=NULL,progress=1 WHERE id=:id AND owner_id=:owner AND lease=:lease AND status='running' AND expires>:now AND cancellation_requested=false AND cancel_requested=false AND (input_revision=:revision OR (input_revision IS NULL AND :revision IS NULL))"),
                               {"id": job["id"], "owner": job["owner_id"], "revision": job.get("input_revision"), "lease": job["lease"], "status": status, "result": encoded(result), "now": time.time()})
        if changed.rowcount != 1:
            problem("lease_lost", "This operation was resumed elsewhere.", 409)

    def cancel(self, owner, job_id):
        self.job(owner, job_id)
        with self.store.transaction() as conn:
            conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,cancel_requested=true,lease=NULL,expires=NULL WHERE id=:id AND owner_id=:owner AND status IN ('queued','retry_wait','running')"), {"id": job_id, "owner": owner})
        return self.job(owner, job_id)

    def fail(self, job, error_code, *, retryable=False, transient=None, connection=None):
        if transient is not None:
            retryable = transient
        allowed = {"provider_unavailable", "provider_transport", "provider_temporarily_unavailable", "needs_authentication", "provider_authorization_required", "unsupported_file", "permission_denied", "invalid_input", "worker_failed", "operation_failed"}
        if error_code not in allowed:
            error_code = "worker_failed"
        retry = retryable and error_code in {"provider_unavailable", "provider_transport", "provider_temporarily_unavailable", "worker_failed"} and job["attempt_count"] < job["max_attempts"]
        delay = min(300, 2 ** min(job["attempt_count"], 8)) * random.uniform(.75, 1.25)
        def persist(conn):
            changed = conn.execute(text("""UPDATE learning_jobs SET status=:status,error_code=:error,safe_error_code=:error,
                result=:result,next_retry_at=:retry,lease=NULL,expires=NULL
                WHERE id=:id AND owner_id=:owner AND lease=:lease AND status='running' AND expires>:now AND cancellation_requested=false AND cancel_requested=false"""),
                {"status": "retry_wait" if retry else "failed", "error": error_code,
                 "result": encoded({"message": "Temporary failure; retry scheduled." if retry else "This operation needs attention before retrying.", "code": error_code}),
                 "retry": time.time() + delay if retry else 0, "id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "now": time.time()})
            return changed.rowcount == 1
        if connection is not None:
            return persist(connection)
        with self.store.transaction() as conn:
            return persist(conn)

    def validate_lease(self, conn, job):
        changed = conn.execute(text("""UPDATE learning_jobs SET progress=progress WHERE id=:id AND owner_id=:owner
            AND lease=:lease AND status='running' AND expires>:now AND cancellation_requested=false AND cancel_requested=false"""),
            {"id": job["id"], "owner": job["owner_id"], "lease": job["lease"], "now": time.time()})
        if changed.rowcount != 1:
            problem("lease_lost", "This operation was resumed elsewhere.", 409)

    def heartbeat(self, job, progress=0, *, lease_seconds=900):
        if progress > 1:
            progress = progress / 100
        with self.store.transaction() as conn:
            try:
                self.validate_lease(conn, job)
            except Exception:
                return False
            conn.execute(text("UPDATE learning_jobs SET expires=:expires,progress=:progress WHERE id=:id AND owner_id=:owner"),
                         {"id": job["id"], "owner": job["owner_id"], "expires": time.time() + lease_seconds, "progress": max(0, min(1, progress))})
        return True

    def ready_ids(self, queue, kinds, limit=20):
        if queue not in {"interactive", "batch"} or not kinds or not 1 <= limit <= 100:
            raise ValueError("Invalid ready-job scope")
        from sqlalchemy import bindparam
        query = text("SELECT id FROM learning_jobs WHERE queue=:queue AND kind IN :kinds AND cancellation_requested=false AND cancel_requested=false AND next_retry_at<=:now AND (status IN ('queued','retry_wait') OR (status='running' AND expires<=:now)) ORDER BY priority DESC,created_at,id LIMIT :limit").bindparams(bindparam("kinds", expanding=True))
        with self.store.engine.connect() as conn:
            return list(conn.execute(query, {"queue": queue, "kinds": list(kinds), "now": time.time(), "limit": limit}).scalars())

    def validate_input(self, conn, job):
        if job["input_revision"] is None:
            return
        revision = conn.execute(text("SELECT revision FROM practice_records WHERE id=:id AND owner_id=:owner"),
                                {"id": job["target_id"], "owner": job["owner_id"]}).scalar_one_or_none()
        if revision is not None and revision != job["input_revision"]:
            problem("revision_conflict", "The source changed while this operation was running. Reload and retry.", 409)
