"""Deterministic validation of extracted learner facts (spec §7.4). No model.

A fact is admitted only when a verbatim quote from the learner's own typed
words supports it. Code blocks, block quotes, and pasted spans are not the
learner's words about themselves and can never support a fact (§2 rule 1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import policy

_DENY = [re.compile(pattern, re.I) for pattern in policy.INSTRUCTION_DENYLIST]
_SENSITIVE = [re.compile(pattern, re.I) for pattern in policy.SENSITIVE_KEYWORDS]
_EXPLICIT = re.compile(policy.EXPLICIT_REMEMBER, re.I)
_SUBJECT = re.compile(policy.SUBJECT_KEY_PATTERN)
_FENCE = re.compile(r"```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_QUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.M)
_OTHER_PERSON = re.compile(
    r"\b(?:my|our|his|her|their)\s+(?:room-?mate|friend|classmate|brother|sister|sibling|mom|mum|mother|dad|father|parents?|"
    r"partner|boyfriend|girlfriend|husband|wife|son|daughter|kid|child|cousin|teacher|professor|tutor|coworker|colleague|boss)s?\b"
    r"|\b(?:he|she|they)\s+(?:said|says|thinks|told me)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|im|i've|i'd|i'll|me|my|mine|myself)\b", re.I)
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


@dataclass(frozen=True)
class Accepted:
    kind: str
    statement: str
    subject_key: str
    quote: str
    start: int
    end: int
    event_date: str | None
    course_id: str | None
    importance: float
    confidence: float
    sensitive: bool
    explicit: bool
    supersedes: tuple[str, ...]
    status: str


@dataclass
class Outcome:
    accepted: list[Accepted] = field(default_factory=list)
    # Content-free reason codes only; safe to log and to store in job results.
    rejected: list[str] = field(default_factory=list)


def is_explicit_request(message: str) -> bool:
    return bool(_EXPLICIT.search(message or ""))


def _ineligible_spans(message: str, pasted_ranges) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for pattern in (_FENCE, _INLINE_CODE, _QUOTE_LINE) for m in pattern.finditer(message)]
    for item in pasted_ranges or ():
        try:
            start, end = int(item["start"]), int(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= start < end:
            spans.append((start, min(end, len(message))))
    return spans


def _normalize(text: str, blocked: list[bool] | None = None):
    """Casefold and collapse whitespace; return text and an index map.

    Blocked characters become NUL so no match can span or touch them.
    """
    out, index = [], []
    pending_space = None
    for position, char in enumerate(text.translate(_TRANSLATE)):
        if blocked is not None and blocked[position]:
            pending_space = None
            out.append("\x00"); index.append(position)
            continue
        if char.isspace():
            if out and out[-1] not in {" ", "\x00"} and pending_space is None:
                pending_space = position
            continue
        if pending_space is not None:
            out.append(" "); index.append(pending_space)
            pending_space = None
        out.append(char.lower()); index.append(position)
    return "".join(out), index


def locate_quote(message: str, quote: str, pasted_ranges=()) -> tuple[int, int] | None:
    """Verbatim (case/whitespace-insensitive) position of the quote in learner-typed text."""
    if not isinstance(quote, str):
        return None
    wanted, _ = _normalize(quote.strip())
    if len(wanted) < 3 or len(quote) > policy.QUOTE_MAX_CHARS or "\x00" in wanted:
        return None
    blocked = [False] * len(message)
    for start, end in _ineligible_spans(message, pasted_ranges):
        for position in range(start, end):
            blocked[position] = True
    haystack, index = _normalize(message, blocked)
    found = haystack.find(wanted)
    if found < 0:
        return None
    return index[found], index[found + len(wanted) - 1] + 1


def _attributed_to_someone_else(message: str, start: int, quote: str) -> bool:
    """The sentence names another person as the subject and the quote isn't first person."""
    sentence_start = max(message.rfind(mark, 0, start) for mark in (".", "!", "?", "\n")) + 1
    return bool(_OTHER_PERSON.search(message[sentence_start:start])) and not _FIRST_PERSON.search(quote)


