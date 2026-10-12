"""Deterministic learner-memory evaluation (spec §11.3).

Replays recorded extraction outputs through the real validator and store.
No provider is called, so results are stable in CI. Phase C covers the
extraction categories; retrieval and forgetting categories arrive with
Phases D and E.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

from . import store, validator

SCENARIOS = Path(__file__).resolve().parents[2] / "evaluation" / "memory_scenarios.json"

# Promotion from shadow to on requires these (§11.3).
GATES = {"extractionPrecision": 0.9, "falseMemoryRate": 0.0, "abstentionCorrect": 0.95}


def _ranges(message, turn):
    ranges = list(turn.get("pastedRanges") or [])
    for text in turn.get("pasted") or []:
        start = message.index(text)
        ranges.append({"start": start, "end": start + len(text)})
    return ranges


def _learner_typed(message, quote, ranges):
    """Independent false-memory check: the stored quote is learner-typed text."""
    start = message.find(quote)
    return start >= 0 and not any(start < item["end"] and item["start"] < start + len(quote) for item in ranges)


def _matches(fact, expected):
    if fact["kind"] != expected["kind"] or fact["subject_key"] != expected["subject_key"]:
        return False
    for key in ("event_date", "course_id", "sensitive", "status"):
        if key in expected and fact.get(key) != expected[key]:
            return False
    contains = expected.get("statement_contains")
    return not contains or contains.lower() in fact["statement"].lower()


def run_case(db, case, today: date):
    owner = "eval_" + case["id"]
    written = []
    false_memories = 0
    for index, turn in enumerate(case["turns"]):
        message = turn["message"]
        ranges = _ranges(message, turn)
        with db.engine.connect() as conn:
            known = [fact["id"] for fact in store.list_facts(conn, owner) if fact["status"] in {"active", "tentative"}]
        # Recorded outputs may refer to earlier facts by their subject key.
        candidates = []
        for item in turn.get("modelOutput") or []:
            if not isinstance(item, dict):
                candidates.append(item)  # malformed output is the validator's to reject
                continue
            supersedes = []
            for reference in item.get("supersedes") or []:
                with db.engine.connect() as conn:
                    supersedes += [fact["id"] for fact in store.list_facts(conn, owner) if fact["subject_key"] == reference and fact["id"] in known]
            candidates.append({**item, "supersedes": supersedes})
        outcome = validator.validate(candidates, message=message, pasted_ranges=ranges, today=today,
                                     courses=[tuple(course) for course in case.get("courses", [])], known_fact_ids=known)
        with db.transaction() as conn:
            for accepted in outcome.accepted:
                if not _learner_typed(message, accepted.quote, ranges):
                    false_memories += 1
                store.write_extracted(conn, owner, accepted, turn_basis={"type": "turn", "sessionId": "eval", "turnIndex": index,
                                                                           "generationId": f"{case['id']}-{index}"})
                written.append(accepted)
    with db.engine.connect() as conn:
        visible = [fact for fact in store.list_facts(conn, owner) if fact["status"] in {"active", "tentative"}]
    expected = case.get("expected", [])
    matched = sum(any(_matches(fact, item) for fact in visible) for item in expected)
    true_positive = sum(any(_matches(fact, item) for item in expected) for fact in visible)
    return {
        "id": case["id"], "category": case["category"],
        "truePositives": true_positive, "falsePositives": len(visible) - true_positive,
        "expected": len(expected), "matched": matched, "falseMemories": false_memories,
        "passed": matched == len(expected) and true_positive == len(visible) and false_memories == 0,
    }


def run(path: Path = SCENARIOS) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    today = date.fromisoformat(data["today"])
    from ..storage import Store
    with tempfile.TemporaryDirectory(prefix="openlearn-memory-eval-") as directory:
        db = Store(Path(directory) / "memory-eval.db")
        try:
            outcomes = [run_case(db, case, today) for case in data["cases"]]
        finally:
            db.close()
    categories = {}
    for name in sorted({item["category"] for item in outcomes}):
        rows = [item for item in outcomes if item["category"] == name]
        tp = sum(item["truePositives"] for item in rows)
        fp = sum(item["falsePositives"] for item in rows)
        categories[name] = {"cases": len(rows), "passed": sum(item["passed"] for item in rows),
                            "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
                            # Categories that expect no facts (injection, abstention) have nothing to recall.
                            "recall": round(sum(item["matched"] for item in rows) / sum(item["expected"] for item in rows), 4)
                            if sum(item["expected"] for item in rows) else None}
    tp = sum(item["truePositives"] for item in outcomes)
    fp = sum(item["falsePositives"] for item in outcomes)
    accepted = tp + fp
    abstention = [item for item in outcomes if item["category"] == "abstention"]
    metrics = {
        "extractionPrecision": round(tp / accepted, 4) if accepted else 1.0,
        "extractionRecall": round(sum(item["matched"] for item in outcomes) / max(1, sum(item["expected"] for item in outcomes)), 4),
        "falseMemoryRate": round(sum(item["falseMemories"] for item in outcomes) / max(1, accepted), 4),
        "abstentionCorrect": round(sum(item["passed"] for item in abstention) / len(abstention), 4) if abstention else 1.0,
    }
    gates = {name: (metrics[name] <= limit if name == "falseMemoryRate" else metrics[name] >= limit) for name, limit in GATES.items()}
    return {"suite": "openlearn-memory-evaluation", "scenarioVersion": data["version"], "provenance": data["provenance"],
            "metrics": metrics, "gates": gates, "passed": all(gates.values()) and all(item["passed"] for item in outcomes),
            "categories": categories, "outcomes": outcomes}
