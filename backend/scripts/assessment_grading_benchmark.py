"""Metered grading comparison using educator-reviewed questions and references.

Input JSON: [{"id": str, "humanReviewed": true, "item": Candidate,
"responses": [{"id": str, "response": str, "expectedScore": number|null,
"expectedStatus": "evaluated"|"uncertain"}]}]. Never use unreviewed generated
rubrics as ground truth. Detailed output is private; summary contains no answers.
"""
import argparse
import json
from pathlib import Path
import time

from backend.app.assessment_models import Candidate
from backend.app.assessment_generation import evaluate
from backend.app.assessment_profiles import profile_snapshot, resolve_provider


def validate_cases(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
        raise ValueError("Supply between 1 and 100 reviewed questions")
    identifiers = set()
    for case in raw:
        if case.get("humanReviewed") is not True or not case.get("id") or case["id"] in identifiers:
            raise ValueError("Each question needs unique id and explicit human review")
        identifiers.add(case["id"])
        item = Candidate.model_validate(case["item"])
        if item.kind != "short" or not 1 <= len(case["responses"]) <= 20:
            raise ValueError("Use written questions with 1–20 reviewed responses")
        for answer in case["responses"]:
            score = answer["expectedScore"]
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1):
                raise ValueError("Reference scores must be null or between zero and one")
            if answer["expectedStatus"] not in {"evaluated", "uncertain"} or (score is None) != (answer["expectedStatus"] == "uncertain"):
                raise ValueError("Reference score and status must agree")
            if not answer.get("id") or not isinstance(answer.get("response"), str) or not 1 <= len(answer["response"]) <= 6000:
                raise ValueError("Every response needs an id and bounded text")
    return raw


def summarize(rows):
    result = {}
    for label in ("baseline", "candidate"):
        subset = [row for row in rows if row["configuration"] == label]
        scored = [row for row in subset if row["result"].get("score") is not None and row["expectedScore"] is not None]
        result[label] = {"count": len(subset), "scorePairs": len(scored),
            "meanAbsoluteScoreError": sum(abs(row["result"]["score"] - row["expectedScore"]) for row in scored) / len(scored) if scored else None,
            "statusAgreement": sum(row["result"]["status"] == row["expectedStatus"] for row in subset) / len(subset) if subset else None,
            "uncertainCount": sum(row["result"]["status"] == "uncertain" for row in subset),
            "unsupportedFullCredit": sum(row["result"].get("score") == 1 and row["expectedScore"] is not None and row["expectedScore"] < 1 for row in subset),
            "meanLatencySeconds": sum(row["latencySeconds"] for row in subset) / len(subset) if subset else None}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    try:
        cases = validate_cases(json.loads(args.input.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    profiles = profile_snapshot()
    if not profiles:
        parser.error("Configure enabled assessment profiles and reviewed tariffs first")
    from backend.app.model_provider import configured_lesson_provider
    from backend.app.storage import Store
    from backend.app.database import database_url
    from backend.app.usage.context import usage_scope
    store = Store(database_url())
    base = configured_lesson_provider()
    if base is None:
        parser.error("Connect the baseline provider before comparison")
    rows = []
    try:
        candidate = resolve_provider(base, "written_answer_evaluator", profiles)
        for case in cases:
            item = Candidate.model_validate(case["item"])
            for answer in case["responses"]:
                for label, provider in (("baseline", base), ("candidate", candidate)):
                    started = time.perf_counter()
                    with usage_scope(store, args.owner, f"grading-benchmark:{case['id']}:{answer['id']}:{label}"):
                        result = evaluate(provider, item, {"outcome": "answer", "response": answer["response"], "selected_ids": []})
                    rows.append({"caseId": case["id"], "responseId": answer["id"], "configuration": label,
                        "expectedScore": answer["expectedScore"], "expectedStatus": answer["expectedStatus"],
                        "result": result, "latencySeconds": time.perf_counter() - started})
    finally:
        store.close()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "private-grading-results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    report = {"reference": "educator-reviewed input", "costSource": "existing usage ledger", "configurations": summarize(rows)}
    (args.output / "grading-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
