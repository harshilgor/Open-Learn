"""Consolidation and forgetting (spec §9.3), run per owner by the memory_consolidate job.

Store everything, retrieve little, demote rather than delete. Every step is
idempotent and runs in bounded transactions (at most CONSOLIDATION_BATCH rows).
Hard deletion here is limited to unvalidated inferences past their TTL and
shadow facts past retention; a fact the learner stated or confirmed is never
deleted for disuse, only archived (§9.1).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

from . import episodes, policy, profile, store

logger = logging.getLogger(__name__)

CHANGES_KIND = "memory_changes"
KIND_EPISODE = "memory_episode"
LEARNER_ORIGINS = {"user_stated", "user_confirmed"}


def _chunks(items, size=policy.CONSOLIDATION_BATCH):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _deadline_passed(fact, now) -> bool:
    if fact["kind"] != "deadline" or not fact.get("event_date"):
        return False
    try:
        raw = fact["event_date"]
        when = datetime.fromisoformat(raw.replace("Z", "+00:00")) if "T" in raw else datetime.fromisoformat(raw + "T23:59:59")
    except ValueError:
        return False
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return now > when.timestamp() + policy.DEADLINE_GRACE_DAYS * policy.DAY_SECONDS


def _terms(statement: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", store.normalized(statement)))


def _jaccard(left: frozenset, right: frozenset) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


# --- Steps -----------------------------------------------------------------------

def expire_tentative(store_, owner, now, counts):
    """Step 1: drop stale unvalidated inferences; promote reinforced ones."""
    with store_.engine.connect() as conn:
        tentative = store.facts_with_status(conn, owner, {"tentative"})
    cutoff = now - policy.TENTATIVE_TTL_DAYS * policy.DAY_SECONDS
    expired = [fact for fact in tentative if fact["learned_at"] < cutoff and not fact["last_used_at"] and not fact["confirmed_at"]]
    expired_ids = {fact["id"] for fact in expired}
    promote = [fact for fact in tentative if fact["id"] not in expired_ids
               and (fact["confirmed_at"] or fact["use_count"] >= policy.TENTATIVE_PROMOTE_USES)]
    for batch in _chunks(expired):
        with store_.transaction() as conn:
            for fact in batch:
                if fact["origin"] in LEARNER_ORIGINS:
                    # The learner's own words are never auto-deleted (§9.1); demote.
                    if store.set_fact_status(conn, owner, fact["id"], "archived", expected_status="tentative"):
                        counts["archived"] += 1
                else:
                    store.delete_fact(conn, owner, fact["id"])
                    counts["expired"] += 1
    for batch in _chunks(promote):
        with store_.transaction() as conn:
            for fact in batch:
                # One active fact per subject and scope: an active one keeps the slot.
                if store._active_same_subject(conn, owner, fact["subject_key"], fact["course_id"]):
                    continue
                if store.set_fact_status(conn, owner, fact["id"], "active", expected_status="tentative"):
                    counts["promoted"] += 1


def archive_weak(store_, owner, now, counts):
    """Step 2: archive faded facts, past deadlines and year-old episodes (kept, not retrieved)."""
    with store_.engine.connect() as conn:
        active = store.facts_with_status(conn, owner, {"active"})
    weak = [fact for fact in active if _deadline_passed(fact, now) or policy.retention(fact, now) < policy.ARCHIVE_THRESHOLD]
    for batch in _chunks(weak):
        with store_.transaction() as conn:
            for fact in batch:
                if store.set_fact_status(conn, owner, fact["id"], "archived", expected_status="active"):
                    counts["archived"] += 1
    before = now - policy.EPISODE_ARCHIVE_DAYS * policy.DAY_SECONDS
    while True:
        with store_.transaction() as conn:
            archived = store.archive_old_episodes(conn, owner, before)
        counts["episodesArchived"] += len(archived)
        if len(archived) < policy.CONSOLIDATION_BATCH:
            break


def duplicate_pairs(facts):
    """(kept, duplicate) pairs within kind + scope; the older fact is kept (§9.3 step 3).

    Lexical only (equal normalized text, or token Jaccard >= DEDUPE_JACCARD)
    until the embeddings decision (§13) makes cosine similarity available.
    """
    groups = {}
    for fact in sorted(facts, key=lambda item: (item["learned_at"], item["id"])):
        groups.setdefault((fact["kind"], fact["course_id"] or "", bool(fact["sensitive"])), []).append(fact)
    pairs = []
    for members in groups.values():
        kept = []
        for fact in members:
            terms, text_ = _terms(fact["statement"]), store.normalized(fact["statement"])
            target = None
            for candidate, candidate_terms, candidate_text in kept:
                if fact.get("event_date") and candidate.get("event_date") and fact["event_date"] != candidate["event_date"]:
                    continue  # different dates are different facts
                if text_ == candidate_text:
                    target = candidate
                    break
                small, large = sorted((len(terms), len(candidate_terms)))
                if large and small / large >= policy.DEDUPE_JACCARD and _jaccard(terms, candidate_terms) >= policy.DEDUPE_JACCARD:
                    target = candidate
                    break
            if target is None:
                kept.append((fact, terms, text_))
            else:
                pairs.append((target["id"], fact["id"]))
    return pairs


def dedupe(store_, owner, now, counts):
    with store_.engine.connect() as conn:
        pairs = duplicate_pairs(store.facts_with_status(conn, owner, {"active"}))
    for batch in _chunks(pairs):
        with store_.transaction() as conn:
            for kept_id, duplicate_id in batch:
                kept, duplicate = store.get_fact(conn, owner, kept_id), store.get_fact(conn, owner, duplicate_id)
                if not kept or not duplicate or kept["status"] != "active" or duplicate["status"] != "active":
                    continue
                store.merge_into(conn, owner, kept, duplicate, now=now)
                counts["merged"] += 1


def review_conflicts(store_, owner, now, counts):
    """Step 4: same-rank, same-subject disagreements within 24 h go to the learner.

    The one-active-fact index means an update already superseded its
    predecessor at write time; what remains is a low-confidence (tentative)
    restatement next to the active fact. Flags are recomputed each run.
    """
    with store_.engine.connect() as conn:
        facts = store.facts_with_status(conn, owner, {"active", "tentative"})
    groups = {}
    for fact in facts:
        groups.setdefault((fact["subject_key"], fact["course_id"] or ""), []).append(fact)
    flagged = set()
    for members in groups.values():
        active = next((fact for fact in members if fact["status"] == "active"), None)
        if not active:
            continue
        for other in members:
            if (other["status"] == "tentative"
                    and policy.ORIGIN_RANK.get(other["origin"], 0) == policy.ORIGIN_RANK.get(active["origin"], 0)
                    and abs(other["valid_from"] - active["valid_from"]) <= policy.CONFLICT_REVIEW_SECONDS
                    and store.normalized(other["statement"]) != store.normalized(active["statement"])):
                flagged.update({active["id"], other["id"]})
    cleared = {fact["id"] for fact in facts if fact["needs_review"]} - flagged
    with store_.transaction() as conn:
        counts["needsReview"] += store.set_needs_review(conn, owner, sorted(flagged), True)
        store.set_needs_review(conn, owner, sorted(cleared), False)


def idle_sessions(store_, owner, now):
    """Sessions idle >= EPISODE_IDLE_MINUTES, touched within the lookback window."""
    from ..session_models import LearningSession
    idle_before = now - policy.EPISODE_IDLE_MINUTES * 60
    since = now - policy.EPISODE_SESSION_LOOKBACK_DAYS * policy.DAY_SECONDS
    found = []
    with store_.engine.connect() as conn:
        rows = conn.execute(text("SELECT payload FROM learning_sessions WHERE learner_id=:owner ORDER BY updated_at DESC LIMIT 200"),
                            {"owner": owner}).scalars().all()
    for raw in rows:
        session = LearningSession.model_validate_json(raw)
        updated = session.updated_at.timestamp()
        if since <= updated <= idle_before:
            found.append(session)
    return found


def journey_for(store_, owner, session_id):
    from fastapi import HTTPException
    from ..workflow_store import WorkflowStore
    try:
        return WorkflowStore(store_).read(owner, f"journey_{session_id}", "journey")
    except HTTPException:
        return None


def schedule_episodes(store_, owner, now, counts):
    """Step 5: queue an episode for each idle session with uncovered turns."""
    from ..workflow_store import WorkflowStore
    queued = 0
    for session in idle_sessions(store_, owner, now):
        if queued >= policy.MAX_EPISODE_SESSIONS_PER_RUN:
            break
        journey = journey_for(store_, owner, session.id)
        turns = episodes.completed_turns(journey)
        if not turns:
            continue
        with store_.transaction() as conn:
            covered = store.episode_coverage(conn, owner, session.id)
            through = turns[-1][0]
            if through <= covered:
                continue
            WorkflowStore(store_).enqueue(owner, session.id, KIND_EPISODE, {"sessionId": session.id, "through": through},
                                         f"memory_episode:{session.id}:{through}", connection=conn, queue="batch", max_attempts=3)
        queued += 1
    counts["episodesQueued"] += queued


def write_episode(store_, owner, payload, *, now=None):
    """The memory_episode job: one extractive episode for a session's uncovered turns."""
    now = now or time.time()
    with store_.engine.connect() as conn:
        if not store.get_settings(conn, owner)["learning_enabled"]:
            return {"status": "skipped", "reason": "learning_paused"}
    session = store_.get_session(payload["sessionId"])
    if session is None or session.learner_id != owner:
        return {"status": "skipped", "reason": "session_unavailable"}
    journey = journey_for(store_, owner, session.id)
    with store_.engine.connect() as conn:
        covered = store.episode_coverage(conn, owner, session.id)
    turns = [(index, turn) for index, turn in episodes.completed_turns(journey) if covered < index <= int(payload["through"])]
    episode = episodes.build(owner, session, journey, turns, now=now)
    if episode is None:
        return {"status": "skipped", "reason": "nothing_to_summarize"}
    with store_.transaction() as conn:
        created = store.insert_episode(conn, owner, episode)
    return {"status": "created" if created else "existing", "turns": len(turns), "method": episode["method"]}


