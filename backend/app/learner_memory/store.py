"""Owner-scoped SQL access for learner memory tables (SQLite and PostgreSQL).

Every function takes the caller's connection so writes share the caller's
transaction. Statements are immutable; status changes bump ``revision``.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from sqlalchemy import text

from . import policy

FACT_COLUMNS = ("owner_id,id,kind,statement,subject_key,course_id,concept_ids,event_date,origin,status,sensitive,"
                "confidence,importance,learned_at,valid_from,invalid_at,superseded_by,basis,last_used_at,use_count,"
                "confirmed_at,stability_days,needs_review,policy_version,revision")


def fact_id_for_derived(owner: str, derived_id: str) -> str:
    """Deterministic fact ID for a memory_derived preference (matches migration 0086)."""
    return "fact_" + hashlib.sha256(f"{owner}:{derived_id}".encode()).hexdigest()[:32]


def normalized(statement: str) -> str:
    return re.sub(r"\s+", " ", statement.strip().lower())


def preference_subject_key(statement: str) -> str:
    # One colon only, so the key satisfies the validator pattern (§7.4).
    return "preference:freeform-" + hashlib.sha256(normalized(statement).encode()).hexdigest()[:8]


def initial_stability(importance: float) -> float:
    return 30 * (1 + 2 * importance)


def _decode(row) -> dict:
    fact = dict(row)
    fact["concept_ids"] = json.loads(fact.get("concept_ids") or "[]")
    fact["basis"] = json.loads(fact.get("basis") or "[]")
    fact["sensitive"] = bool(fact["sensitive"])
    fact["needs_review"] = bool(fact["needs_review"])
    return fact


def get_fact(conn, owner, fact_id):
    row = conn.execute(text(f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE owner_id=:owner AND id=:id"),
                       {"owner": owner, "id": fact_id}).mappings().first()
    return _decode(row) if row else None


def _active_same_subject(conn, owner, subject_key, course_id):
    row = conn.execute(text(f"""SELECT {FACT_COLUMNS} FROM memory_facts
        WHERE owner_id=:owner AND subject_key=:subject AND COALESCE(course_id,'')=:course AND status='active'"""),
        {"owner": owner, "subject": subject_key, "course": course_id or ""}).mappings().first()
    return _decode(row) if row else None


def record_explicit_preference(conn, owner, *, derived_id, statement, course_id, basis, now=None):
    """Mirror an explicit memory_derived preference as an active user_stated fact.

    Idempotent per derived row. Re-stating an existing active preference in
    the same scope confirms it instead of inserting a duplicate.
    """
    now = now or time.time()
    fact_id = fact_id_for_derived(owner, derived_id)
    if get_fact(conn, owner, fact_id):
        return fact_id
    refs = [{"type": "memory_source", "sourceId": ref.get("sourceId"), "revision": ref.get("revision"), "derivedId": derived_id}
            for ref in basis if isinstance(ref, dict) and ref.get("sourceId")]
    subject_key = preference_subject_key(statement)
    existing = _active_same_subject(conn, owner, subject_key, course_id)
    if existing and normalized(existing["statement"]) == normalized(statement):
        merged = existing["basis"] + [ref for ref in refs if ref not in existing["basis"]]
        conn.execute(text("""UPDATE memory_facts SET basis=:basis,confirmed_at=:now,stability_days=:stability,revision=revision+1
            WHERE owner_id=:owner AND id=:id"""),
            {"basis": json.dumps(merged), "now": now, "stability": policy.CONFIRMED_STABILITY_DAYS, "owner": owner, "id": existing["id"]})
        return existing["id"]
    if existing:
        # Same subject key, different text (a hash collision): never supersede
        # an explicit statement silently; keep the earlier one active.
        status = "tentative"
    else:
        status = "active"
    conn.execute(text(f"""INSERT INTO memory_facts({FACT_COLUMNS}) VALUES(:owner,:id,'preference',:statement,:subject,:course,'[]',NULL,
        'user_stated',:status,:false,1.0,:importance,:now,:now,NULL,NULL,:basis,NULL,0,:now,:stability,:false,:policy,1)"""),
        {"owner": owner, "id": fact_id, "statement": statement.strip()[:2000], "subject": subject_key, "course": course_id,
         "status": status, "false": False, "importance": policy.DEFAULT_IMPORTANCE["preference"], "now": now,
         "basis": json.dumps(refs), "stability": policy.CONFIRMED_STABILITY_DAYS, "policy": policy.MEMORY_POLICY_VERSION})
    return fact_id


def _facts_referencing(conn, owner, key, value):
    # LIKE narrows the scan to plausible rows; the JSON check is authoritative.
    pattern = "%" + json.dumps(value)[1:-1].replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.execute(text(f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE owner_id=:owner AND basis LIKE :pattern ESCAPE '\\'"),
                        {"owner": owner, "pattern": pattern}).mappings().all()
    return [fact for fact in map(_decode, rows) if any(ref.get(key) == value for ref in fact["basis"])]


def delete_fact(conn, owner, fact_id):
    """Hard delete a fact and its embeddings (§9.1)."""
    conn.execute(text("DELETE FROM memory_embeddings WHERE owner_id=:owner AND item_type='fact' AND item_id=:id"), {"owner": owner, "id": fact_id})
    conn.execute(text("DELETE FROM memory_facts WHERE owner_id=:owner AND id=:id"), {"owner": owner, "id": fact_id})


def _drop_basis(conn, owner, facts, key, value, *, on_empty):
    for fact in facts:
        remaining = [ref for ref in fact["basis"] if ref.get(key) != value]
        if any(ref.get("type") == "memory_source" for ref in remaining) or any(ref.get("type") == "turn" for ref in remaining):
            conn.execute(text("UPDATE memory_facts SET basis=:basis,revision=revision+1 WHERE owner_id=:owner AND id=:id"),
                         {"basis": json.dumps(remaining), "owner": owner, "id": fact["id"]})
        else:
            on_empty(fact)


def forget_derived(conn, owner, derived_id):
    """The learner dismissed a saved preference: remove what only it supported."""
    _drop_basis(conn, owner, _facts_referencing(conn, owner, "derivedId", derived_id), "derivedId", derived_id,
                on_empty=lambda fact: delete_fact(conn, owner, fact["id"]))


def source_changed(conn, owner, source_id, *, removed, now=None):
    """A basis source was removed (learner delete) or revised (no longer exact)."""
    now = now or time.time()

    def unsupported(fact):
        if removed:
            delete_fact(conn, owner, fact["id"])
        elif fact["status"] in {"active", "tentative"}:
            conn.execute(text("""UPDATE memory_facts SET status='archived',invalid_at=:now,revision=revision+1
                WHERE owner_id=:owner AND id=:id"""), {"now": now, "owner": owner, "id": fact["id"]})
    _drop_basis(conn, owner, _facts_referencing(conn, owner, "sourceId", source_id), "sourceId", source_id, on_empty=unsupported)


def list_facts(conn, owner, *, status=None, kind=None, course_id=None, limit=200):
    clauses, params = ["owner_id=:owner"], {"owner": owner, "limit": limit}
    # Shadow facts exist only for evaluation and are never shown (§7.4).
    clauses.append("status<>'shadow'")
    if status:
        clauses.append("status=:status"); params["status"] = status
    if kind:
        clauses.append("kind=:kind"); params["kind"] = kind
    if course_id:
        clauses.append("course_id=:course"); params["course"] = course_id
    rows = conn.execute(text(f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE {' AND '.join(clauses)} "
                             "ORDER BY learned_at DESC, id LIMIT :limit"), params).mappings().all()
    return [_decode(row) for row in rows]


def fact_history(conn, owner, fact_id, *, limit=50):
    """Supersession chain, oldest first, containing ``fact_id``."""
    current = get_fact(conn, owner, fact_id)
    if not current or current["status"] == "shadow":
        return None
    chain, seen = [current], {fact_id}
    head = current
    while len(chain) < limit:
        row = conn.execute(text(f"SELECT {FACT_COLUMNS} FROM memory_facts WHERE owner_id=:owner AND superseded_by=:id ORDER BY valid_from DESC, id LIMIT 1"),
                           {"owner": owner, "id": head["id"]}).mappings().first()
        if not row or row["id"] in seen:
            break
        head = _decode(row); seen.add(head["id"]); chain.insert(0, head)
    tail = current
    while len(chain) < limit and tail.get("superseded_by") and tail["superseded_by"] not in seen:
        nxt = get_fact(conn, owner, tail["superseded_by"])
        if not nxt:
            break
        tail = nxt; seen.add(tail["id"]); chain.append(tail)
    return chain


def active_preferences(conn, owner, course_id):
    """Active, non-sensitive preferences for this course or global."""
    rows = conn.execute(text(f"""SELECT {FACT_COLUMNS} FROM memory_facts
        WHERE owner_id=:owner AND kind='preference' AND status='active' AND sensitive=:false
          AND (course_id IS NULL OR course_id=:course)"""),
        {"owner": owner, "course": course_id or "", "false": False}).mappings().all()
    return [_decode(row) for row in rows]


def list_episodes(conn, owner, *, course_id=None, limit=100):
    params = {"owner": owner, "limit": limit}
    sql = "SELECT * FROM memory_episodes WHERE owner_id=:owner AND status='active'"
    if course_id:
        sql += " AND course_id=:course"; params["course"] = course_id
    rows = conn.execute(text(sql + " ORDER BY period_end DESC, id LIMIT :limit"), params).mappings().all()
    return [{**dict(row), "turn_range": json.loads(row["turn_range"]), "topics": json.loads(row["topics"]),
             "basis": json.loads(row["basis"])} for row in rows]


def delete_episode(conn, owner, episode_id):
    conn.execute(text("DELETE FROM memory_embeddings WHERE owner_id=:owner AND item_type='episode' AND item_id=:id"), {"owner": owner, "id": episode_id})
    return conn.execute(text("DELETE FROM memory_episodes WHERE owner_id=:owner AND id=:id"), {"owner": owner, "id": episode_id}).rowcount


def get_settings(conn, owner):
    row = conn.execute(text("SELECT learning_enabled,revision,updated_at FROM memory_settings WHERE owner_id=:owner"),
                       {"owner": owner}).mappings().first()
    if not row:
        return {"learning_enabled": policy.DEFAULT_LEARNING_ENABLED, "revision": 0, "updated_at": None}
    return {"learning_enabled": bool(row["learning_enabled"]), "revision": row["revision"], "updated_at": row["updated_at"]}


def put_settings(conn, owner, *, learning_enabled, expected_revision, now=None):
    """Optimistic write; returns the new settings or None on a revision conflict."""
    now = now or time.time()
    values = {"owner": owner, "enabled": learning_enabled, "now": now, "expected": expected_revision}
    if expected_revision == 0:
        inserted = conn.execute(text("""INSERT INTO memory_settings(owner_id,learning_enabled,revision,updated_at)
            VALUES(:owner,:enabled,1,:now) ON CONFLICT(owner_id) DO NOTHING"""), values).rowcount
        if not inserted:
            return None
    else:
        changed = conn.execute(text("""UPDATE memory_settings SET learning_enabled=:enabled,revision=revision+1,updated_at=:now
            WHERE owner_id=:owner AND revision=:expected"""), values).rowcount
        if not changed:
            return None
    return get_settings(conn, owner)
