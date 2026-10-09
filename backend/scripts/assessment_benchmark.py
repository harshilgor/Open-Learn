"""Export synthetic cases and blinded review forms; live generation is opt-in.

python -m backend.scripts.assessment_benchmark --output outputs/quiz-benchmark
python -m backend.scripts.assessment_benchmark --live --owner OWNER --limit 6 --output backend/data/quiz-benchmark
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import time

from backend.app.assessment_benchmark import fixtures
from backend.app.assessment_generation import generate_item
from backend.app.assessment_profiles import profile_snapshot
from backend.app.adaptive_question_planner import choose_question_plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--owner")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261009)
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("limit must be between 1 and 30")
    if args.live and not args.owner:
        parser.error("live runs require an authorized owner for usage accounting")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = fixtures()[:args.limit]
    (args.output / "fixtures.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    artifacts = []
    if args.live:
        from backend.app.model_provider import configured_lesson_provider
        from backend.app.storage import Store
        from backend.app.database import database_url
        from backend.app.usage.context import usage_scope
        store = Store(database_url())
        provider = configured_lesson_provider()
        profiles = profile_snapshot()
        if not profiles:
            parser.error("Enable and configure assessment model profiles before comparison")
        try:
            for case in cases:
                quiz = {"id": case["id"], "conceptIds": [case["conceptId"]], "count": 5,
                    "sessionPlan": {"schemaVersion": 2, "challengePreference": case["challengePreference"], "feedbackPolicy": "practice_immediate"}}
                plan = choose_question_plan(quiz, [])
                plan.reasoning_task = case["task"]
                context = {"conceptIds": [case["conceptId"]], "concept": case["title"], "sources": [case["source"]], "questionPlan": plan.model_dump()}
                for label, role_profiles in (("baseline", {}), ("candidate", profiles)):
                    started = time.perf_counter()
                    with usage_scope(store, args.owner, "benchmark:" + case["id"] + ":" + label):
                        try:
                            item, author, checker = generate_item(provider, {**context, "modelProfiles": role_profiles}, [])
                            artifact = {"caseId": case["id"], "configuration": label, "item": item.model_dump(), "author": author, "checker": checker, "status": "approved"}
                        except Exception as exc:
                            artifact = {"caseId": case["id"], "configuration": label, "status": "failed", "errorType": type(exc).__name__}
                    artifact["latencySeconds"] = time.perf_counter() - started
                    artifacts.append(artifact)
        finally:
            store.close()
    random.Random(args.seed).shuffle(artifacts)
    private_mapping = []
    with (args.output / "blind-review.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = ["reviewId", "caseId", "stem", "options", "solution", "rubric", "correctness", "clarity", "conceptualDepth", "challengeAlignment", "distractorQuality", "rubricFairness", "reviewer", "comments"]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index, artifact in enumerate(artifacts):
            review_id = hashlib.sha256(f"{args.seed}:{index}".encode()).hexdigest()[:12]
            private_mapping.append({"reviewId": review_id, **artifact})
            item = artifact.get("item", {})
            writer.writerow({"reviewId": review_id, "caseId": artifact["caseId"], "stem": item.get("stem", "Generation failed"), "options": json.dumps(item.get("options", [])), "solution": item.get("solution", ""), "rubric": json.dumps(item.get("criteria", []))})
    (args.output / "private-artifacts.json").write_text(json.dumps(private_mapping, indent=2), encoding="utf-8")
    report = {"fixtureCount": len(cases), "live": args.live, "approved": sum(a["status"] == "approved" for a in artifacts),
        "humanReviewStatus": "pending", "educationalImprovement": "not_measured", "costSource": "existing usage ledger for live runs",
        "gradingEvaluation": "fixtures exported; human reference grading must use a reviewed question and rubric, not an unrelated generated item"}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
