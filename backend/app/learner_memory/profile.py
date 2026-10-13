"""Deterministic core profile (spec §9.3 step 6): no model, byte-stable.

The profile is the ordered list of the learner's most durable facts. It is
stored in ``context_records`` and rewritten only when its bytes change, so
the provider's cached prompt prefix stays reusable. The read path renders
it from the live fact rows, keeping only IDs that are still active, so a
deleted, archived or superseded fact leaves the prompt immediately, even
before the next rebuild.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text

from ..context_engine import estimate_tokens
from . import policy, store

logger = logging.getLogger(__name__)

PROFILE_KIND = "learner_core_profile"


def record_id(owner: str) -> str:
    return "memprofile_" + hashlib.sha256(str(owner).encode()).hexdigest()[:40]


def _score(fact, now):
    return policy.retention(fact, now) * (0.7 + 0.3 * fact["importance"]) + policy.ORIGIN_BONUS.get(fact["origin"], 0.0)


def select(facts, now):
    """Active facts with retention >= 0.3, in profile order, within the token cap.

    A sensitive fact is included only when the learner enabled it (§2 rule 6).
    """
    today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    order = {kind: index for index, kind in enumerate(policy.PROFILE_KIND_ORDER)}
    eligible = []
    for fact in facts:
        if fact["status"] != "active" or (fact.get("sensitive") and not fact.get("sensitive_enabled")) or fact["kind"] not in order:
            continue
        if fact["kind"] == "deadline" and (not fact.get("event_date") or fact["event_date"][:10] < today):
            continue  # only upcoming deadlines are profile material
        if policy.retention(fact, now) < policy.PROFILE_MIN_RETENTION:
            continue
        eligible.append(fact)

    def key(fact):
        # Soonest deadline first; every other kind by score. The ID breaks ties.
        rank = fact["event_date"][:10] if fact["kind"] == "deadline" else ""
        return (order[fact["kind"]], rank, -round(_score(fact, now), 6), fact["id"])

    chosen, used = [], 0
    for fact in sorted(eligible, key=key):
        cost = estimate_tokens(line(fact)) + 1
        if used + cost > policy.PROFILE_MAX_TOKENS:
            break
        chosen.append(fact)
        used += cost
    return chosen


def line(fact) -> str:
    return f"- [{fact['kind'].replace('_', ' ')}] {fact['statement']}"


def build(facts, now) -> dict:
    chosen = select(facts, now)
    return {"policyVersion": policy.MEMORY_POLICY_VERSION, "factIds": [fact["id"] for fact in chosen],
            "text": "\n".join(line(fact) for fact in chosen)}


def _encode(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stored(conn, owner):
    raw = conn.execute(text("SELECT payload FROM context_records WHERE id=:id AND owner_id=:owner AND kind=:kind"),
                       {"id": record_id(owner), "owner": owner, "kind": PROFILE_KIND}).scalar_one_or_none()
    return json.loads(raw) if raw else None


def rebuild(conn, owner, *, now=None) -> bool:
    """Rebuild inside the caller's transaction; returns True when the stored bytes changed."""
    now = now or time.time()
    payload = build(store.facts_with_status(conn, owner, {"active"}), now)
    encoded = _encode(payload)
    identifier = record_id(owner)
    # Rows copied in by an account import carry remapped IDs; one profile per owner.
    conn.execute(text("DELETE FROM context_records WHERE owner_id=:owner AND kind=:kind AND id<>:id"),
                 {"owner": owner, "kind": PROFILE_KIND, "id": identifier})
    current = conn.execute(text("SELECT payload FROM context_records WHERE id=:id AND owner_id=:owner"),
                           {"id": identifier, "owner": owner}).scalar_one_or_none()
    if current == encoded:
        return False
    if current is None:
        conn.execute(text("""INSERT INTO context_records(id,owner_id,kind,session_id,sequence,payload)
            VALUES(:id,:owner,:kind,NULL,1,:payload)"""), {"id": identifier, "owner": owner, "kind": PROFILE_KIND, "payload": encoded})
    else:
        conn.execute(text("UPDATE context_records SET payload=:payload,sequence=sequence+1 WHERE id=:id AND owner_id=:owner"),
                     {"payload": encoded, "id": identifier, "owner": owner})
    from ..cache import invalidate, owner_scope
    invalidate("learner_profile", owner_scope(owner))  # flushed after the caller's commit
    # The read path caches the profile per process behind the memory version.
    store.bump_version(conn, owner, now=now)
    return True


def clear(conn, owner):
    """Remove the stored profile (forget everything); the next rebuild starts empty."""
    conn.execute(text("DELETE FROM context_records WHERE owner_id=:owner AND kind=:kind"), {"owner": owner, "kind": PROFILE_KIND})
    from ..cache import invalidate, owner_scope
    invalidate("learner_profile", owner_scope(owner))


def rebuild_if_enabled(conn, owner, *, now=None) -> bool:
    """For write paths outside consolidation; never fails the caller's write."""
    if not policy.consolidation_enabled():
        return False
    try:
        with conn.begin_nested():
            return rebuild(conn, owner, now=now)
    except Exception as exc:
        logger.warning("learner profile rebuild failed (%s)", type(exc).__name__)
        return False


def load(store_, owner):
    """The stored profile payload, through the Redis ``learner_profile`` namespace, or None."""
    from ..cache import get_or_load, json_codec, owner_scope

    def loader():
        with store_.engine.connect() as conn:
            return stored(conn, owner)
    return get_or_load("learner_profile", owner_scope(owner), {"profile": 1}, loader,
                       ttl_seconds=policy.PROFILE_CACHE_TTL_SECONDS, **json_codec())
