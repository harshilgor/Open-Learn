"""Durable generation records and replayable stream events."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .conversation_branching import ConversationBranchStore
from .generation_models import GenerationDescriptor
from .generation_models import GenerationEvent
from .material_service import problem

TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
ACTIVE = {"queued", "preparing", "streaming", "finalizing", "cancel_requested"}
TRANSITIONS = {
    "queued": {"preparing", "cancel_requested", "failed", "interrupted"},
    "preparing": {"streaming", "cancel_requested", "failed", "interrupted"},
    "streaming": {"finalizing", "cancel_requested", "failed", "interrupted"},
    "finalizing": {"completed", "cancel_requested", "failed", "interrupted"},
    "cancel_requested": {"cancelled", "failed", "interrupted"},
}


class StaleGenerationWrite(RuntimeError):
    """A generation mutation was rejected because its owner fence is stale."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class GenerationStore:
    def __init__(self, store):
        self.store = store

    def _row(self, row) -> dict:
        if not row:
            problem("not_found", "This generation is not available.", 404)
        payload = json.loads(row["payload"])
        result = json.loads(row["result"]) if row["result"] else None
        return {**payload, "id": row["id"], "status": row["status"], "sequence": row["sequence"],
                "cancellationRequested": bool(row["cancellation_requested"]), "provider": row["provider"],
                "model": row["model"], "errorCode": row["error_code"], "result": result,
                "messageEventId": row["message_event_id"], "branchId": row["branch_id"],
                "contextRevision": row["context_revision"], "parentGenerationId": row["parent_generation_id"],
                "relation": row["relation"], "ownerToken": row["owner_token"], "ownerFence": row["owner_fence"],
                "leaseExpiresAt": row["lease_expires_at"], "capacityReserved": bool(row["capacity_reserved"]),
                "partialOutput": row["partial_output"], "outputSeq": row["output_seq"]}

    def create(self, owner: str, session_id: str, request: dict, key: str, provider: str, model: str,
               on_create=None, *, reject_if_active: bool = True) -> dict:
        request = dict(request)
        client_message_id = str(request.get("clientMessageId") or key)
        if client_message_id != key:
            problem("idempotency_conflict", "Use the same ID for the message and its idempotency key.", 409)
        request["clientMessageId"] = client_message_id
        reply_to_generation_id = request.get("replyToGenerationId")
        parent_generation_id = request.get("parentGenerationId") or reply_to_generation_id
        request_hash = hashlib.sha256(_json([session_id, request]).encode()).hexdigest()
        now = time.time()
        message_text = request.get("message") or ("Start learning" if request.get("action") == "start" else "Continue")
        record = {"id": f"gen_{uuid4().hex}", "owner": owner, "session": session_id, "mode": request["mode"],
                  "request": request, "createdAt": now, "metrics": {"queuedAt": now}}
        values = {"id": record["id"], "owner": owner, "session": session_id, "key": key, "hash": request_hash,
                  "mode": request["mode"], "provider": provider, "model": model, "payload": _json(record), "now": now,
                  "message": message_text}
        try:
            with self.store.transaction() as conn:
                for referenced_generation_id in dict.fromkeys(
                    item for item in (reply_to_generation_id, parent_generation_id) if item
                ):
                    parent = conn.execute(text("""
                        SELECT id FROM generation_records
                        WHERE id=:id AND owner_id=:owner AND session_id=:session
                    """), {"id": referenced_generation_id, "owner": owner, "session": session_id}).first()
                    if not parent:
                        problem("not_found", "The response you referenced is not available in this conversation.", 404)
                existing = conn.execute(text("SELECT * FROM generation_records WHERE owner_id=:owner AND idempotency_key=:key"),
                                         values).mappings().first()
                if existing:
                    if existing["request_hash"] != request_hash:
                        problem("idempotency_conflict", "This request key was already used for another generation.", 409)
                    return {**self._row(existing), "createdNow": False}
                if reject_if_active:
                    active = conn.execute(text("""
                        SELECT id FROM generation_records WHERE owner_id=:owner AND session_id=:session
                            AND status IN ('queued','preparing','streaming','finalizing','cancel_requested')
                        LIMIT 1
                    """), values).first()
                    if active:
                        problem("generation_in_progress", "Finish or cancel the current response before sending another message.", 409)
                branches = ConversationBranchStore(self.store)
                event, branch, is_new_message = branches.accept_message(
                    conn, owner, session_id, client_message_id, message_text, request["mode"],
                    reply_to_generation_id=reply_to_generation_id)
                head = conn.execute(text("""
                    SELECT revision,selected_branch_id FROM conversation_branch_heads
                    WHERE owner_id=:owner AND session_id=:session
                """), {"owner": owner, "session": session_id}).mappings().one()
                record.update({"messageId": client_message_id, "conversationSeq": event["sequence"],
                               "contextRevision": event["sequence"], "branchId": branch["id"],
                               "relation": branch["relation"], "branchRevision": int(head["revision"]),
                               "selectedBranchId": head["selected_branch_id"]})
                values.update({"payload": _json(record), "event": event["id"], "branch": branch["id"],
                               "context_revision": event["sequence"],
                               "parent_generation": parent_generation_id,
                               "relation": branch["relation"]})
                conn.execute(text("""INSERT INTO generation_records(
                    id,owner_id,session_id,idempotency_key,request_hash,status,mode,provider,model,payload,
                    message_event_id,branch_id,context_revision,parent_generation_id,relation,
                    created_at,updated_at)
                    VALUES(:id,:owner,:session,:key,:hash,'queued',:mode,:provider,:model,:payload,
                    :event,:branch,:context_revision,:parent_generation,:relation,:now,:now)"""), values)
                if on_create is not None:
                    receipt = on_create(conn, record["id"], {
                        "messageId": client_message_id, "conversationSeq": event["sequence"],
                        "contextRevision": event["sequence"], "branchId": branch["id"],
                        "relation": branch["relation"], "isNewMessage": is_new_message,
                    })
                    if isinstance(receipt, dict):
                        if receipt.get("journeyRevision") is not None:
                            record["journeyRevision"] = receipt["journeyRevision"]
                        snapshot = receipt.get("contextSnapshot")
                        if snapshot is not None:
                            for turn in snapshot.get("turns", []):
                                if turn.get("status") == "pending" and turn.get("generationId") != record["id"]:
                                    prior = conn.execute(text("SELECT partial_output FROM generation_records WHERE id=:id"),
                                                         {"id": turn.get("generationId")}).first()
                                    if prior and prior[0]:
                                        turn["partialOutput"] = prior[0]
                            conn.execute(text("""INSERT INTO generation_context_snapshots(
                                generation_id,context_revision,snapshot_json,created_at)
                                VALUES(:id,:revision,:snapshot,:now)"""),
                                {"id": record["id"], "revision": event["sequence"],
                                 "snapshot": _json(snapshot), "now": now})
                    elif receipt is not None:
                        record["journeyRevision"] = receipt
                    conn.execute(text("UPDATE generation_records SET payload=:payload WHERE id=:id"),
                                 {"id": record["id"], "payload": _json(record)})
                ConversationBranchStore.append_generation_event(conn, record["id"], "message.accepted",
                    {"messageId": client_message_id, "conversationSeq": event["sequence"],
                     "contextRevision": event["sequence"], "branchId": branch["id"]})
                ConversationBranchStore.append_generation_event(conn, record["id"], "generation.queued",
                    {"branchId": branch["id"], "contextRevision": event["sequence"],
                     "queueReason": "capacity", "relation": branch["relation"]})
        except IntegrityError:
            with self.store.engine.connect() as conn:
                existing = conn.execute(text("SELECT * FROM generation_records WHERE owner_id=:owner AND idempotency_key=:key"), values).mappings().first()
            if existing and existing["request_hash"] == request_hash:
                return {**self._row(existing), "createdNow": False}
            if not existing or existing["request_hash"] != request_hash:
                problem("idempotency_conflict", "This message or request ID was already used for another submission.", 409)
        return {**self.get(owner, record["id"]), "createdNow": True}

    def accept_cancel_message(self, owner: str, session_id: str, request: dict, key: str,
                              provider: str, model: str) -> dict:
        """Durably accept an explicit stop command without starting a model run."""
        request = dict(request)
        client_message_id = str(request.get("clientMessageId") or key)
        if client_message_id != key:
            problem("idempotency_conflict", "Use the same ID for the message and its idempotency key.", 409)
        request["clientMessageId"] = client_message_id
        message = request.get("message", "")
        with self.store.transaction() as connection:
            result = ConversationBranchStore(self.store).accept_cancel_message(
                connection, owner, session_id, client_message_id, message,
                request.get("mode", "ask"), request.get("replyToGenerationId"))
        active = self.active_for_session(owner, session_id)
        return {
            "id": None, "owner": owner, "session": session_id, "mode": request.get("mode", "ask"),
            "status": "cancel_requested" if result["targetStatus"] == "cancel_requested" else "completed",
            "sequence": 0, "provider": provider, "model": model, "errorCode": None, "result": None,
            "messageId": client_message_id, "conversationSeq": result["event"]["sequence"],
            "contextRevision": result["event"]["sequence"], "branchId": result["branch"]["id"],
            "relation": "cancel", "branchRevision": result["branchRevision"],
            "selectedBranchId": result["selectedBranchId"], "accepted": True,
            "scheduledGenerationIds": [item["id"] for item in active if item["status"] == "queued"],
            "activeGenerationIds": [item["id"] for item in active if item["status"] != "queued"],
            "cancelTargetGenerationId": result["targetGenerationId"], "cancelTargetStatus": result["targetStatus"],
            "metrics": {}, "createdNow": result["event"]["sequence"] > 0,
        }

    def retry(self, owner: str, source_generation_id: str, key: str,
              *, provider: str | None = None, model: str | None = None, on_create=None) -> dict:
        """Create a fresh execution for a failed/interrupted accepted message."""
        now = time.time()
        generation_id = f"gen_{uuid4().hex}"
        try:
            with self.store.transaction() as connection:
                source = connection.execute(text("""
                    SELECT * FROM generation_records WHERE id=:id AND owner_id=:owner
                """), {"id": source_generation_id, "owner": owner}).mappings().first()
                if not source:
                    problem("not_found", "This response is not available to retry.", 404)
                request = json.loads(source["payload"]).get("request") or {}
                request_hash = hashlib.sha256(_json(["retry", source_generation_id, request]).encode()).hexdigest()
                existing = connection.execute(text("""
                    SELECT * FROM generation_records WHERE owner_id=:owner AND idempotency_key=:key
                """), {"owner": owner, "key": key}).mappings().first()
                if existing:
                    if existing["request_hash"] != request_hash:
                        problem("idempotency_conflict", "This retry key was already used for another request.", 409)
                    return {**self._row(existing), "createdNow": False}
                if source["status"] not in {"failed", "interrupted"}:
                    problem("retry_not_available", "Only failed or interrupted responses can be retried.", 409)
                snapshot = connection.execute(text("""
                    SELECT snapshot_json FROM generation_context_snapshots WHERE generation_id=:id
                """), {"id": source_generation_id}).first()
                if not snapshot:
                    problem("retry_not_available", "This response has no saved context snapshot. Send the message again to retry it.", 409)
                event = connection.execute(text("""
                    SELECT id,sequence,client_message_id FROM conversation_events
                    WHERE id=:event AND owner_id=:owner AND session_id=:session
                """), {"event": source["message_event_id"], "owner": owner,
                       "session": source["session_id"]}).mappings().first()
                if not event:
                    problem("retry_not_available", "This response no longer has an accepted message to retry.", 409)
                payload = {"id": generation_id, "owner": owner, "session": source["session_id"],
                    "mode": source["mode"], "request": request, "createdAt": now,
                    "metrics": {"queuedAt": now, "retryOfGenerationId": source_generation_id},
                    "messageId": event["client_message_id"], "conversationSeq": event["sequence"],
                    "contextRevision": source["context_revision"], "branchId": source["branch_id"],
                    "relation": source["relation"], "parentGenerationId": source_generation_id}
                values = {"id": generation_id, "owner": owner, "session": source["session_id"],
                    "key": key, "hash": request_hash, "mode": source["mode"],
                    "provider": provider or source["provider"], "model": model or source["model"], "payload": _json(payload),
                    "event": source["message_event_id"], "branch": source["branch_id"],
                    "context_revision": source["context_revision"], "parent_generation": source_generation_id,
                    "relation": source["relation"], "now": now}
                connection.execute(text("""
                    INSERT INTO generation_records(
                        id,owner_id,session_id,idempotency_key,request_hash,status,mode,provider,model,payload,
                        message_event_id,branch_id,context_revision,parent_generation_id,relation,created_at,updated_at)
                    VALUES(:id,:owner,:session,:key,:hash,'queued',:mode,:provider,:model,:payload,
                        :event,:branch,:context_revision,:parent_generation,:relation,:now,:now)
                """), values)
                if on_create is not None:
                    receipt = on_create(connection, generation_id, {
                        "messageId": event["client_message_id"], "conversationSeq": event["sequence"],
                        "contextRevision": source["context_revision"], "branchId": source["branch_id"],
                        "relation": source["relation"], "isRetry": True,
                    })
                    retry_snapshot = receipt.get("contextSnapshot") if isinstance(receipt, dict) else None
                    if retry_snapshot is not None:
                        connection.execute(text("""
                            INSERT INTO generation_context_snapshots(generation_id,context_revision,snapshot_json,created_at)
                            VALUES(:id,:revision,:snapshot,:now)
                        """), {"id": generation_id, "revision": source["context_revision"],
                               "snapshot": _json(retry_snapshot), "now": now})
                    if isinstance(receipt, dict) and receipt.get("journeyRevision") is not None:
                        payload["journeyRevision"] = receipt["journeyRevision"]
                        connection.execute(text("UPDATE generation_records SET payload=:payload WHERE id=:id"),
                                           {"payload": _json(payload), "id": generation_id})
                ConversationBranchStore.append_generation_event(connection, generation_id, "generation.queued",
                    {"branchId": source["branch_id"], "contextRevision": source["context_revision"],
                     "queueReason": "capacity", "retryOfGenerationId": source_generation_id})
        except IntegrityError:
            with self.store.engine.connect() as connection:
                existing = connection.execute(text("SELECT * FROM generation_records WHERE owner_id=:owner AND idempotency_key=:key"),
                    {"owner": owner, "key": key}).mappings().first()
            if existing and existing["request_hash"] == request_hash:
                return {**self._row(existing), "createdNow": False}
            problem("idempotency_conflict", "This retry key was already used for another request.", 409)
        return {**self.get(owner, generation_id), "createdNow": True}

    def get(self, owner: str, generation_id: str) -> dict:
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM generation_records WHERE id=:id AND owner_id=:owner"), {"id": generation_id, "owner": owner}).mappings().first()
        return self._row(row)

    def transition(self, generation_id: str, status: str, *, error_code: str | None = None,
                   sequence: int | None = None, result: dict | None = None,
                   owner_token: str | None = None, connection=None) -> dict:
        if connection is None:
            try:
                with self.store.transaction() as conn:
                    return self.transition(generation_id, status, error_code=error_code, sequence=sequence,
                                           result=result, owner_token=owner_token, connection=conn)
            except StaleGenerationWrite as exc:
                self._record_stale_write()
                exc.metric_recorded = True
                raise
        row = connection.execute(text("SELECT * FROM generation_records WHERE id=:id"), {"id": generation_id}).mappings().first()
        if not row:
            raise RuntimeError("Missing generation")
        current = row["status"]
        if status not in TRANSITIONS.get(current, set()):
            raise RuntimeError(f"Illegal generation transition {current} -> {status}")
        values = {"id": generation_id, "status": status, "now": time.time(), "error": error_code,
                  "sequence": max(int(row["sequence"]), sequence or 0), "result": _json(result) if result is not None else row["result"]}
        ownership_clause = " AND owner_token=:owner_token" if owner_token is not None else ""
        transition_values = {**values, "previous": current}
        if owner_token is not None:
            transition_values["owner_token"] = owner_token
            ownership_clause += " AND capacity_reserved=1 AND lease_expires_at>:now"
        if status == "failed":
            # A durable Stop request wins a race against provider/error handling.
            # Recheck in the UPDATE predicate so a concurrent cancellation cannot
            # be overwritten after the row was initially read above.
            ownership_clause += " AND cancellation_requested=0"
        updated = connection.execute(text(f"""
            UPDATE generation_records SET status=:status,updated_at=:now,error_code=:error,
                sequence=:sequence,result=:result WHERE id=:id AND status=:previous{ownership_clause}
        """), transition_values)
        if updated.rowcount != 1:
            if owner_token is not None:
                raise StaleGenerationWrite("Generation changed or this worker no longer owns it")
            raise RuntimeError("Generation changed before its state transition")
        if status in TERMINAL and row["capacity_reserved"]:
            self._release_capacity(connection, row)
        return self._row(connection.execute(text("SELECT * FROM generation_records WHERE id=:id"), {"id": generation_id}).mappings().one())

    @staticmethod
    def _capacity_id(owner: str, session_id: str) -> str:
        return f"{owner}:{session_id}"

    def _ensure_capacity(self, connection, scope_type: str, scope_id: str, limit_count: int) -> None:
        connection.execute(text("""
            INSERT INTO generation_capacity(scope_type,scope_id,active_count,limit_count,updated_at)
            VALUES(:type,:scope,0,:limit,:now)
            ON CONFLICT(scope_type,scope_id) DO NOTHING
        """), {"type": scope_type, "scope": scope_id, "limit": limit_count, "now": time.time()})
        connection.execute(text("""
            UPDATE generation_capacity SET limit_count=:limit,updated_at=:now
            WHERE scope_type=:type AND scope_id=:scope
        """), {"type": scope_type, "scope": scope_id, "limit": limit_count, "now": time.time()})

    def claim_capacity(self, generation_id: str, *, conversation_limit: int, global_limit: int,
                       lease_seconds: float = 90, provider: str | None = None,
                       model: str | None = None) -> dict | None:
        """Atomically reserve both per-conversation and deployment-wide slots."""
        owner_token = f"owner_{uuid4().hex}"
        now = time.time()
        with self.store.transaction() as connection:
            row = connection.execute(text("SELECT * FROM generation_records WHERE id=:id"),
                                     {"id": generation_id}).mappings().first()
            if not row or row["status"] != "queued":
                return None
            conversation_id = self._capacity_id(row["owner_id"], row["session_id"])
            self._ensure_capacity(connection, "conversation", conversation_id, conversation_limit)
            self._ensure_capacity(connection, "global", "deployment", global_limit)
            acquired_conversation = connection.execute(text("""
                UPDATE generation_capacity SET active_count=active_count+1,updated_at=:now
                WHERE scope_type='conversation' AND scope_id=:scope AND active_count<limit_count
                RETURNING active_count
            """), {"scope": conversation_id, "now": now}).first()
            if not acquired_conversation:
                return None
            acquired_global = connection.execute(text("""
                UPDATE generation_capacity SET active_count=active_count+1,updated_at=:now
                WHERE scope_type='global' AND scope_id='deployment' AND active_count<limit_count
                RETURNING active_count
            """), {"now": now}).first()
            if not acquired_global:
                connection.execute(text("""
                    UPDATE generation_capacity SET active_count=CASE WHEN active_count>0 THEN active_count-1 ELSE 0 END,
                        updated_at=:now WHERE scope_type='conversation' AND scope_id=:scope
                """), {"scope": conversation_id, "now": now})
                return None
            claimed = connection.execute(text("""
                UPDATE generation_records SET status='preparing',owner_token=:token,
                    owner_fence=owner_fence+1,lease_expires_at=:expires,capacity_reserved=1,
                    provider=COALESCE(:provider,provider),model=COALESCE(:model,model),updated_at=:now
                WHERE id=:id AND status='queued'
            """), {"token": owner_token, "expires": now + lease_seconds, "now": now,
                   "provider": provider, "model": model, "id": generation_id})
            if claimed.rowcount != 1:
                self._decrement_capacity(connection, "conversation", conversation_id, now)
                self._decrement_capacity(connection, "global", "deployment", now)
                return None
            result = connection.execute(text("SELECT * FROM generation_records WHERE id=:id"),
                                        {"id": generation_id}).mappings().one()
            return self._row(result)

    @staticmethod
    def _decrement_capacity(connection, scope_type: str, scope_id: str, now: float) -> None:
        connection.execute(text("""
            UPDATE generation_capacity SET active_count=CASE WHEN active_count>0 THEN active_count-1 ELSE 0 END,
                updated_at=:now WHERE scope_type=:type AND scope_id=:scope
        """), {"type": scope_type, "scope": scope_id, "now": now})

    def _release_capacity(self, connection, row) -> None:
        now = time.time()
        self._decrement_capacity(connection, "conversation",
                                 self._capacity_id(row["owner_id"], row["session_id"]), now)
        self._decrement_capacity(connection, "global", "deployment", now)
        connection.execute(text("""
            UPDATE generation_records SET capacity_reserved=0,lease_expires_at=NULL
            WHERE id=:id
        """), {"id": row["id"]})

    def renew_lease(self, generation_id: str, owner_token: str, lease_seconds: float = 90) -> bool:
        now = time.time()
        with self.store.transaction() as connection:
            result = connection.execute(text("""
                UPDATE generation_records SET lease_expires_at=:expires,updated_at=:now
                WHERE id=:id AND owner_token=:token AND capacity_reserved=1
                    AND lease_expires_at>:now
                    AND cancellation_requested=0
                    AND status IN ('preparing','streaming','finalizing')
            """), {"id": generation_id, "token": owner_token, "expires": now + lease_seconds, "now": now})
            return result.rowcount == 1

    def checkpoint(self, generation_id: str, owner_token: str, output: str,
                   output_sequence: int | None = None, lease_seconds: float = 90) -> bool:
        now = time.time()
        with self.store.transaction() as connection:
            result = connection.execute(text("""
                UPDATE generation_records SET partial_output=COALESCE(partial_output,'')||:output,
                    output_seq=CASE WHEN :sequence IS NULL THEN output_seq+1 ELSE :sequence END,
                    lease_expires_at=:expires,updated_at=:now
                WHERE id=:id AND owner_token=:token AND capacity_reserved=1 AND lease_expires_at>:now
                    AND status IN ('streaming','finalizing')
            """), {"id": generation_id, "token": owner_token, "output": output,
                   "sequence": output_sequence, "expires": now + lease_seconds, "now": now})
            return result.rowcount == 1

    def interrupt_expired_leases(self, now: float | None = None) -> list[str]:
        """Interrupt only executions whose durable ownership lease has expired."""
        now = now or time.time()
        interrupted: list[str] = []
        with self.store.transaction() as connection:
            rows = connection.execute(text("""
                SELECT * FROM generation_records
                WHERE capacity_reserved=1 AND lease_expires_at IS NOT NULL AND lease_expires_at<=:now
                    AND status IN ('preparing','streaming','finalizing','cancel_requested')
            """), {"now": now}).mappings().all()
            for row in rows:
                changed = connection.execute(text("""
                    UPDATE generation_records SET status='interrupted',error_code='STREAM_INTERRUPTED',
                        capacity_reserved=0,lease_expires_at=NULL,updated_at=:now
                    WHERE id=:id AND owner_token=:token AND lease_expires_at<=:now
                        AND status IN ('preparing','streaming','finalizing','cancel_requested')
                """), {"id": row["id"], "token": row["owner_token"], "now": now})
                if changed.rowcount != 1:
                    continue
                self._decrement_capacity(connection, "conversation",
                    self._capacity_id(row["owner_id"], row["session_id"]), now)
                self._decrement_capacity(connection, "global", "deployment", now)
                ConversationBranchStore.append_generation_event(connection, row["id"], "generation.interrupted",
                    {"reason": "worker_lease_expired", "partialOutputAvailable": bool(row["partial_output"])})
                try:
                    from .journey_service import JourneyService
                    JourneyService(self.store, None).finish_stream_turn(
                        row["owner_id"], row["session_id"], row["id"], "interrupted", "STREAM_INTERRUPTED", connection)
                except Exception:
                    # Old generations may not have a canonical Journey turn.
                    pass
                interrupted.append(row["id"])
        return interrupted

    def interrupt_unowned_legacy(self) -> list[str]:
        """Close pre-lease active rows left by the serial generation manager."""
        now = time.time()
        interrupted: list[str] = []
        with self.store.transaction() as connection:
            rows = connection.execute(text("""
                SELECT * FROM generation_records
                WHERE owner_token IS NULL AND capacity_reserved=0
                    AND status IN ('preparing','streaming','finalizing','cancel_requested')
            """)).mappings().all()
            for row in rows:
                changed = connection.execute(text("""
                    UPDATE generation_records SET status='interrupted',error_code='STREAM_INTERRUPTED',
                        lease_expires_at=NULL,updated_at=:now
                    WHERE id=:id AND owner_token IS NULL AND capacity_reserved=0
                        AND status IN ('preparing','streaming','finalizing','cancel_requested')
                """), {"id": row["id"], "now": now})
                if changed.rowcount != 1:
                    continue
                ConversationBranchStore.append_generation_event(connection, row["id"], "generation.interrupted",
                    {"reason": "legacy_worker_recovery", "partialOutputAvailable": bool(row["partial_output"])})
                try:
                    from .journey_service import JourneyService
                    JourneyService(self.store, None).finish_stream_turn(
                        row["owner_id"], row["session_id"], row["id"], "interrupted", "STREAM_INTERRUPTED", connection)
                except Exception:
                    pass
                interrupted.append(row["id"])
        return interrupted

    def queued_for_session(self, owner: str, session_id: str, limit: int = 20) -> list[dict]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM generation_records WHERE owner_id=:owner AND session_id=:session AND status='queued'
                ORDER BY created_at,id LIMIT :limit
            """), {"owner": owner, "session": session_id, "limit": limit}).mappings().all()
        return [self._row(row) for row in rows]

    def queued_global(self, limit: int = 200) -> list[dict]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM generation_records WHERE status='queued'
                ORDER BY created_at,id LIMIT :limit
            """), {"limit": limit}).mappings().all()
        return [self._row(row) for row in rows]

    def request_cancel(self, owner: str, generation_id: str) -> dict:
        with self.store.transaction() as conn:
            row = conn.execute(text("SELECT * FROM generation_records WHERE id=:id AND owner_id=:owner"), {"id": generation_id, "owner": owner}).mappings().first()
            state = self._row(row)
            if state["status"] in TERMINAL:
                return state
            already_requested = state["cancellationRequested"]
            conn.execute(text("UPDATE generation_records SET cancellation_requested=1,status=CASE WHEN status IN ('queued','preparing','streaming','finalizing') THEN 'cancel_requested' ELSE status END,updated_at=:now WHERE id=:id"), {"id": generation_id, "now": time.time()})
            updated = self._row(conn.execute(text("SELECT * FROM generation_records WHERE id=:id"), {"id": generation_id}).mappings().one())
            if not already_requested:
                ConversationBranchStore(self.store).append_cancel_event(conn, owner, state["session"], generation_id)
            return updated

    def update_metrics(self, generation_id: str, values: dict, connection=None,
                       owner_token: str | None = None) -> None:
        if connection is None:
            try:
                with self.store.transaction() as conn:
                    self.update_metrics(generation_id, values, conn, owner_token)
                    return
            except StaleGenerationWrite as exc:
                self._record_stale_write()
                exc.metric_recorded = True
                raise
        query = "SELECT payload FROM generation_records WHERE id=:id"
        params = {"id": generation_id}
        if owner_token is not None:
            query += " AND owner_token=:token AND capacity_reserved=1 AND lease_expires_at>:now"
            params.update({"token": owner_token, "now": time.time()})
        row = connection.execute(text(query), params).first()
        if not row:
            if owner_token is not None:
                raise StaleGenerationWrite("Generation is missing or this worker no longer owns it")
            raise RuntimeError("Generation is missing or this worker no longer owns it")
        payload = json.loads(row[0]); payload.setdefault("metrics", {}).update(values)
        query = "UPDATE generation_records SET payload=:payload,updated_at=:now WHERE id=:id"
        params = {"id": generation_id, "payload": _json(payload), "now": time.time()}
        if owner_token is not None:
            query += " AND owner_token=:token AND capacity_reserved=1 AND lease_expires_at>:now"
            params["token"] = owner_token
            params["now"] = time.time()
        updated = connection.execute(text(query), params)
        if updated.rowcount != 1:
            if owner_token is not None:
                raise StaleGenerationWrite("Generation changed or this worker no longer owns it")
            raise RuntimeError("Generation changed before metrics were saved")

    def cancelled(self, generation_id: str) -> bool:
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT cancellation_requested FROM generation_records WHERE id=:id"), {"id": generation_id}).first()
        return bool(row and row[0])

    def append_event(self, generation_id: str, event_type: str, data: dict | None = None,
                     connection=None, owner_token: str | None = None, *,
                     allow_cancelled_checkpoint: bool = False) -> GenerationEvent:
        if connection is None:
            try:
                with self.store.transaction() as conn:
                    return self.append_event(generation_id, event_type, data, conn, owner_token,
                                             allow_cancelled_checkpoint=allow_cancelled_checkpoint)
            except StaleGenerationWrite as exc:
                self._record_stale_write()
                exc.metric_recorded = True
                raise
        values = {"id": generation_id}
        ownership_clause = ""
        if owner_token is not None:
            values["now"] = time.time()
            ownership_clause = " AND owner_token=:owner_token"
            values["owner_token"] = owner_token
            if allow_cancelled_checkpoint and event_type != "text.delta":
                raise ValueError("Only a final text checkpoint may be written after cancellation.")
            if allow_cancelled_checkpoint:
                ownership_clause += " AND capacity_reserved=1 AND lease_expires_at>:now"
                ownership_clause += " AND status='cancel_requested' AND cancellation_requested=1"
            elif event_type in {"generation.completed", "generation.cancelled", "generation.error", "generation.interrupted"}:
                ownership_clause += " AND status IN ('completed','cancelled','failed','interrupted')"
            elif event_type == "generation.cancel_requested":
                ownership_clause += " AND status='cancel_requested' AND capacity_reserved=1"
            else:
                ownership_clause += " AND capacity_reserved=1 AND lease_expires_at>:now"
                ownership_clause += " AND status IN ('preparing','streaming','finalizing') AND cancellation_requested=0"
        if event_type == "text.delta" and isinstance((data or {}).get("text"), str):
            values["text"] = (data or {})["text"]
            row = connection.execute(text(f"""
                UPDATE generation_records SET sequence=sequence+1,
                    partial_output=COALESCE(partial_output,'')||:text,output_seq=output_seq+1
                WHERE id=:id{ownership_clause} RETURNING sequence
            """), values).first()
        else:
            row = connection.execute(text(f"""
                UPDATE generation_records SET sequence=sequence+1
                WHERE id=:id{ownership_clause} RETURNING sequence
            """), values).first()
        if row is None:
            if owner_token is not None:
                raise StaleGenerationWrite("Generation is missing or this worker no longer owns it")
            raise RuntimeError("Generation is missing or this worker no longer owns it")
        sequence = int(row[0])
        connection.execute(text("INSERT INTO generation_events(generation_id,sequence,event_type,data_json,created_at) VALUES(:id,:sequence,:type,:data,:now)"),
                           {"id": generation_id, "sequence": sequence, "type": event_type, "data": _json(data or {}), "now": time.time()})
        return GenerationEvent(generation_id=generation_id, sequence=sequence, type=event_type, data=data or {})

    def validate_owner(self, connection, generation_id: str, owner_token: str) -> dict:
        row = connection.execute(text("""
            SELECT * FROM generation_records WHERE id=:id AND owner_token=:token
                AND capacity_reserved=1 AND lease_expires_at>:now
        """), {"id": generation_id, "token": owner_token, "now": time.time()}).mappings().first()
        if not row:
            raise StaleGenerationWrite("Generation ownership lease was lost")
        return self._row(row)

    def record_acceptance_latency(self, generation_id: str, latency_ms: float) -> None:
        """Persist the measured HTTP acceptance work once, without touching stream payloads."""
        with self.store.transaction() as connection:
            connection.execute(text("""
                INSERT INTO generation_acceptance_metrics(generation_id,acceptance_latency_ms,measured_at)
                VALUES(:id,:latency,:now) ON CONFLICT(generation_id) DO NOTHING
            """), {"id": generation_id, "latency": max(0.0, float(latency_ms)), "now": time.time()})

    def _record_stale_write(self) -> None:
        now = time.time()
        try:
            with self.store.transaction() as connection:
                connection.execute(text("""
                    INSERT INTO live_branching_metric_counters(name,value,updated_at)
                    VALUES('stale_write_rejections',1,:now)
                    ON CONFLICT(name) DO UPDATE SET value=value+1,updated_at=excluded.updated_at
                """), {"now": now})
            logging.getLogger(__name__).warning(
                "Live branching rejected a stale generation write",
                extra={"metric": "live_branching.stale_write_rejections", "metric_delta": 1},
            )
        except Exception:
            # Fencing still rejects the write if telemetry storage is unavailable.
            logging.getLogger(__name__).exception("Could not persist stale generation write metric")

    def record_stale_write(self) -> None:
        """Record a fenced write discovered inside a larger caller transaction."""
        self._record_stale_write()

    def active_for_session(self, owner: str, session_id: str) -> list[dict]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM generation_records WHERE owner_id=:owner AND session_id=:session
                    AND status IN ('queued','preparing','streaming','finalizing','cancel_requested')
                ORDER BY created_at,id
            """), {"owner": owner, "session": session_id}).mappings().all()
        return [self._row(row) for row in rows]

    def events_after(self, generation_id: str, after: int) -> list[GenerationEvent]:
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT sequence,event_type,data_json FROM generation_events WHERE generation_id=:id AND sequence>:after ORDER BY sequence"),
                                {"id": generation_id, "after": after}).mappings().all()
        return [GenerationEvent(generation_id=generation_id, sequence=row["sequence"], type=row["event_type"], data=json.loads(row["data_json"])) for row in rows]

    def interrupt_active(self) -> None:
        from .journey_service import JourneyService
        journey_service = JourneyService(self.store, None)
        with self.store.transaction() as conn:
            rows = conn.execute(text("SELECT id,owner_id,session_id FROM generation_records WHERE status IN ('queued','preparing','streaming','finalizing','cancel_requested')")).mappings().all()
            conn.execute(text("UPDATE generation_records SET status='interrupted',error_code='STREAM_INTERRUPTED',updated_at=:now WHERE status IN ('queued','preparing','streaming','finalizing','cancel_requested')"), {"now": time.time()})
            for row in rows:
                try:
                    journey_service.finish_stream_turn(row["owner_id"], row["session_id"], row["id"], "interrupted", "STREAM_INTERRUPTED", conn)
                except Exception:
                    # Older generations predate canonical submitted turns.
                    pass
                self.append_event(row["id"], "generation.error", {"code": "STREAM_INTERRUPTED", "message": "The generation was interrupted. Please try again."}, conn)

    @staticmethod
    def descriptor(record: dict) -> GenerationDescriptor:
        result = record.get("result") or {}
        return GenerationDescriptor(
            id=record["id"], session_id=record["session"], mode=record["mode"], status=record["status"],
            sequence=record["sequence"], provider=record["provider"], model=record["model"],
            journey_revision=record.get("journeyRevision"), final_revision=result.get("revision"),
            error_code=record.get("errorCode"), message_id=record.get("messageId"),
            conversation_seq=record.get("conversationSeq"), context_revision=record.get("contextRevision"),
            parent_generation_id=record.get("parentGenerationId"),
            branch_id=record.get("branchId"), relation=record.get("relation"),
            branch_revision=record.get("branchRevision"), selected_branch_id=record.get("selectedBranchId"),
            cancel_target_generation_id=record.get("cancelTargetGenerationId"),
            cancel_target_status=record.get("cancelTargetStatus"),
            accepted=True, scheduled_generation_ids=record.get("scheduledGenerationIds") or [],
            active_generation_ids=record.get("activeGenerationIds") or [],
            metrics=record.get("metrics") or {},
        )
