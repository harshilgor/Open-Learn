"""Durable idempotency receipts for generation commands that need a mode choice."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from .material_service import problem
from .mode_transition_service import ModeTransitionService


def _receipt_id(owner: str, session_id: str, key: str) -> str:
    digest = hashlib.sha256(f"{owner}\0{session_id}\0{key}".encode()).hexdigest()
    return f"mode_cmd_{digest}"


def _request_hash(command: dict) -> str:
    # A dismissed mode choice legitimately resumes with the same message ID
    # after the Journey revision changes. Exclude only those continuation fields.
    identity = {key: value for key, value in command.items()
                if key not in {"expectedRevision", "classificationBypassId"}}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def get_mode_choice(store, owner: str, session_id: str, key: str, command: dict) -> dict | None:
    receipt_id = _receipt_id(owner, session_id, key)
    with store.engine.connect() as connection:
        row = connection.execute(text("""
            SELECT payload FROM practice_records
            WHERE id=:id AND owner_id=:owner AND parent_id=:session
              AND kind='generation_mode_choice'
        """), {"id": receipt_id, "owner": owner, "session": session_id}).first()
    if not row:
        return None
    payload = json.loads(row[0])
    if payload.get("requestHash") != _request_hash(command):
        problem("idempotency_conflict", "This request ID was already used for another message.", 409)
    return payload


def save_mode_choice(store, owner: str, session_id: str, key: str, command: dict,
                     decision: str, suggestion: dict) -> dict:
    receipt_id = _receipt_id(owner, session_id, key)
    payload = {"requestHash": _request_hash(command), "decision": decision,
               "suggestion": suggestion}
    with store.transaction() as connection:
        connection.execute(text("""
            INSERT INTO practice_records(id,owner_id,kind,parent_id,revision,payload)
            VALUES(:id,:owner,'generation_mode_choice',:session,1,:payload)
            ON CONFLICT(id) DO NOTHING
        """), {"id": receipt_id, "owner": owner, "session": session_id,
               "payload": json.dumps(payload, ensure_ascii=False)})
        row = connection.execute(text("""
            SELECT payload FROM practice_records
            WHERE id=:id AND owner_id=:owner AND parent_id=:session
              AND kind='generation_mode_choice'
        """), {"id": receipt_id, "owner": owner, "session": session_id}).first()
    if not row:
        raise RuntimeError("Mode choice receipt could not be persisted")
    stored = json.loads(row[0])
    if stored.get("requestHash") != payload["requestHash"]:
        problem("idempotency_conflict", "This request ID was already used for another message.", 409)
    if stored.get("suggestion", {}).get("id") != suggestion.get("id"):
        # Concurrent duplicate classification may have created a losing offer.
        ModeTransitionService(store).supersede_suggestion(owner, session_id, suggestion.get("id"))
    return stored


def clear_mode_choice(store, owner: str, session_id: str, key: str) -> None:
    with store.transaction() as connection:
        connection.execute(text("""
            DELETE FROM practice_records WHERE id=:id AND owner_id=:owner
              AND parent_id=:session AND kind='generation_mode_choice'
        """), {"id": _receipt_id(owner, session_id, key), "owner": owner,
               "session": session_id})


def clear_mode_choice_by_suggestion(store, owner: str, session_id: str, suggestion_id: str) -> None:
    with store.engine.connect() as connection:
        rows = connection.execute(text("""SELECT id,payload FROM practice_records
            WHERE owner_id=:owner AND parent_id=:session AND kind='generation_mode_choice'"""),
            {"owner": owner, "session": session_id}).fetchall()
    receipt_ids = []
    for row in rows:
        try:
            payload = json.loads(row[1])
        except (TypeError, ValueError):
            continue
        if (payload.get("suggestion") or {}).get("id") == suggestion_id:
            receipt_ids.append(row[0])
    if receipt_ids:
        with store.transaction() as connection:
            for receipt_id in receipt_ids:
                connection.execute(text("""DELETE FROM practice_records
                    WHERE id=:id AND owner_id=:owner AND parent_id=:session
                      AND kind='generation_mode_choice'"""),
                    {"id": receipt_id, "owner": owner, "session": session_id})