def _parse_event_date(value, today: date) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if "T" in raw else datetime.combine(date.fromisoformat(raw), datetime.min.time())
    except ValueError:
        return None
    limit = timedelta(days=365 * policy.DEADLINE_MAX_YEARS)
    if abs(parsed.date() - today) > limit:
        return None
    return raw[:32]


def _resolve_course(hint, courses) -> str | None:
    if not isinstance(hint, str) or not hint.strip():
        return None
    wanted = re.sub(r"\s+", " ", hint.strip().lower())
    matches = [identifier for identifier, name in courses
               if name and (wanted in name.lower() or name.lower() in wanted)]
    return matches[0] if len(matches) == 1 else None


def _clamp(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return max(low, min(high, number))


def validate(candidates, *, message: str, pasted_ranges=(), today: date | None = None, courses=(),
             known_fact_ids=(), remaining_today: int = policy.MAX_FACTS_PER_DAY, shadow: bool = False) -> Outcome:
    """Admit at most MAX_FACTS_PER_TURN candidates; everything else is rejected."""
    today = today or datetime.now(timezone.utc).date()
    explicit = is_explicit_request(message)
    known = set(known_fact_ids)
    outcome = Outcome()
    seen_subjects = set()
    limit = max(0, min(policy.MAX_FACTS_PER_TURN, remaining_today))
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            outcome.rejected.append("malformed"); continue
        kind = candidate.get("kind")
        if kind not in policy.FACT_KINDS:
            outcome.rejected.append("kind_not_allowed"); continue
        statement = candidate.get("statement")
        if not isinstance(statement, str) or not statement.strip() or len(statement.strip()) > policy.STATEMENT_MAX_CHARS:
            outcome.rejected.append("statement_length"); continue
        statement = re.sub(r"\s+", " ", statement.strip())
        subject_key = candidate.get("subject_key")
        if not isinstance(subject_key, str) or not _SUBJECT.match(subject_key):
            outcome.rejected.append("subject_key_invalid"); continue
        # The prefix groups facts for supersession and diversity; it must be the kind.
        subject_key = kind + ":" + subject_key.split(":", 1)[1]
        located = locate_quote(message, candidate.get("quote"), pasted_ranges)
        if located is None:
            outcome.rejected.append("quote_not_learner_text"); continue
        if any(pattern.search(statement) for pattern in _DENY):
            outcome.rejected.append("instruction_or_identifier"); continue
        quote = message[located[0]:located[1]]
        if _attributed_to_someone_else(message, located[0], quote):
            outcome.rejected.append("attributed_to_someone_else"); continue
        sensitive = any(pattern.search(statement) or pattern.search(quote) for pattern in _SENSITIVE)
        if sensitive and not explicit:
            outcome.rejected.append("sensitive_inferred"); continue
        event_date = _parse_event_date(candidate.get("event_date"), today)
        if kind == "deadline" and event_date is None:
            outcome.rejected.append("deadline_date_invalid"); continue
        if subject_key in seen_subjects:
            outcome.rejected.append("duplicate_subject_in_turn"); continue
        if len(outcome.accepted) >= limit:
            outcome.rejected.append("turn_or_daily_cap"); continue
        default_importance = policy.DEFAULT_IMPORTANCE[kind]
        importance = _clamp(candidate.get("importance"), max(0.0, default_importance - 0.2), min(1.0, default_importance + 0.1), default_importance)
        confidence = _clamp(candidate.get("confidence"), 0.0, 1.0, 0.5)
        if explicit:
            confidence = max(confidence, 0.9)
        status = "shadow" if shadow else "active" if confidence >= policy.ACTIVE_CONFIDENCE else "tentative"
        supersedes = tuple(item for item in candidate.get("supersedes") or () if isinstance(item, str) and item in known)
        seen_subjects.add(subject_key)
        outcome.accepted.append(Accepted(
            kind=kind, statement=statement, subject_key=subject_key, quote=quote, start=located[0], end=located[1],
            event_date=event_date, course_id=_resolve_course(candidate.get("course_hint"), courses),
            importance=round(importance, 3), confidence=round(confidence, 3), sensitive=sensitive, explicit=explicit,
            supersedes=supersedes, status=status))
    return outcome