# --- Change log (learner-visible, content-free) -----------------------------------

def _changes_id(owner) -> str:
    return "memchanges_" + hashlib.sha256(str(owner).encode()).hexdigest()[:40]


def record_change(conn, owner, source, counts, *, fact_ids=(), now=None):
    """Append a content-free entry to the owner's change log (newest first, capped)."""
    counts = {key: value for key, value in counts.items() if value}
    if not counts:
        return
    entry = {"at": now or time.time(), "source": source, "counts": counts, "factIds": list(fact_ids)[:20]}
    identifier = _changes_id(owner)
    current = conn.execute(text("SELECT payload FROM context_records WHERE id=:id AND owner_id=:owner"),
                           {"id": identifier, "owner": owner}).scalar_one_or_none()
    entries = [entry] + (json.loads(current).get("entries", []) if current else [])
    payload = json.dumps({"entries": entries[:policy.MAX_CHANGE_ENTRIES]}, separators=(",", ":"))
    if current is None:
        conn.execute(text("""INSERT INTO context_records(id,owner_id,kind,session_id,sequence,payload)
            VALUES(:id,:owner,:kind,NULL,1,:payload)"""), {"id": identifier, "owner": owner, "kind": CHANGES_KIND, "payload": payload})
    else:
        conn.execute(text("UPDATE context_records SET payload=:payload,sequence=sequence+1 WHERE id=:id AND owner_id=:owner"),
                     {"payload": payload, "id": identifier, "owner": owner})


