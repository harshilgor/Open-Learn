"""Hybrid retrieval, time intent, ranking, and budgeting (spec §8.2).

Pure functions over candidate rows, so ranking is unit-testable with a fixed
clock. The read path never writes; use is recorded at turn commit.
"""
from __future__ import annotations

import calendar
import math
import re
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..context_engine import estimate_tokens
from . import policy

STOP = {"about", "after", "again", "could", "does", "from", "have", "into", "just", "know", "more", "please", "that",
        "their", "them", "there", "these", "this", "what", "when", "where", "which", "with", "would", "your", "the",
        "and", "for", "are", "was", "you", "can", "how", "why", "has", "had", "its", "our", "but", "not", "all", "any"}
# Full weekday names only: abbreviations ("sun", "sat") are ordinary words.
WEEKDAYS = {name.lower(): index for index, name in enumerate(calendar.day_name)}
MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): index for index, name in enumerate(calendar.month_abbr) if name})
PAST_CUE = re.compile(r"\b(?:did|was|were|covered|learned|learnt|studied|struggled|went|had|ago)\b", re.I)
PERSONAL_CUE = re.compile(r"\b(?:i|i'm|im|my|me|mine|remember|deadline|due|exam|test|quiz|midterm|final|goal|prefer|last time|we covered|we did)\b", re.I)


@dataclass(frozen=True)
class TimeIntent:
    start: float
    end: float
    prefers_future: bool


@dataclass
class Scored:
    item: dict
    item_type: str  # "fact" or "episode"
    relevance: float
    strength: float
    score: float
    signals: dict = field(default_factory=dict)


def tokens(text: str) -> list[str]:
    return list(_tokens(text or ""))


@lru_cache(maxsize=65536)
def _tokens(text: str) -> tuple[str, ...]:
    # Statements are immutable, so cached tokens stay valid across turns.
    words = _WORD.findall(text.lower())
    return tuple(word[:-1] if len(word) > 4 and word.endswith("s") else word for word in words if word not in STOP)


_WORD = re.compile(r"[a-z0-9]{3,}")


def zone(name: str | None):
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _day_bounds(day: date, tz) -> tuple[float, float]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def parse_time_intent(message: str, now: float, timezone_name: str | None = None) -> TimeIntent | None:
    """Deterministic window for time phrases in the learner's message (§8.2 step 3)."""
    text = (message or "").lower()
    tz = zone(timezone_name)
    today = datetime.fromtimestamp(now, tz).date()

    def days(first: date, count: int, future: bool) -> TimeIntent:
        start, _ = _day_bounds(first, tz)
        _, end = _day_bounds(first + timedelta(days=count - 1), tz)
        return TimeIntent(start, end, future)

    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            day = date(int(match[1]), int(match[2]), int(match[3]))
            return days(day, 1, day >= today)
        except ValueError:
            pass
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.search(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text)
    if match:
        month, number = MONTHS[match[1]], int(match[2])
        try:
            day = date(today.year, month, number)
            if day < today - timedelta(days=183):
                day = date(today.year + 1, month, number)
            return days(day, 1, day >= today)
        except ValueError:
            pass
    if re.search(r"\btoday\b|\btonight\b", text):
        return days(today, 1, True)
    if re.search(r"\btomorrow\b", text):
        return days(today + timedelta(days=1), 1, True)
    if re.search(r"\byesterday\b", text):
        return days(today - timedelta(days=1), 1, False)
    match = re.search(r"\b(last|this|next)\s+(week|month)\b", text)
    if match:
        which, unit = match[1], match[2]
        if unit == "week":
            monday = today - timedelta(days=today.weekday())
            offset = {"last": -7, "this": 0, "next": 7}[which]
            return days(monday + timedelta(days=offset), 7, which != "last")
        first = today.replace(day=1)
        if which == "last":
            first = (first - timedelta(days=1)).replace(day=1)
        elif which == "next":
            first = (first + timedelta(days=32)).replace(day=1)
        return days(first, calendar.monthrange(first.year, first.month)[1], which != "last")
    weekday_names = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
    match = re.search(rf"\b(?:(last|this|next|on)\s+)?({weekday_names})\b", text)
    if match:
        target = WEEKDAYS[match[2]]
        if match[1] == "last":
            delta = (today.weekday() - target) % 7 or 7
            return days(today - timedelta(days=delta), 1, False)
        if match[1] == "next":
            # "next Friday" means the Friday of next week (bare "Friday" is the coming one).
            monday = today - timedelta(days=today.weekday())
            return days(monday + timedelta(days=7 + target), 1, True)
        delta = (target - today.weekday()) % 7
        return days(today + timedelta(days=delta), 1, True)
    match = re.search(rf"\b(?:in|during|since)\s+({month_names})\b", text)
    if match:
        month = MONTHS[match[1]]
        if PAST_CUE.search(text):  # "what did we cover in September": the most recent past one
            year = today.year if month <= today.month else today.year - 1
        else:  # "what's due in November": the next one
            year = today.year if month >= today.month else today.year + 1
        first = date(year, month, 1)
        return days(first, calendar.monthrange(year, month)[1], first > today)
    if re.search(r"\bwhen(?:'s| is| are)\s+(?:my|the|our)\b|\b(?:next|upcoming)\s+(?:deadline|exam|test|quiz|midterm|final|due)", text):
        return days(today, 183, True)
    return None


