"""Offline deterministic policy regression runner; it has no provider dependency."""
from __future__ import annotations
import json
from pathlib import Path
from .assessment_generation import deterministic_quality_failures
from .assessment_models import Candidate, Criterion, Option
from .adaptive_question_planner import choose_question_plan
from .pedagogical_actions import select_teaching_action
from .unified_learner_state import reduce_capability
FIXTURES = Path(__file__).resolve().parents[1] / "evaluation" / "fixtures.json"
OPENLEARN_FIXTURES = Path(__file__).resolve().parents[1] / "evaluation" / "openlearn_scenarios.json"


def _openlearn_scenarios(fixtures: Path) -> list[dict]:
    """Run labeled synthetic policy cases separately from content/outcome metrics."""
    data = json.loads(fixtures.read_text(encoding="utf-8"))
    results = []
    for case in data["teachingPolicy"]:
        actual = select_teaching_action(case["intent"], case["workflow"],
            hypothesis=case.get("hypothesis"), history=case.get("history", [])).action
        results.append({"id": case["id"], "category": "policy", "source": "labeled_synthetic",
                        "expected": case["expected"], "actual": actual, "passed": actual == case["expected"]})
    for case in data["questionPlanning"]:
        actual = choose_question_plan(case["quiz"], case.get("attempts", []),
            states=case.get("states", []), previous=case.get("previous", []),
            diagnostic=case.get("diagnostic")).objective
        results.append({"id": case["id"], "category": "policy", "source": "labeled_synthetic",
                        "expected": case["expected"], "actual": actual, "passed": actual == case["expected"]})
    for case in data["learnerState"]:
        actual = reduce_capability(case["events"])
        observed = {"state": actual["state"], "independentSuccessCount": len(actual["independentSuccessIds"]),
                    "delayedRetrievalCount": actual["delayedRetrievalCount"]}
        passed = all(observed[key] == expected for key, expected in case["expected"].items())
        results.append({"id": case["id"], "category": "state_admission", "source": "labeled_synthetic",
                        "expected": case["expected"], "actual": observed, "passed": passed})
    return results


def run(fixtures: Path = FIXTURES) -> dict:
    data = json.loads(fixtures.read_text(encoding="utf-8")); results=[]
    results.append({"id":"recommendation-next-action","passed":data["recommendation"]["expectedNext"] == "backpropagation" and "quiz-without-material" in data["recommendation"]["unavailable"]})
    note=data["noteContext"]; excerpt=note["body"][note["start"]:note["end"]]
    results.append({"id":"note-context-boundary","passed":excerpt == note["expected"] and "IGNORE" not in excerpt})
    a=data["assessment"]; item=Candidate(concept_id="c",family="arithmetic",kind="single",stem="Which claim is correct: " + a["duplicateStem"],reasoning_target="Infer a result from the addition rule.",options=[Option(id="a",label="Four"),Option(id="b",label="Five")],correct_ids=["a"],solution="Two plus two equals four by ordinary integer addition.",criteria=[Criterion(id="result",description="Identifies the supported result.",weight=1)],hints=["Add the two values."],source_ids=["owned-span"])
    results.append({"id":"assessment-quality","passed":a["expectedFailure"] in deterministic_quality_failures(item,[{"spanId":"owned-span"}],[{"stem":"Which claim is correct: " + a["previousStem"],"family":"arithmetic"}])})
    grading=data["grading"]; results.append({"id":"grading-contract","passed":float(set(grading["selected"]) == set(grading["correct"])) == grading["expectedScore"]})
    source=data["sourceSupport"]; results.append({"id":"source-support","passed":set(source["candidateSources"]).issubset(source["allowedSources"]) == source["expectedSupported"]})
    results.append({"id":"false-mastery","passed":data["falseMastery"]["event"] == "recommendation_selection" and not data["falseMastery"]["expectedStateWrite"]})
    for item in results:
        item.update(category="existing_regression", source="synthetic_fixture")
    scenarios = _openlearn_scenarios(OPENLEARN_FIXTURES)
    outcomes = results + scenarios
    category_counts = {category: {"total": sum(x["category"] == category for x in outcomes),
                                  "passed": sum(x["category"] == category and x["passed"] for x in outcomes)}
                       for category in sorted({x["category"] for x in outcomes})}
    return {"suite":"openlearn-deterministic-evaluation","fixtureVersion":data["version"],
            "scenarioVersion": json.loads(OPENLEARN_FIXTURES.read_text(encoding="utf-8"))["version"],
            "passed":all(x["passed"] for x in outcomes), "categories": category_counts, "outcomes":outcomes}
if __name__ == "__main__": print(json.dumps(run(),sort_keys=True))