def changes(conn, owner):
    raw = conn.execute(text("SELECT payload FROM context_records WHERE owner_id=:owner AND kind=:kind ORDER BY sequence DESC LIMIT 1"),
                       {"owner": owner, "kind": CHANGES_KIND}).scalar_one_or_none()
    return json.loads(raw).get("entries", []) if raw else []


# --- Job body ------------------------------------------------------------------------

def consolidate(store_, owner, *, now=None) -> dict:
    """Run every step for one owner; returns content-free counts."""
    now = now or time.time()
    counts = Counter()
    expire_tentative(store_, owner, now, counts)
    archive_weak(store_, owner, now, counts)
    dedupe(store_, owner, now, counts)
    review_conflicts(store_, owner, now, counts)
    with store_.transaction() as conn:
        counts["shadowDeleted"] += store.delete_shadow_facts_before(conn, owner, now - policy.SHADOW_RETENTION_DAYS * policy.DAY_SECONDS)
    schedule_episodes(store_, owner, now, counts)
    with store_.transaction() as conn:
        counts["profileRebuilt"] += int(profile.rebuild(conn, owner, now=now))
        visible = {key: counts[key] for key in ("archived", "expired", "promoted", "merged", "needsReview", "episodesArchived")}
        record_change(conn, owner, "consolidation", visible, now=now)
    report = {key: counts[key] for key in sorted(counts)}
    logger.info("memory consolidation %s", json.dumps(report, sort_keys=True))
    return {"status": "consolidated", **report}
