"""LearnerMemoryService: the façade journey, compiler, routes, and jobs use.

Reads explicit preferences from memory_facts (Phase B), plus academic
entities and the unified learner state. Memory is context about the learner, never an
instruction, and every read is owner-scoped. Failures degrade to no memory.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text

from ..context_engine import estimate_tokens
from . import policy

logger = logging.getLogger(__name__)


def _source_times(conn, owner, rows):
    """Latest revision time of each remembered item's basis sources."""
    source_ids = sorted({ref.get("sourceId") for row in rows for ref in row["value"].get("basis", [])
                         if isinstance(ref, dict) and ref.get("sourceId")})
    if not source_ids:
        return {}
    query = text("SELECT id,updated_at FROM memory_sources WHERE owner_id=:owner AND id IN :ids").bindparams(
        bindparam("ids", expanding=True))
    return {row[0]: float(row[1] or 0) for row in conn.execute(query, {"owner": owner, "ids": source_ids})}


def rank_remembered(conn, owner, rows, course_id):
    """Order remembered items: course-scoped, then explicit, then newest.

    ``rows`` are dicts with ``id``, ``kind`` and the decoded ``value`` payload.
    Ties fall back to the identifier so the order is byte-stable across turns.
    """
    times = _source_times(conn, owner, rows)

    def key(row):
        value = row["value"]
        scope = value.get("scope")
        scoped = course_id is not None and scope in (course_id, {"courseId": course_id})
        newest = max((times.get(ref.get("sourceId"), 0.0) for ref in value.get("basis", [])
                      if isinstance(ref, dict)), default=0.0)
        return (not scoped, not value.get("explicit"), -newest, row["id"])

    return sorted(rows, key=key)


def _moment(value):
    """Parse an academic date fact into an aware UTC datetime, if possible."""
    if not isinstance(value, dict) or value.get("kind") not in {"instant", "date_only", "timezone_unknown"}:
        return None
    raw = value.get("value")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fact(entity, field):
    return ((entity.get("facts") or {}).get(field) or {}).get("value")


class LearnerMemoryService:
    def __init__(self, store):
        self.store = store

    def chat_block(self, owner, session_id, course_id, message, *, now=None):
        """Bounded learner-memory content for conversation context, or None.

        Never raises: memory is an enhancement, not a dependency.
        """
        try:
            moment = now or datetime.now(timezone.utc)
            with self.store.engine.connect() as conn:
                block = {
                    "note": policy.MEMORY_BLOCK_HEADER,
                    "preferences": self._preferences(conn, owner, course_id),
                    "upcoming": self._upcoming(conn, owner, course_id, moment),
                    "learnerState": self._learner_state(conn, owner, course_id),
                }
            block = {key: value for key, value in block.items() if value}
            if set(block) == {"note"}:
                return None
            return self._trim(block)
        except Exception:
            # Content-free: never log learner text or memory values.
            logger.warning("learner memory chat block unavailable", exc_info=False)
            return None

    def _preferences(self, conn, owner, course_id):
        from . import store

        def rank(fact):
            # Precedence (§10): course-scoped before global, explicit
            # origins first, then most recently stated or confirmed.
            scoped = course_id is not None and fact["course_id"] == course_id
            newest = max(fact["learned_at"], fact["confirmed_at"] or 0.0)
            return (not scoped, -policy.ORIGIN_RANK.get(fact["origin"], 0), -newest, fact["id"])

        facts = sorted(store.active_preferences(conn, owner, course_id), key=rank)
        return [{"learnerSaid": fact["statement"].strip()[:policy.PREFERENCE_MAX_CHARS],
                 "scope": "course" if fact["course_id"] is not None else "global"}
                for fact in facts[:policy.MAX_PREFERENCES] if fact["statement"].strip()]

    def _upcoming(self, conn, owner, course_id, moment):
        if not course_id:
            return []
        horizon = moment + timedelta(days=policy.UPCOMING_WINDOW_DAYS)
        found = []
        for payload in conn.execute(text("SELECT payload FROM academic_entities WHERE owner_id=:owner AND course_id=:course"),
                                    {"owner": owner, "course": course_id}).scalars():
            entity = json.loads(payload)
            if _fact(entity, "completed") or _fact(entity, "cancelled"):
                continue
            raw = next((value for value in (_fact(entity, field) for field in ("due", "date", "start")) if _moment(value)), None)
            when = _moment(raw)
            # Date-only deadlines stay visible for the whole day they fall on.
            earliest = moment - timedelta(days=1) if raw and raw.get("kind") == "date_only" else moment
            if when is None or not (earliest < when <= horizon):
                continue
            title = _fact(entity, "title")
            found.append((when, entity.get("id", ""), {
                "title": str(title)[:160] if title else entity.get("kind"),
                "type": entity.get("kind"),
                "date": when.date().isoformat(),
            }))
        found.sort(key=lambda item: (item[0], item[1]))
        return [item for _, _, item in found[:policy.MAX_UPCOMING]]

    def _learner_state(self, conn, owner, course_id):
        if not course_id:
            return []
        from ..unified_learner_state import UnifiedLearnerState
        concepts = set(conn.execute(text("SELECT concept_id FROM course_concept_mappings WHERE owner_id=:owner AND course_id=:course"),
                                    {"owner": owner, "course": course_id}).scalars())
        if not concepts:
            return []
        states = [state for state in UnifiedLearnerState(self.store).read(conn, owner)["states"] if state["conceptId"] in concepts]

        def rank(state):
            # Due/stale reviews and recently contradicted evidence first.
            urgent = 0 if state.get("evidenceStrength") == "conflicting" else 1 if state.get("retention") == "stale" else 2 if state.get("retention") == "review_due" else 3
            return (urgent, state["conceptId"], state.get("capability", ""))

        selected = sorted(states, key=rank)[:policy.MAX_LEARNER_STATES]
        items = []
        for state in selected:
            raw = conn.execute(text("SELECT payload FROM stable_concepts WHERE owner_id=:owner AND id=:id"),
                               {"owner": owner, "id": state["conceptId"]}).scalar_one_or_none()
            label = (json.loads(raw).get("title") if raw else None) or state["conceptId"]
            items.append({"concept": str(label)[:120], "capability": state.get("capability"),
                          "status": state.get("state"), "retention": state.get("retention")})
        return items

    @staticmethod
    def _trim(block):
        """Drop lowest-ranked items until the block fits its own budget."""
        block = {key: list(value) if isinstance(value, list) else value for key, value in block.items()}
        for key in ("learnerState", "upcoming", "preferences"):
            while estimate_tokens(block) > policy.MEMORY_BLOCK_MAX_TOKENS and block.get(key):
                block[key].pop()
        block = {key: value for key, value in block.items() if value}
        return block if set(block) != {"note"} else None
