"""Durable message events and branch selection for live chat generations."""
from __future__ import annotations

import json
import re
import time
from uuid import uuid4

from sqlalchemy import text

from .material_service import problem


RELATIONS = {"add", "clarify", "revise", "new_topic", "cancel", "uncertain"}


def classify_relation(message: str, has_previous: bool = True) -> str:
    """Cheap deterministic routing; uncertain input always preserves prior work."""
    value = re.sub(r"\s+", " ", (message or "").strip().lower())
    if re.fullmatch(r"(?:please\s+)?(?:stop(?:\s+generating)?|cancel(?:\s+(?:that|this|the response))?|abort|never\s*mind(?:\s+that)?|don't\s+continue)[.! ]*", value):
        return "cancel"
    if not has_previous or re.search(r"\b(new topic|different topic|forget that|switch topics)\b", value):
        return "new_topic"
    if re.search(r"\b(i meant|i mean|actually|to clarify|what i meant|that's not what)\b", value):
        return "clarify"
    if re.search(r"\b(instead|rather|rewrite|rephrase|make it|change it|use a .* analogy)\b", value):
        return "revise"
    if re.search(r"\b(also|additionally|in addition|another question|and what about)\b", value):
        return "add"
    return "uncertain"


def visible_context_turns(turns: list[dict], branch_id: str | None,
                          parent_by_branch: dict[str, str | None]) -> list[dict]:
    """Keep legacy turns plus the branch ancestors; exclude sibling answers."""
    ancestors: set[str] = set()
    current = parent_by_branch.get(branch_id) if branch_id else None
    while current and current not in ancestors:
        ancestors.add(current)
        current = parent_by_branch.get(current)
    return [turn for turn in turns
            if not turn.get("branchId") or turn.get("branchId") in ancestors]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ConversationBranchStore:
    """Conversation event log and selected response branch state."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _next_sequence(connection, owner: str, session_id: str) -> int:
        values = {"owner": owner, "session": session_id, "now": time.time()}
        connection.execute(text("""
            INSERT INTO conversation_event_counters(owner_id,session_id,sequence)
            VALUES(:owner,:session,0)
            ON CONFLICT(owner_id,session_id) DO NOTHING
        """), values)
        row = connection.execute(text("""
            UPDATE conversation_event_counters SET sequence=sequence+1
            WHERE owner_id=:owner AND session_id=:session
            RETURNING sequence
        """), values).first()
        if row is None:
            raise RuntimeError("Could not allocate a conversation event sequence")
        return int(row[0])

    def append_event(self, connection, owner: str, session_id: str, event_type: str,
                     payload: dict, *, client_message_id: str | None = None,
                     created_at: float | None = None) -> dict:
        now = created_at or time.time()
        sequence = self._next_sequence(connection, owner, session_id)
        event_id = _id("evt")
        connection.execute(text("""
            INSERT INTO conversation_events(id,owner_id,session_id,sequence,event_type,
                client_message_id,payload_json,created_at)
            VALUES(:id,:owner,:session,:sequence,:type,:client,:payload,:created)
        """), {"id": event_id, "owner": owner, "session": session_id, "sequence": sequence,
               "type": event_type, "client": client_message_id, "payload": _json(payload), "created": now})
        return {"id": event_id, "sequence": sequence, "type": event_type, "payload": payload, "createdAt": now}

    def accept_message(self, connection, owner: str, session_id: str, client_message_id: str,
                       message: str, mode: str, reply_to_generation_id: str | None = None) -> tuple[dict, dict, bool]:
        """Return (event, branch, is_new_message), deduplicating by client ID."""
        existing = connection.execute(text("""
            SELECT id,sequence,event_type,payload_json,created_at FROM conversation_events
            WHERE owner_id=:owner AND session_id=:session AND client_message_id=:client
        """), {"owner": owner, "session": session_id, "client": client_message_id}).mappings().first()
        if existing:
            payload = json.loads(existing["payload_json"])
            if payload.get("text") != message:
                problem("idempotency_conflict", "This message ID was already used for different text.", 409)
            event = {"id": existing["id"], "sequence": existing["sequence"], "type": existing["event_type"],
                     "payload": payload, "createdAt": existing["created_at"]}
            branch = connection.execute(text("""
                SELECT * FROM response_branches WHERE trigger_event_id=:event
                ORDER BY created_at DESC LIMIT 1
            """), {"event": event["id"]}).mappings().first()
            if not branch:
                raise RuntimeError("Accepted conversation message is missing its response branch")
            return event, dict(branch), False

        previous = connection.execute(text("""
            SELECT COUNT(*) FROM conversation_events
            WHERE owner_id=:owner AND session_id=:session AND event_type='user_message'
        """), {"owner": owner, "session": session_id}).scalar_one()
        relation = classify_relation(message, bool(previous))
        payload = {"text": message, "mode": mode}
        if reply_to_generation_id:
            payload["replyToGenerationId"] = reply_to_generation_id
        event = self.append_event(connection, owner, session_id, "user_message",
            payload, client_message_id=client_message_id)
        head = connection.execute(text("""
            SELECT selected_branch_id,revision FROM conversation_branch_heads
            WHERE owner_id=:owner AND session_id=:session
        """), {"owner": owner, "session": session_id}).mappings().first()
        parent_branch_id = head["selected_branch_id"] if head else None
        if reply_to_generation_id:
            replied_to = connection.execute(text("""
                SELECT branch_id FROM generation_records
                WHERE id=:id AND owner_id=:owner AND session_id=:session
            """), {"id": reply_to_generation_id, "owner": owner, "session": session_id}).first()
            if not replied_to:
                problem("not_found", "The response you are replying to is not available in this conversation.", 404)
            parent_branch_id = replied_to[0]
        elif relation == "new_topic":
            parent_branch_id = None
        branch_id = _id("branch")
        now = time.time()
        selecting = relation != "cancel"
        connection.execute(text("""
            INSERT INTO response_branches(id,owner_id,session_id,parent_branch_id,trigger_event_id,
                relation,status,created_at,updated_at)
            VALUES(:id,:owner,:session,:parent,:event,:relation,:status,:now,:now)
        """), {"id": branch_id, "owner": owner, "session": session_id, "parent": parent_branch_id,
               "event": event["id"], "relation": relation,
               "status": "selected" if selecting else "control", "now": now})
        if selecting:
            connection.execute(text("""
            UPDATE response_branches SET status='superseded',updated_at=:now
            WHERE owner_id=:owner AND session_id=:session AND id<>:selected AND status='selected'
            """), {"owner": owner, "session": session_id, "selected": branch_id, "now": now})
            connection.execute(text("""
            INSERT INTO conversation_branch_heads(owner_id,session_id,selected_branch_id,revision,updated_at)
            VALUES(:owner,:session,:branch,1,:now)
            ON CONFLICT(owner_id,session_id) DO UPDATE SET
                selected_branch_id=excluded.selected_branch_id,
                revision=conversation_branch_heads.revision+1,
                updated_at=excluded.updated_at
            """), {"owner": owner, "session": session_id, "branch": branch_id, "now": now})
        branch = {"id": branch_id, "owner_id": owner, "session_id": session_id,
                  "parent_branch_id": parent_branch_id, "trigger_event_id": event["id"],
                  "relation": relation, "status": "selected" if selecting else "control", "created_at": now, "updated_at": now}
        self.append_event(connection, owner, session_id, "branch.updated",
                          {"branchId": branch_id, "relation": relation,
                           "status": branch["status"], "selected": selecting})
        return event, branch, True

    def accept_cancel_message(self, connection, owner: str, session_id: str, client_message_id: str,
                              message: str, mode: str, reply_to_generation_id: str | None = None) -> dict:
        """Persist an explicit stop message and request cancellation of its target."""
        event, branch, is_new = self.accept_message(connection, owner, session_id, client_message_id,
                                                    message, mode, reply_to_generation_id)
        target_id = reply_to_generation_id or event["payload"].get("replyToGenerationId")
        if target_id:
            target = connection.execute(text("""
                SELECT id,status FROM generation_records
                WHERE id=:id AND owner_id=:owner AND session_id=:session
            """), {"id": target_id, "owner": owner, "session": session_id}).first()
            if not target:
                problem("not_found", "This response is not available to cancel.", 404)
        else:
            parent_branch_id = branch.get("parent_branch_id")
            target = connection.execute(text("""
                SELECT id,status FROM generation_records
                WHERE owner_id=:owner AND session_id=:session
                    AND status IN ('queued','preparing','streaming','finalizing','cancel_requested')
                    AND (:branch IS NULL OR branch_id=:branch)
                ORDER BY created_at DESC,id DESC LIMIT 1
            """), {"owner": owner, "session": session_id, "branch": parent_branch_id}).first()
            if not target and parent_branch_id is not None:
                target = connection.execute(text("""
                    SELECT id,status FROM generation_records WHERE owner_id=:owner AND session_id=:session
                        AND status IN ('queued','preparing','streaming','finalizing','cancel_requested')
                    ORDER BY created_at DESC,id DESC LIMIT 1
                """), {"owner": owner, "session": session_id}).first()
        target_id = target[0] if target else None
        target_status = target[1] if target else "none"
        if is_new:
            self.append_event(connection, owner, session_id, "generation.cancel_requested",
                              {"generationId": target_id, "reason": "explicit_stop_message",
                               "messageId": client_message_id})
        if target_id and target_status not in {"completed", "failed", "cancelled", "interrupted"}:
            changed = connection.execute(text("""
                UPDATE generation_records SET cancellation_requested=1,
                    status=CASE WHEN status='queued' THEN 'cancelled'
                                WHEN status IN ('preparing','streaming','finalizing') THEN 'cancel_requested'
                                ELSE status END,updated_at=:now
                WHERE id=:id AND owner_id=:owner AND session_id=:session
                    AND status IN ('queued','preparing','streaming','finalizing')
            """), {"now": time.time(), "id": target_id, "owner": owner, "session": session_id})
            if changed.rowcount == 1:
                if is_new:
                    self.append_generation_event(connection, target_id, "generation.cancel_requested",
                                                 {"reason": "explicit_stop_message"})
                if target_status == "queued":
                    self.append_generation_event(connection, target_id, "generation.cancelled",
                                                 {"code": "CANCELLED", "reason": "explicit_stop_message"})
                    try:
                        from .journey_service import JourneyService
                        JourneyService(self.store, None).finish_stream_turn(owner, session_id, target_id,
                                                                            "cancelled", "CANCELLED", connection)
                    except Exception:
                        pass
                    target_status = "cancelled"
                else:
                    target_status = "cancel_requested"
            else:
                target_status = connection.execute(text("SELECT status FROM generation_records WHERE id=:id"),
                                                   {"id": target_id}).scalar_one()
        head = connection.execute(text("""
            SELECT revision,selected_branch_id FROM conversation_branch_heads
            WHERE owner_id=:owner AND session_id=:session
        """), {"owner": owner, "session": session_id}).mappings().first()
        return {"event": event, "branch": branch, "targetGenerationId": target_id,
                "targetStatus": target_status, "branchRevision": int(head["revision"]) if head else 0,
                "selectedBranchId": head["selected_branch_id"] if head else None}

    def append_cancel_event(self, connection, owner: str, session_id: str,
                            generation_id: str, reason: str = "user_cancelled") -> dict:
        event = self.append_event(connection, owner, session_id, "generation.cancel_requested",
                                  {"generationId": generation_id, "reason": reason})
        self.append_generation_event(connection, generation_id, "generation.cancel_requested",
                                     {"reason": reason})
        return event

    @staticmethod
    def append_generation_event(connection, generation_id: str, event_type: str, data: dict) -> None:
        row = connection.execute(text("""
            UPDATE generation_records SET sequence=sequence+1
            WHERE id=:id RETURNING sequence
        """), {"id": generation_id}).first()
        if row is None:
            return
        connection.execute(text("""
            INSERT INTO generation_events(generation_id,sequence,event_type,data_json,created_at)
            VALUES(:id,:sequence,:type,:data,:now)
        """), {"id": generation_id, "sequence": int(row[0]), "type": event_type,
               "data": _json(data), "now": time.time()})

    def context_snapshot(self, owner: str, generation_id: str) -> dict | None:
        with self.store.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT snapshot_json FROM generation_context_snapshots
                WHERE generation_id=:generation
            """), {"generation": generation_id}).first()
        return json.loads(row[0]) if row else None

    def is_selected(self, connection, owner: str, session_id: str, branch_id: str) -> bool:
        return bool(connection.execute(text("""
            SELECT 1 FROM conversation_branch_heads
            WHERE owner_id=:owner AND session_id=:session AND selected_branch_id=:branch
        """), {"owner": owner, "session": session_id, "branch": branch_id}).first())

    def list_branches(self, owner: str, session_id: str) -> dict:
        with self.store.engine.connect() as connection:
            head = connection.execute(text("""
                SELECT selected_branch_id,revision FROM conversation_branch_heads
                WHERE owner_id=:owner AND session_id=:session
            """), {"owner": owner, "session": session_id}).mappings().first()
            rows = connection.execute(text("""
                SELECT b.id,b.parent_branch_id,b.trigger_event_id,b.relation,b.status,b.created_at,
                       e.sequence AS conversation_seq,e.client_message_id,e.payload_json,
                       g.id AS generation_id,g.status AS generation_status,g.sequence AS generation_sequence,
                       g.context_revision,g.partial_output,g.result,g.error_code,g.created_at AS generation_created
                FROM response_branches b
                JOIN conversation_events e ON e.id=b.trigger_event_id
                LEFT JOIN generation_records g ON g.branch_id=b.id
                WHERE b.owner_id=:owner AND b.session_id=:session
                ORDER BY e.sequence ASC,g.created_at ASC
            """), {"owner": owner, "session": session_id}).mappings().all()
        branches: dict[str, dict] = {}
        for row in rows:
            item = branches.setdefault(row["id"], {
                "id": row["id"], "parentBranchId": row["parent_branch_id"],
                "triggerMessageId": row["client_message_id"], "conversationSeq": row["conversation_seq"],
                "message": json.loads(row["payload_json"]).get("text", ""),
                "relation": row["relation"], "status": row["status"],
                "createdAt": row["created_at"], "selected": bool(head and head["selected_branch_id"] == row["id"]),
                "generations": [],
            })
            if row["generation_id"]:
                item["generations"].append({
                    "id": row["generation_id"], "status": row["generation_status"],
                    "sequence": row["generation_sequence"], "contextRevision": row["context_revision"],
                    "partialOutput": row["partial_output"], "result": json.loads(row["result"]) if row["result"] else None,
                    "errorCode": row["error_code"], "createdAt": row["generation_created"],
                })
        return {"revision": int(head["revision"]) if head else 0,
                "selectedBranchId": head["selected_branch_id"] if head else None,
                "branches": list(branches.values())}

    def select_branch(self, owner: str, session_id: str, branch_id: str, expected_revision: int) -> dict:
        now = time.time()
        with self.store.transaction() as connection:
            head = connection.execute(text("""
                SELECT revision FROM conversation_branch_heads
                WHERE owner_id=:owner AND session_id=:session
            """), {"owner": owner, "session": session_id}).first()
            if not head or int(head[0]) != expected_revision:
                problem("branch_revision_conflict", "The selected response changed. Refresh the conversation and try again.", 409)
            branch = connection.execute(text("""
                SELECT id FROM response_branches
                WHERE id=:branch AND owner_id=:owner AND session_id=:session AND relation<>'cancel'
            """), {"branch": branch_id, "owner": owner, "session": session_id}).first()
            if not branch:
                problem("not_found", "This response branch is not available.", 404)
            updated = connection.execute(text("""
                UPDATE conversation_branch_heads SET selected_branch_id=:branch,
                    revision=revision+1,updated_at=:now WHERE owner_id=:owner AND session_id=:session
                    AND revision=:expected
            """), {"branch": branch_id, "now": now, "owner": owner, "session": session_id,
                   "expected": expected_revision})
            if updated.rowcount != 1:
                problem("branch_revision_conflict", "The selected response changed. Refresh the conversation and try again.", 409)
            connection.execute(text("""
                UPDATE response_branches SET status=CASE WHEN id=:branch THEN 'selected' ELSE 'superseded' END,
                    updated_at=:now WHERE owner_id=:owner AND session_id=:session
            """), {"branch": branch_id, "now": now, "owner": owner, "session": session_id})
            self.append_event(connection, owner, session_id, "branch.updated",
                              {"branchId": branch_id, "selected": True,
                               "selectionSource": "user"})
        return self.list_branches(owner, session_id)
