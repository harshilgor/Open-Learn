"""Extractive session episodes (spec §6.2, §9.3 step 5): what was covered, and when.

An episode summarizes the turns of one session that no earlier episode
covers. It is built deterministically from the learner's questions and the
first heading or sentence of each answer, plus lesson titles and stable
concept IDs as topics. No model is called, so episodes cost nothing and can
never introduce text the session did not contain.

Questions that read as instructions, or that touch a sensitive category, are
left out: an episode re-enters later prompts in other sessions, so it must
not carry injected directives or sensitive details (§2 rules 1 and 6).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from . import policy

METHOD = "extractive-v1"
_INSTRUCTION = re.compile("|".join(policy.INSTRUCTION_DENYLIST), re.IGNORECASE)
_SENSITIVE = re.compile("|".join(policy.SENSITIVE_KEYWORDS), re.IGNORECASE)


def episode_id(owner, session_id, start, end) -> str:
    return "episode_" + hashlib.sha256(json.dumps([owner, session_id, start, end]).encode()).hexdigest()[:32]


def _clip(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _answer_lead(turn) -> str:
    """The first heading of the answer, or else its first sentence."""
    blocks = (turn.get("lesson") or {}).get("blocks") or []
    for block in blocks:
        heading = str(block.get("heading") or "").strip()
        if heading:
            return heading
    for block in blocks:
        body = re.sub(r"[#*_`>]+", " ", str(block.get("body") or "")).strip()
        if body:
            return re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]
    return ""


def _usable(text: str) -> bool:
    return bool(text) and not _INSTRUCTION.search(text) and not _SENSITIVE.search(text)


def completed_turns(journey) -> list[tuple[int, dict]]:
    return [(index, turn) for index, turn in enumerate((journey or {}).get("turns") or [])
            if turn.get("status") in {None, "completed"} and isinstance(turn.get("question"), str) and turn.get("lesson")]


def build(owner, session, journey, turns, *, now) -> dict | None:
    """One episode for ``turns`` (index, turn) pairs of a session, or None if nothing is usable."""
    if not turns:
        return None
    items, titles = [], []
    for _, turn in turns:
        question = _clip(turn["question"], policy.EPISODE_QUESTION_CHARS)
        lead = _clip(_answer_lead(turn), policy.EPISODE_ANSWER_CHARS)
        if _usable(question):
            items.append(f"{question} → {lead}" if _usable(lead) else question)
        title = str((turn.get("lesson") or {}).get("title") or "").strip()
        if title and _usable(title) and title not in titles:
            titles.append(_clip(title, 80))
    concepts = [item for item in dict.fromkeys((journey or {}).get("taughtCanonicalConceptIds") or (journey or {}).get("canonicalConceptIds") or [])
                if isinstance(item, str)]
    topics = (titles[:policy.EPISODE_MAX_TOPICS] + concepts[:policy.EPISODE_MAX_TOPICS])
    if not items and not titles:
        return None
    covered = ", ".join(titles[:policy.EPISODE_MAX_TOPICS])
    summary = f"Covered {covered}." if covered else ""
    asked = ""
    for item in items:
        candidate = (asked + "; " if asked else "Learner asked: ") + item
        if len((summary + " " + candidate).strip()) > policy.EPISODE_SUMMARY_MAX_CHARS:
            break
        asked = candidate
    summary = (summary + " " + asked).strip() if asked else summary
    summary = _clip(summary, policy.EPISODE_SUMMARY_MAX_CHARS)
    if not summary:
        return None
    first, last = turns[0][0], turns[-1][0]
    updated = session.updated_at.timestamp() if isinstance(session.updated_at, datetime) else now
    times = [float(turn["submittedAt"]) for _, turn in turns if isinstance(turn.get("submittedAt"), (int, float))]
    basis = [{"type": "turn", "sessionId": session.id, "turnIndex": index, **({"generationId": turn["generationId"]} if turn.get("generationId") else {})}
             for index, turn in turns][-policy.EPISODE_MAX_BASIS:]
    return {"id": episode_id(owner, session.id, first, last), "session_id": session.id, "course_id": session.course_id,
            "period_start": min(times) if times else updated, "period_end": max(times) if times else updated,
            "turn_range": {"from": first, "to": last}, "summary": summary, "topics": topics, "method": METHOD,
            "basis": basis, "created_at": now}
