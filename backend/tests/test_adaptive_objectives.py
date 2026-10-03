from backend.app.adaptive_question_planner import choose_question_plan
from backend.app.pedagogical_actions import select_teaching_action
from backend.app.unified_learner_state import reduce_capability


def test_coverage_reserves_final_questions_despite_repeated_failure():
    quiz = {"conceptIds": ["a", "b", "c"], "count": 5, "difficulty": "adaptive"}
    attempts = [{"conceptId": "a", "score": 0} for _ in range(3)]
    plan = choose_question_plan(quiz, attempts, diagnostic={"conceptId": "a"})
    assert plan.concept_id == "b"
    assert plan.objective == "missing_capability_evidence"
    assert plan.remaining_items == 2


def test_diagnostics_bounded_and_scope_locked():
    quiz = {"conceptIds": ["a"], "count": 5}
    attempts = [{"conceptId": "a", "questionPlan": {"objective": "distinguishing_check"}}] * 2
    assert choose_question_plan(quiz, attempts, diagnostic={"conceptId": "a"}).objective != "distinguishing_check"
    assert choose_question_plan(quiz, [], diagnostic={"conceptId": "outside"}).concept_id == "a"


def test_assisted_success_requests_fresh_independent_check_and_family():
    plan = choose_question_plan({"conceptIds": ["a"], "count": 3},
        [{"conceptId": "a", "score": 1, "assisted": True}], previous=[{"family": "same_structure"}])
    assert plan.objective == "independent_verification"
    assert plan.excluded_families == ["same_structure"]


def test_direct_request_overrides_supported_hypothesis():
    action = select_teaching_action("Explain this directly", "learn", hypothesis={"action": "prerequisite_repair"})
    assert action.action == "direct_explanation"


def test_hint_disclosure_limit_and_loop_exit():
    assert select_teaching_action("Just a hint", "ask").disclosure_limits
    action = select_teaching_action("", "learn", history=[{"productive": False}] * 3)
    assert action.action == "worked_example"
    assert "unproductive_loop_bound" in action.reason_codes


def test_exposure_skip_uncertain_and_assisted_are_not_demonstration():
    entries = [{"id": str(i), "occurredAt": "2026-10-01T00:00:00+00:00", "category": category,
        "outcome": "correct", "assistance": "assisted", "familyId": "f", "sessionId": "s",
        "attributionResolved": True} for i, category in enumerate(["exposure", "skip", "excluded", "assisted_correct"])]
    state = reduce_capability(entries)
    assert state["state"] != "demonstrated"
    assert state["independentSuccessIds"] == []


def test_late_occurrence_replay_deterministic_and_retention_needs_delay():
    entries = [{"id": str(i), "occurredAt": date, "category": "independent_correct", "outcome": "correct",
        "assistance": "independent", "familyId": str(i), "sessionId": str(i), "attributionResolved": True}
        for i, date in enumerate(["2026-10-01T00:00:00+00:00", "2026-10-02T12:00:00+00:00"])]
    assert reduce_capability(entries) == reduce_capability(list(reversed(entries)))
    state = reduce_capability(entries)
    assert state["delayedRetrievalCount"] == 1
    assert state["demonstrationCandidate"] is True
    assert state["state"] == "developing"
    assert "demonstration_policy_pending_validation" in state["reasonCodes"]
