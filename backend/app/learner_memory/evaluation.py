"""Deterministic learner-memory evaluation (spec §11.3).

Replays recorded extraction outputs through the real validator and store.
No provider is called, so results are stable in CI. Phase C covers the
extraction categories, Phase D retrieval, and Phase E forgetting.
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
            retrieval_report = run_retrieval(db)
            forgetting_report = run_forgetting(db)
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
    # Extraction cases must all pass; retrieval is gated on aggregate recall,
    # so a documented hard case (e.g. a synonym) can miss without failing CI.
    return {"suite": "openlearn-memory-evaluation", "scenarioVersion": data["version"], "provenance": data["provenance"],
            "metrics": metrics, "gates": gates,
            "passed": all(gates.values()) and all(item["passed"] for item in outcomes) and retrieval_report["passed"] and forgetting_report["passed"],
            "categories": categories, "outcomes": outcomes, "retrieval": retrieval_report, "forgetting": forgetting_report}


# --- Phase D: retrieval categories (§11.3 categories 1–4 and abstention) -------

RETRIEVAL_SCENARIOS = Path(__file__).resolve().parents[2] / "evaluation" / "memory_retrieval_scenarios.json"
RETRIEVAL_GATES = {"recallAt5.single_fact_recall": 0.8, "recallAt5.knowledge_update_recall": 0.8,
                   "recallAt5.temporal": 0.8, "retrievalAbstentionCorrect": 0.95,
                   # §2 rule 5 is a hard rule: every assessment case must pass.
                   "assessmentIsolationCorrect": 1.0}
ASSESSMENT_KINDS = {"preference", "constraint"}


def _seed_fact(conn, owner, item, now):
    from sqlalchemy import text as sql
    from . import policy as memory_policy
    learned = now - float(item.get("days_ago", 1)) * 86400
    importance = memory_policy.DEFAULT_IMPORTANCE.get(item["kind"], 0.5)
    conn.execute(sql(f"""INSERT INTO memory_facts({store.FACT_COLUMNS}) VALUES(:owner,:id,:kind,:statement,:subject,NULL,'[]',:event_date,
        'user_stated',:status,:false,0.9,:importance,:learned,:learned,NULL,NULL,'[]',NULL,0,NULL,:stability,:false,'eval',1)"""),
        {"owner": owner, "id": item["key"], "kind": item["kind"], "statement": item["statement"],
         "subject": item.get("subject") or f"{item['kind']}:{item['key']}", "event_date": item.get("event_date"),
         "status": item.get("status", "active"), "false": False, "importance": importance, "learned": learned,
         "stability": 30 * (1 + 2 * importance)})


def _seed_episode(conn, owner, item, now):
    from sqlalchemy import text as sql
    end = now - float(item["days_ago"]) * 86400
    conn.execute(sql("""INSERT INTO memory_episodes(owner_id,id,session_id,course_id,period_start,period_end,turn_range,summary,topics,method,basis,status,created_at,revision)
        VALUES(:owner,:id,'eval',NULL,:start,:end,'{}',:summary,'[]','extractive-v1','[]','active',:end,1)"""),
        {"owner": owner, "id": item["key"], "start": end - 3600, "end": end, "summary": item["summary"]})


def run_retrieval(db, path: Path = RETRIEVAL_SCENARIOS) -> dict:
    from datetime import datetime
    from ..context_engine import estimate_tokens
    from .service import LearnerMemoryService
    data = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["now"]).timestamp()
    service = LearnerMemoryService(db)
    outcomes = []
    for case in data["cases"]:
        owner = "eval_retrieval_" + case["id"]
        with db.transaction() as conn:
            for item in data["commonFacts"] + case.get("facts", []):
                _seed_fact(conn, owner, item, now)
            for item in case.get("episodes", []):
                _seed_episode(conn, owner, item, now)
        purpose = case.get("purpose", "teaching")
        result = service.context(owner, None, case["query"], purpose=purpose, now=now, timezone_name=data["timezone"])
        included = sorted((result.trace["included"] if result else []), key=lambda item: -item["score"])
        top = [item["id"] for item in included[:5]]
        relevant = set(case["relevant"])
        forbidden = set(case.get("forbidden", []))
        hits = len(relevant & set(top))
        outcome = {"id": case["id"], "category": case["category"], "relevant": len(relevant), "hitsAt5": hits,
                   "included": len(included), "relevantIncluded": len(relevant & {item["id"] for item in included}),
                   "forbiddenIncluded": len(forbidden & {item["id"] for item in included}),
                   "memoryTokens": estimate_tokens(result.text) if result else 0, "hard": case.get("hard")}
        if purpose == "assessment":
            kinds = {item["key"]: item["kind"] for item in data["commonFacts"] + case.get("facts", [])}
            text = result.text if result else ""
            outcome["passed"] = not result or (not result.episode_ids and all(kinds.get(identifier) in ASSESSMENT_KINDS for identifier in result.fact_ids)
                                                 and "Relevant memories:" not in text and "Earlier sessions:" not in text
                                                 and "Upcoming course dates:" not in text and "Learner progress:" not in text)
        else:
            outcome["passed"] = (hits == len(relevant) and not outcome["forbiddenIncluded"]) if relevant else outcome["included"] == 0
        outcomes.append(outcome)
    categories = {}
    for name in sorted({item["category"] for item in outcomes}):
        rows = [item for item in outcomes if item["category"] == name]
        relevant_total = sum(item["relevant"] for item in rows)
        included_total = sum(item["included"] for item in rows)
        categories[name] = {"cases": len(rows), "passed": sum(item["passed"] for item in rows),
                            "recallAt5": round(sum(item["hitsAt5"] for item in rows) / relevant_total, 4) if relevant_total else None,
                            "precision": round(sum(item["relevantIncluded"] for item in rows) / included_total, 4) if included_total else None,
                            "meanMemoryTokens": round(sum(item["memoryTokens"] for item in rows) / len(rows), 1)}
    abstention = [item for item in outcomes if item["category"] == "retrieval_abstention"]
    metrics = {f"recallAt5.{name}": row["recallAt5"] for name, row in categories.items() if row["recallAt5"] is not None}
    metrics["retrievalAbstentionCorrect"] = round(sum(item["passed"] for item in abstention) / len(abstention), 4) if abstention else 1.0
    isolation = [item for item in outcomes if item["category"] == "assessment_isolation"]
    metrics["assessmentIsolationCorrect"] = round(sum(item["passed"] for item in isolation) / len(isolation), 4) if isolation else 0.0
    gates = {name: (metrics.get(name) or 0) >= limit for name, limit in RETRIEVAL_GATES.items()}
    return {"scenarioVersion": data["version"], "provenance": data["provenance"], "metrics": metrics, "gates": gates,
            "passed": all(gates.values()), "categories": categories, "outcomes": outcomes}


# --- Phase E: forgetting (§11.3 category 9) -------------------------------------------

FORGETTING_SCENARIOS = Path(__file__).resolve().parents[2] / "evaluation" / "memory_forgetting_scenarios.json"
# Forgetting is policy, not ranking: every case must match exactly, and no
# fact the learner stated or confirmed may ever be deleted for disuse.
FORGETTING_GATES = {"forgettingCorrect": 1.0, "learnerStatedDeleted": 0}


def _seed_forgetting_fact(conn, owner, item, now):
    from sqlalchemy import text as sql
    from . import policy as memory_policy
    day = 86400
    learned = now - float(item.get("days_ago", 1)) * day
    importance = memory_policy.DEFAULT_IMPORTANCE.get(item["kind"], 0.5)
    ago = lambda key: now - float(item[key]) * day if key in item else None  # noqa: E731
    conn.execute(sql(f"""INSERT INTO memory_facts({store.FACT_COLUMNS}) VALUES(:owner,:id,:kind,:statement,:subject,NULL,'[]',:event_date,
        :origin,:status,:false,0.9,:importance,:learned,:learned,NULL,NULL,'[]',:last_used,:uses,:confirmed,:stability,:false,'eval',1)"""),
        {"owner": owner, "id": item["key"], "kind": item["kind"], "statement": item["statement"],
         "subject": item.get("subject") or f"{item['kind']}:{item['key']}", "event_date": item.get("event_date"),
         "origin": item.get("origin", "user_stated"), "status": item.get("status", "active"), "false": False, "importance": importance,
         "learned": learned, "last_used": ago("last_used_days_ago"), "uses": item.get("use_count", 0), "confirmed": ago("confirmed_days_ago"),
         "stability": item.get("stability") or store.initial_stability(importance)})


def run_forgetting(db, path: Path = FORGETTING_SCENARIOS) -> dict:
    from datetime import datetime
    from sqlalchemy import text as sql
    from . import consolidation, profile
    data = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["now"]).timestamp()
    outcomes = []
    for case in data["cases"]:
        owner = "eval_forgetting_" + case["id"]
        with db.transaction() as conn:
            for item in case.get("facts", []):
                _seed_forgetting_fact(conn, owner, item, now)
            for item in case.get("episodes", []):
                _seed_episode(conn, owner, item, now)
        learner_stated = {item["key"] for item in case.get("facts", [])
                          if item.get("origin", "user_stated") in {"user_stated", "user_confirmed"} and item.get("status") != "shadow"}
        consolidation.consolidate(db, owner, now=now + float(case.get("advanceDays", 0)) * 86400)
        with db.engine.connect() as conn:
            found = dict(conn.execute(sql("SELECT id,status FROM memory_facts WHERE owner_id=:owner"), {"owner": owner}).all())
            found.update(conn.execute(sql("SELECT id,status FROM memory_episodes WHERE owner_id=:owner"), {"owner": owner}).all())
            built = profile.stored(conn, owner) or {"factIds": []}
        actual = {key: found.get(key, "deleted") for key in case["expected"]}
        mismatches = {key: actual[key] for key, expected in case["expected"].items() if actual[key] != expected}
        profile_ok = "profile" not in case or built["factIds"] == case["profile"]
        deleted = sorted(key for key in learner_stated if key not in found)
        outcomes.append({"id": case["id"], "passed": not mismatches and profile_ok and not deleted,
                         "mismatches": mismatches, "profileMatches": profile_ok, "learnerStatedDeleted": len(deleted)})
    metrics = {"forgettingCorrect": round(sum(item["passed"] for item in outcomes) / len(outcomes), 4) if outcomes else 0.0,
               "learnerStatedDeleted": sum(item["learnerStatedDeleted"] for item in outcomes)}
    gates = {"forgettingCorrect": metrics["forgettingCorrect"] >= FORGETTING_GATES["forgettingCorrect"],
             "learnerStatedDeleted": metrics["learnerStatedDeleted"] <= FORGETTING_GATES["learnerStatedDeleted"]}
    return {"scenarioVersion": data["version"], "provenance": data["provenance"], "metrics": metrics, "gates": gates,
            "passed": all(gates.values()), "cases": len(outcomes), "outcomes": outcomes}