def should_retrieve(message: str, intent: TimeIntent | None) -> bool:
    """Skip retrieved facts for short, impersonal messages (§8.2 step 1)."""
    return len(re.findall(r"\S+", message or "")) >= 3 or intent is not None or bool(PERSONAL_CUE.search(message or ""))


def bm25(query_terms, documents, *, k1=1.2, b=0.75) -> list[float]:
    """BM25 over the candidate set, normalized to [0, 1] by the best score."""
    if not query_terms or not documents:
        return [0.0] * len(documents)
    count = len(documents)
    average = sum(len(doc) for doc in documents) / count or 1.0
    wanted = set(query_terms)
    matches = []
    frequency = dict.fromkeys(wanted, 0)
    for doc in documents:
        counts = {}
        for term in doc:
            if term in wanted:
                counts[term] = counts.get(term, 0) + 1
        for term in counts:
            frequency[term] += 1
        matches.append(counts)
    raw = []
    for doc, counts in zip(documents, matches):
        score = 0.0
        if counts:
            length = len(doc) or 1
            for term, tf in counts.items():
                idf = math.log(1 + (count - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average))
        raw.append(score)
    best = max(raw)
    return [value / best if best > 0 else 0.0 for value in raw]


@dataclass(frozen=True)
class LexicalIndex:
    """Inverted index over a cached corpus: term -> ((doc id, tf), ...)."""
    postings: dict
    lengths: dict
    average: float
    count: int


def fact_document(fact) -> tuple[str, ...]:
    return _tokens(fact["statement"] + " " + fact["subject_key"].split(":", 1)[-1].replace("-", " "))


def episode_document(episode) -> tuple[str, ...]:
    return _tokens(episode["summary"] + " " + " ".join(str(topic) for topic in episode.get("topics") or []))


def build_index(documents: dict) -> LexicalIndex:
    postings, lengths = {}, {}
    for identifier, doc in documents.items():
        lengths[identifier] = len(doc)
        counts = {}
        for term in doc:
            counts[term] = counts.get(term, 0) + 1
        for term, tf in counts.items():
            postings.setdefault(term, []).append((identifier, tf))
    count = len(documents)
    return LexicalIndex({term: tuple(items) for term, items in postings.items()}, lengths,
                        (sum(lengths.values()) / count) if count else 1.0, count)


def bm25_indexed(query_terms, index: LexicalIndex, allowed=None, *, k1=1.2, b=0.75) -> dict:
    """BM25 touching only documents that contain a query term; normalized to [0, 1]."""
    raw = {}
    for term in set(query_terms):
        items = index.postings.get(term)
        if not items:
            continue
        idf = math.log(1 + (index.count - len(items) + 0.5) / (len(items) + 0.5))
        for identifier, tf in items:
            if allowed is not None and identifier not in allowed:
                continue
            length = index.lengths[identifier] or 1
            raw[identifier] = raw.get(identifier, 0.0) + idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (index.average or 1.0)))
    best = max(raw.values(), default=0.0)
    return {identifier: value / best for identifier, value in raw.items()} if best > 0 else {}


