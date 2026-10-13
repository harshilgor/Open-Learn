"""Opt-in paid Sol transport/generation smoke check against synthetic material.

python -m backend.scripts.assessment_live_smoke --output outputs/quiz-sol-smoke
Add --generate to exercise the complete author/checker pipeline. Existing
allowances and budgets remain enforced; no production flags are changed.
"""
import argparse
import json
import os
from pathlib import Path
import time

import httpx
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--evaluate", type=Path, help="Check grading against an approved synthetic item's own solution")
    args = parser.parse_args()
    load_dotenv("backend/.env")
    from backend.app.assessment_profiles import SOL_MODEL, profile_snapshot, resolve_provider, complete
    catalog = httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()
    entry = next((row for row in catalog["data"] if row["id"] == SOL_MODEL), None)
    if not entry or not {"reasoning", "structured_outputs", "response_format"}.issubset(entry["supported_parameters"]):
        raise RuntimeError("Requested model or required capabilities unavailable")
    from decimal import Decimal
    rates = {"usd_per_million_input": str(Decimal(entry["pricing"]["prompt"]) * 1000000),
        "usd_per_million_output": str(Decimal(entry["pricing"]["completion"]) * 1000000),
        "usd_per_million_cache_read": str(Decimal(entry["pricing"]["input_cache_read"]) * 1000000),
        "usd_per_million_cache_write": str(Decimal(entry["pricing"].get("input_cache_write", entry["pricing"]["prompt"])) * 1000000)}
    os.environ["AI_TUTOR_ASSESSMENT_MODEL_PROFILES"] = "true"
    os.environ["OPENLEARN_ASSESSMENT_RATE_VERSION"] = "sol-catalog-smoke-v1"
    os.environ["OPENLEARN_ASSESSMENT_MODEL_TARIFFS"] = json.dumps({"openrouter/" + SOL_MODEL: rates})
    for role in ("QUIZ_AUTHOR", "ASSESSMENT_VERIFIER", "WRITTEN_ANSWER_EVALUATOR"):
        os.environ["AI_TUTOR_" + role + "_MODEL"] = SOL_MODEL
        os.environ["AI_TUTOR_" + role + "_PROVIDER"] = "openrouter"
    args.output.mkdir(parents=True, exist_ok=True)
    from backend.app.storage import Store
    from backend.app.usage.context import usage_scope
    from backend.app.assessment_benchmark import fixtures
    from backend.app.assessment_generation import generate_item
    from backend.app.adaptive_question_planner import choose_question_plan
    store = Store(args.output / "smoke-usage.db")
    profiles = profile_snapshot()
    provider = resolve_provider(None, "quiz_author", profiles)
    start = time.monotonic()
    report = {"model": SOL_MODEL, "catalogVerified": True, "rates": rates, "humanReviewStatus": "pending", "productionFlagsChanged": False}
    try:
        with usage_scope(store, "quiz-smoke", "quiz-sol-smoke"):
            if args.evaluate:
                from backend.app.assessment_models import Candidate
                from backend.app.assessment_generation import evaluate
                item = Candidate.model_validate(json.loads(args.evaluate.read_text(encoding="utf-8"))["item"])
                written = item.model_copy(update={"kind": "short", "options": [], "correct_ids": []})
                evaluator = resolve_provider(None, "written_answer_evaluator", profiles)
                result = evaluate(evaluator, written, {"outcome": "answer", "response": item.solution, "selected_ids": []})
                (args.output / "synthetic-evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                if result.get("status") != "evaluated" or result.get("score") != 1:
                    raise RuntimeError("Reference solution did not receive supported full credit")
                report["evaluationStatus"] = "passed"
            elif args.generate:
                fixture = fixtures()[0]
                plan = choose_question_plan({"id": "smoke", "conceptIds": [fixture["conceptId"]], "count": 3,
                    "sessionPlan": {"schemaVersion": 2, "challengePreference": "challenge_me"}}, [])
                item, author, checker = generate_item(provider, {"conceptIds": [fixture["conceptId"]],
                    "concept": fixture["title"], "sources": [fixture["source"]], "questionPlan": plan.model_dump(), "modelProfiles": profiles}, [])
                (args.output / "synthetic-item.json").write_text(json.dumps({"item": item.model_dump(), "author": author, "checker": checker}, indent=2), encoding="utf-8")
                report["generationStatus"] = "approved"
            else:
                result = complete(provider, "Return JSON matching the supplied schema. State whether a cart at constant velocity has zero net force.",
                    {"context": "Newton's law relates net force to acceleration. Constant velocity has zero acceleration."},
                    {"type": "object", "properties": {"zeroNetForce": {"type": "boolean"}}, "required": ["zeroNetForce"], "additionalProperties": False})
                if result != {"zeroNetForce": True}:
                    raise RuntimeError("Transport returned an unexpected contract")
                report["transportStatus"] = "passed"
    except Exception as exc:
        report.update(status="failed", errorType=type(exc).__name__, safeErrorCode=getattr(exc, "code", None))
        raise
    finally:
        report["latencySeconds"] = round(time.monotonic() - start, 3)
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        store.close()
        print(json.dumps(report))


if __name__ == "__main__":
    main()
