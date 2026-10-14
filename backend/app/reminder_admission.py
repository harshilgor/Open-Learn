"""Freeze interpreted chat schedules so request retries do not recompile intent."""
import hashlib
import json
from sqlalchemy import text
from .identity import fail, assert_owner_active
from .workflow_store import WorkflowStore, encoded


def identity(body, owner, key):
    return ('reminder_chat_'+hashlib.sha256(encoded([owner,key]).encode()).hexdigest()[:32],
            hashlib.sha256(encoded(body.model_dump()).encode()).hexdigest())


def cached(store, owner, body, key):
    identifier,digest=identity(body,owner,key)
    with store.engine.connect() as conn:
        assert_owner_active(conn,owner)
        row=conn.execute(text("SELECT payload FROM practice_records WHERE id=:id AND owner_id=:owner AND kind='reminder_chat_admission'"),{'id':identifier,'owner':owner}).scalar_one_or_none()
    if not row:return None
    value=json.loads(row)
    if value['requestHash']!=digest:fail('idempotency_conflict','This scheduling request key has different content.',409)
    return value['command']


def freeze(store, owner, body, key, command):
    identifier,digest=identity(body,owner,key)
    with store.transaction() as conn:
        assert_owner_active(conn,owner)
        from .buddy_service import BuddyService
        BuddyService(store).ensure(conn,owner)
        conn.execute(text('UPDATE buddy_profiles SET payload=payload WHERE owner_id=:owner'),{'owner':owner})
        row=conn.execute(text("SELECT payload FROM practice_records WHERE id=:id AND owner_id=:owner AND kind='reminder_chat_admission'"),{'id':identifier,'owner':owner}).scalar_one_or_none()
        if row:
            value=json.loads(row)
            if value['requestHash']!=digest:fail('idempotency_conflict','This scheduling request key has different content.',409)
            return value['command']
        WorkflowStore(store).put(conn,owner,'reminder_chat_admission',{'id':identifier,'requestHash':digest,'command':command},body.sessionId)
        return command