@lru_cache(maxsize=8192)
def _event_moment(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.fromisoformat(value + "T12:00:00")
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def temporal_score(start: float | None, end: float | None, intent: TimeIntent | None, now: float, kind: str | None = None) -> float:
    if intent is None:
        if kind == "deadline" and start is not None:
            days_until = (start - now) / policy.DAY_SECONDS
            return 0.0 if days_until < 0 else 1 - min(days_until / 60, 1)
        return 0.5
    if start is None:
        return 0.0
    end = end if end is not None else start
    if end >= intent.start and start <= intent.end:
        return 1.0
    # Linear decay outside the window (§8.2), but over at most a week: for a
    # month-long window, a session nine days outside it is not "in October".
    span = min(max(intent.end - intent.start, policy.DAY_SECONDS), policy.TEMPORAL_DECAY_MAX_DAYS * policy.DAY_SECONDS)
    distance = intent.start - end if end < intent.start else start - intent.end
    return max(0.0, 1 - distance / span)


def _jaccard(left, right) -> float:
    left, right = set(left or ()), set(right or ())
    return len(left & right) / len(left | right) if left and right else 0.0


def rank(facts, episodes, *, message, now, course_id=None, concept_ids=(), intent=None, hydrate=None, fact_index=None, episode_index=None):
    """Score facts and episodes; drop weak relevance (except near deadlines).

    ``hydrate(ids) -> {id: fields}`` supplies per-use fields (last_used_at,
    stability_days) for facts that pass the relevance filter, so callers can
    rank over cached static rows and read only the survivors' volatile state.
    """
    weights = {key: value for key, value in policy.RELEVANCE_WEIGHTS.items() if key != "semantic"}
    total = sum(weights.values())
    query = tokens(message)
    if fact_index is not None:
        lexical_by_id = bm25_indexed(query, fact_index, {fact["id"] for fact in facts})
        fact_scores = [lexical_by_id.get(fact["id"], 0.0) for fact in facts]
    else:
        fact_scores = bm25(query, [fact_document(fact) for fact in facts])
    if episode_index is not None:
        lexical_by_id = bm25_indexed(query, episode_index, {episode["id"] for episode in episodes})
        episode_scores = [lexical_by_id.get(episode["id"], 0.0) for episode in episodes]
    else:
        episode_scores = bm25(query, [episode_document(episode) for episode in episodes])
    ranked = []
    # Undated facts with no lexical or concept overlap score at most the neutral
    # temporal share, which is below the relevance floor: skip them cheaply.
    neutral_ceiling = weights["temporal"] * 0.5 / total
    skip_unmatched = neutral_ceiling < policy.MIN_RELEVANCE
    concept_set = set(concept_ids)
    survivors = []
    for fact, lexical in zip(facts, fact_scores):
        if skip_unmatched and not lexical and not fact.get("event_date") and not (concept_set and concept_set.intersection(fact.get("concept_ids") or ())):
            continue
        moment = _event_moment(fact.get("event_date"))
        signals = {"lexical": lexical, "concept": _jaccard(fact.get("concept_ids"), concept_ids),
                   "temporal": temporal_score(moment, moment, intent, now, fact["kind"])}
        relevance = sum(weights[key] * signals[key] for key in weights) / total
        near_deadline = fact["kind"] == "deadline" and moment is not None and 0 <= moment - now <= policy.DEADLINE_ALWAYS_DAYS * policy.DAY_SECONDS
        if relevance < policy.MIN_RELEVANCE and not near_deadline:
            continue
        survivors.append((fact, relevance, signals))
    volatile = hydrate([fact["id"] for fact, _, _ in survivors]) if hydrate and survivors else {}
    for fact, relevance, signals in survivors:
        if hydrate:
            if fact["id"] not in volatile:
                continue  # deleted or deactivated since the static rows were read
            fact = {**fact, **volatile[fact["id"]]}
        strength = policy.retention(fact, now)
        score = (relevance * (0.6 + 0.4 * strength) * (0.7 + 0.3 * fact["importance"])
                 + policy.ORIGIN_BONUS.get(fact["origin"], 0.0)
                 + (policy.SCOPE_BONUS if course_id and fact.get("course_id") == course_id else 0.0))
        ranked.append(Scored(fact, "fact", relevance, strength, score, signals))
    for episode, lexical in zip(episodes, episode_scores):
        signals = {"lexical": lexical, "concept": _jaccard([topic for topic in episode.get("topics") or [] if isinstance(topic, str)], concept_ids),
                   "temporal": temporal_score(episode["period_start"], episode["period_end"], intent, now)}
        relevance = sum(weights[key] * signals[key] for key in weights) / total
        if relevance < policy.MIN_RELEVANCE:
            continue
        age_days = max(0.0, now - episode["period_end"]) / policy.DAY_SECONDS
        strength = math.exp(-age_days / 90)
        ranked.append(Scored(episode, "episode", relevance, strength, relevance * (0.6 + 0.4 * strength), signals))
    return sorted(ranked, key=lambda item: (-item.score, item.item["id"]))


def select(ranked, *, exclude_ids=()):
    """Diversity (≤2 per kind, ≤3 episodes) and per-section token budgets."""
    excluded = set(exclude_ids)
    facts, episodes, omitted = [], [], []
    per_kind = {}
    fact_tokens = episode_tokens = 0
    for entry in ranked:
        identifier = entry.item["id"]
        if identifier in excluded:
            continue
        if entry.item_type == "fact":
            kind = entry.item["subject_key"].split(":", 1)[0]
            cost = estimate_tokens(entry.item["statement"]) + 12
            if per_kind.get(kind, 0) >= policy.MAX_PER_KIND:
                omitted.append({"id": identifier, "reason": "kind_diversity"}); continue
            if fact_tokens + cost > policy.RETRIEVED_MAX_TOKENS:
                omitted.append({"id": identifier, "reason": "memory_budget"}); continue
            per_kind[kind] = per_kind.get(kind, 0) + 1
            fact_tokens += cost
            facts.append(entry)
        else:
            cost = estimate_tokens(entry.item["summary"]) + 16
            if len(episodes) >= policy.MAX_EPISODES:
                omitted.append({"id": identifier, "reason": "episode_limit"}); continue
            if episode_tokens + cost > policy.EPISODES_MAX_TOKENS:
                omitted.append({"id": identifier, "reason": "memory_budget"}); continue
            episode_tokens += cost
            episodes.append(entry)
    return facts, episodes, omitted
