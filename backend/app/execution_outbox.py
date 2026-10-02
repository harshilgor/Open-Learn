"""Transactional follow-up delivery and monotone projection checkpoints.

Handlers execute in the same short database transaction as the delivery mark.
They must only mutate durable state or enqueue jobs, never call providers.
"""
import hashlib
import time
from sqlalchemy import text
from .workflow_store import encoded, uid
from .material_service import problem


class ExecutionOutbox:
    def __init__(self, store):
        self.store = store

    def append(self, connection, owner, topic, key, payload):
        digest = hashlib.sha256(encoded(payload).encode()).hexdigest()
        args = {"id": uid("outbox"), "owner": owner, "topic": topic, "key": key,
                "hash": digest, "payload": encoded(payload), "now": time.time()}
        connection.execute(text("""INSERT INTO execution_outbox(id,owner_id,topic,command_key,request_hash,payload,created_at)
            VALUES(:id,:owner,:topic,:key,:hash,:payload,:now) ON CONFLICT(owner_id,topic,command_key) DO NOTHING"""), args)
        row = connection.execute(text("SELECT id,request_hash FROM execution_outbox WHERE owner_id=:owner AND topic=:topic AND command_key=:key"), args).one()
        if row[1] != digest:
            problem("idempotency_conflict", "The follow-up key has different input.", 409)
        return row[0]

    def drain(self, handlers, limit=20):
        import json
        if not 1 <= limit <= 100:
            raise ValueError("Invalid delivery limit")
        delivered = 0
        for _ in range(limit):
            with self.store.transaction() as conn:
                if conn.dialect.name == "sqlite":
                    # Acquire the SQLite writer before selecting. A SELECT then
                    # UPDATE race would deadlock two deferred transactions.
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                suffix = " FOR UPDATE SKIP LOCKED" if conn.dialect.name == "postgresql" else ""
                from sqlalchemy import bindparam
                if not handlers:
                    return delivered
                query = text("SELECT * FROM execution_outbox WHERE delivered_at IS NULL AND topic IN :topics ORDER BY created_at,id LIMIT 1" + suffix).bindparams(bindparam("topics", expanding=True))
                row = conn.execute(query, {"topics": list(handlers)}).mappings().first()
                if row is None:
                    break
                handlers[row["topic"]](conn, row["owner_id"], row["id"], json.loads(row["payload"]))
                conn.execute(text("UPDATE execution_outbox SET delivered_at=:now WHERE id=:id"), {"id": row["id"], "now": time.time()})
            delivered += 1
        return delivered

    def advance(self, connection, owner, projection, sequence, revision):
        if sequence < 0:
            raise ValueError("Invalid watermark")
        connection.execute(text("""INSERT INTO execution_watermarks(owner_id,projection,sequence,revision) VALUES(:owner,:projection,:sequence,:revision)
            ON CONFLICT(owner_id,projection) DO UPDATE SET sequence=excluded.sequence,revision=excluded.revision
            WHERE execution_watermarks.sequence<=excluded.sequence"""), {"owner": owner, "projection": projection, "sequence": sequence, "revision": revision})

    def require(self, owner, projection, sequence, revision):
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT sequence,revision FROM execution_watermarks WHERE owner_id=:owner AND projection=:projection"), {"owner": owner, "projection": projection}).first()
        if not row or row[0] < sequence or row[1] != revision:
            problem("analysis_pending", "Required analysis is still catching up. Retry shortly.", 409)
        return row[0]
