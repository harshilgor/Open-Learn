"""LearnerMemoryService: the façade journey, compiler, routes, and jobs use.

Reads explicit preferences from memory_facts (Phase B), plus academic
entities and the unified learner state. Memory is context about the learner, never an
instruction, and every read is owner-scoped. Failures degrade to no memory.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
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


def compiler_preferences(conn, owner, course_id):
    """Active preference and constraint facts for the context compiler (Phase F3).

    Allowed in every purpose, assessment included (§2 rule 5). Ordered by the
    §10 precedence among memory facts: course-scoped before global, then
    learner-stated or confirmed before inferred, then most recently stated.
    """
    from . import store

    rows = conn.execute(text(f"""SELECT id,kind,statement,course_id,origin,learned_at,confirmed_at FROM memory_facts
        WHERE owner_id=:owner AND status='active' AND kind IN ('preference','constraint') AND {store.PROMPT_ELIGIBLE}
          AND (course_id IS NULL OR course_id=:course)"""),
        {"owner": owner, "course": course_id or "", "false": False, "true": True}).mappings().all()

    def rank(row):
        scoped = course_id is not None and row["course_id"] == course_id
        newest = max(row["learned_at"], row["confirmed_at"] or 0.0)
        return (not scoped, -policy.ORIGIN_RANK.get(row["origin"], 0), -newest, row["id"])

    return [{"id": row["id"], "kind": row["kind"], "source": "memory_fact",
             "value": {"statement": row["statement"].strip()[:policy.PREFERENCE_MAX_CHARS]},
             "scope": row["course_id"], "explicit": row["origin"] in {"user_stated", "user_confirmed"}}
            for row in sorted(rows, key=rank)[:policy.COMPILER_MAX_REMEMBERED]]


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

    # --- Phase D: retrieval v2 (§8.2) ------------------------------------------

    def context(self, owner, course_id, message, *, purpose="teaching", now=None, concept_ids=(), timezone_name=None):
        """Ranked, budgeted learner memory rendered as byte-stable text, or None.

        Assessment context gets only preference and constraint facts, never
        episodes, dates or progress (§2 rule 5). Never raises.
        """
        try:
            return self._context(owner, course_id, message, purpose=purpose, now=now or time.time(),
                                 concept_ids=tuple(item for item in concept_ids if item), timezone_name=timezone_name)
        except Exception:
            logger.warning("learner memory retrieval unavailable", exc_info=False)
            return None

    def _core_profile(self, owner, cache_key, watermark):
        """The stored core profile payload, or None (fall back to the Phase D profile).

        Cached per process behind the memory version; a failed load is not
        cached, so the next turn retries.
        """
        from ..performance import span
        from . import profile

        def load():
            with span("memory_profile"):
                return profile.load(self.store, owner)
        try:
            return _cached(_PROFILES, cache_key, watermark, load)
        except Exception:
            logger.warning("learner core profile unavailable", exc_info=False)
            return None

    def _context(self, owner, course_id, message, *, purpose, now, concept_ids, timezone_name):
        from . import retrieval, store
        assessment = purpose == "assessment"
        intent = retrieval.parse_time_intent(message, now, timezone_name)
        tz = retrieval.zone(timezone_name)
        with self.store.engine.connect() as conn:
            allowed = {"preference", "constraint"} if assessment else None
            cache_key = (str(self.store.engine.url), owner)
            facts_mark, episodes_mark = store.watermarks(conn, owner)
            all_facts, fact_index = _cached(_FACTS, cache_key, facts_mark, lambda: _with_index(
                store.static_facts(conn, owner), retrieval.fact_document))
            # A profile rewrite bumps the memory version, so this never serves a stale profile.
            core = self._core_profile(owner, cache_key, facts_mark) if policy.consolidation_enabled() else None
            facts = [fact for fact in all_facts
                     if (fact["course_id"] is None or fact["course_id"] == course_id) and (allowed is None or fact["kind"] in allowed)]
            since = now - policy.EPISODE_LOOKBACK_DAYS * policy.DAY_SECONDS
            episodes, episode_index = [], None
            if not assessment:
                all_episodes, episode_index = _cached(_EPISODES, cache_key, episodes_mark, lambda: _with_index(
                    store.candidate_episodes(conn, owner, None, 0), retrieval.episode_document))
                episodes = [episode for episode in all_episodes
                            if episode["period_end"] >= since and (episode["course_id"] is None or not course_id or episode["course_id"] == course_id)
                            ][:policy.EPISODE_CANDIDATE_CAP]
            moment = datetime.fromtimestamp(now, timezone.utc)
            upcoming = [] if assessment else self._upcoming(conn, owner, course_id, moment)
            progress = [] if assessment else self._learner_state(conn, owner, course_id)
            hydrate = lambda ids: store.volatile_for(conn, owner, ids)  # noqa: E731
            retrieve = not assessment and retrieval.should_retrieve(message, intent)
            ranked = retrieval.rank(facts, episodes, message=message, now=now, course_id=course_id, concept_ids=concept_ids,
                                    intent=intent, hydrate=hydrate, fact_index=fact_index, episode_index=episode_index) if retrieve else []

        if core is not None:
            # The stored core profile (§9.3 step 6), in its stored order. Only
            # facts still active, in scope and allowed for this purpose render,
            # so a forgotten fact leaves the prompt before the next rebuild.
            by_id = {fact["id"]: fact for fact in facts}
            profile = [by_id[identifier] for identifier in core.get("factIds") or [] if identifier in by_id]
        else:
            # Before a core profile exists: preferences and constraints always
            # apply. Course-scoped first.
            def profile_rank(fact):
                scoped = course_id is not None and fact["course_id"] == course_id
                return (not scoped, fact["kind"] != "constraint", -policy.ORIGIN_RANK.get(fact["origin"], 0),
                        -policy.last_reinforced_at(fact), fact["id"])
            profile, used = [], 0
            for fact in sorted((fact for fact in facts if fact["kind"] in {"preference", "constraint"}), key=profile_rank):
                cost = estimate_tokens(fact["statement"]) + 12
                if used + cost > policy.PROFILE_MAX_TOKENS:
                    break
                profile.append(fact); used += cost
        retrieved, chosen_episodes, omitted = [], [], []
        if retrieve:
            retrieved, chosen_episodes, omitted = retrieval.select(ranked, exclude_ids={fact["id"] for fact in profile})

        def day(epoch):
            return datetime.fromtimestamp(epoch, tz).date().isoformat()

        names = {}

        def course_name(identifier):
            # Only course-scoped lines need names; most turns never query them.
            if not names:
                with self.store.engine.connect() as conn:
                    names.update(store.course_names(conn, owner) or {None: None})
            return names.get(identifier)

        def fact_line(fact):
            label = fact["kind"].replace("_", " ")
            if fact.get("course_id") and course_name(fact["course_id"]):
                label += " · " + course_name(fact["course_id"])
            return f"- [{label}] {fact['statement']} (learner said, {day(fact['learned_at'])})"

        sections = [
            ("Profile:", [fact_line(fact) for fact in profile]),
            ("Relevant memories:", [fact_line(entry.item) for entry in retrieved]),
            ("Upcoming course dates:", [f"- {item['date']} · {item['type']} · {item['title']}" for item in upcoming]),
            ("Learner progress:", [f"- {item['concept']} ({item['capability']}): {item['status']}" + (f", {item['retention'].replace('_', ' ')}" if item.get("retention") else "")
                                   for item in progress]),
            ("Earlier sessions:", [f"- {day(entry.item['period_end'])} · {entry.item['summary']}" for entry in chosen_episodes]),
        ]
        header = policy.MEMORY_BLOCK_HEADER + ":"

        def render(parts):
            lines = [header]
            for title, items in parts:
                if items:
                    lines.append(title); lines.extend(items)
            return "\n".join(lines)

        # Whole-block cap: trim the least essential sections first.
        sections = [(title, list(items)) for title, items in sections]
        for index in (4, 3, 2, 1, 0):
            while estimate_tokens(render(sections)) > policy.MEMORY_BLOCK_MAX_TOKENS and sections[index][1]:
                sections[index][1].pop()
        kept_profile = profile[:len(sections[0][1])]
        kept_retrieved = retrieved[:len(sections[1][1])]
        kept_episodes = chosen_episodes[:len(sections[4][1])]
        for entry in retrieved[len(kept_retrieved):]:
            omitted.append({"id": entry.item["id"], "reason": "block_budget"})
        if not any(items for _, items in sections):
            return None
        trace = {
            "policyVersion": policy.MEMORY_POLICY_VERSION, "purpose": purpose, "timeIntent": intent is not None,
            "coreProfile": core is not None,
            "candidates": {"facts": len(facts), "episodes": len(episodes)},
            "profile": [fact["id"] for fact in kept_profile],
            "included": [{"id": entry.item["id"], "type": entry.item_type, "score": round(entry.score, 4),
                          "relevance": round(entry.relevance, 4), "strength": round(entry.strength, 4)}
                         for entry in kept_retrieved + kept_episodes],
            "omitted": omitted[:50],
        }
        return MemoryContext(text=render(sections), fact_ids=tuple(fact["id"] for fact in kept_profile) + tuple(entry.item["id"] for entry in kept_retrieved),
                             episode_ids=tuple(entry.item["id"] for entry in kept_episodes), trace=trace)


# Per-process cache of static ranking rows, revalidated every turn by a cheap
# watermark query, so a stale entry is never served (§11.4 latency target).
_FACTS: "OrderedDict[str, tuple]" = OrderedDict()
_EPISODES: "OrderedDict[str, tuple]" = OrderedDict()
_PROFILES: "OrderedDict[str, tuple]" = OrderedDict()
_CACHE_OWNERS = 64
_CACHE_LOCK = threading.Lock()


def _with_index(rows, document):
    from . import retrieval
    return rows, retrieval.build_index({row["id"]: document(row) for row in rows})


def _cached(cache, key, watermark, load):
    """key is (database URL, owner): never shared across databases or owners."""
    with _CACHE_LOCK:
        hit = cache.get(key)
        if hit and hit[0] == watermark:
            cache.move_to_end(key)
            return hit[1]
    rows = load()
    with _CACHE_LOCK:
        cache[key] = (watermark, rows)
        cache.move_to_end(key)
        while len(cache) > _CACHE_OWNERS:
            cache.popitem(last=False)
    return rows


@dataclass(frozen=True)
class MemoryContext:
    text: str
    fact_ids: tuple
    episode_ids: tuple
    trace: dict
