import pytest

from backend.app.classification.jev import JevClientError, JevDecisionClient, JevResult, choice
from backend.app.classification.service import ClassificationDecision, ClassificationService
from backend.app.agent_execution.admission import classify_message
from backend.app.learning_kernel import classify_intent
from backend.app.session_models import TeachingActionInput, TeachingIntent
from backend.app.web_evidence.lifecycle import EvidenceOutcome, classify_evidence_outcome
from backend.app.browser_assistant.intent import compile_intent
from backend.app.reminder_intent import compile_reminder


class StubClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def decide(self, contract, version, state, questions):
        self.calls.append((contract, version, state, questions))
        return JevResult(self.answers, version, "typesafe/jev-test", "request-test", 12, 1)


def _choice(value, probabilities):
    return {"type": "choice", "choice": value, "probabilities": probabilities}


def test_mode_contract_batches_workflow_and_request_timing():
    client = StubClient({
        "workflow": _choice("quiz", {"ask": 0.02, "learn": 0.01, "quiz": 0.95, "none": 0.02}),
        "request_type": _choice("explicit", {"explicit": 0.93, "implicit": 0.04, "none": 0.03}),
        "quiz_now": {"type": "noul", "noul": 0.96},
        "quiz_discussed_or_deferred": {"type": "noul", "noul": 0.01},
    })

    result = ClassificationService(client).mode_intent(
        "Can you test what I remember?", current_mode="ask", available_modes=["ask", "learn", "quiz"],
        recent_turns=[{"learner": "We reviewed this topic.", "assistant": "A short explanation."}],
        topic="Attention",
    )

    contract, version, state, questions = client.calls[0]
    assert (contract, version) == ("mode_intent", "mode-intent-v4")
    assert set(questions) == {"workflow", "request_type", "quiz_now", "quiz_discussed_or_deferred"}
    assert state["latest_message"] == "Can you test what I remember?"
    assert result.workflow == "quiz"
    assert result.request_type == "explicit"
    assert result.score == pytest.approx(0.93)
    assert result.quiz_now == pytest.approx(0.96)


def test_choice_contract_rejects_unrecognized_model_label():
    with pytest.raises(JevClientError, match="invalid_answer"):
        choice({"choice": "execute_action", "confidence": 1.0}, {"direct_answer", "none"})


def test_choice_contract_requires_selected_label_probability_not_distribution_confidence():
    with pytest.raises(JevClientError, match="invalid_score"):
        choice({"type": "choice", "choice": "direct_answer", "confidence": 0.99}, {"direct_answer", "none"})


def test_noul_contract_requires_typed_probability():
    from backend.app.classification.jev import noul

    with pytest.raises(JevClientError, match="invalid_answer"):
        noul({"confidence": 0.99})


def test_jev_client_settles_with_openrouter_cost_receipt(monkeypatch):
    settled = []
    class Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"answers": {"route": {"type": "choice", "choice": "direct_answer"}},
                    "usage": {"cost": 0.000014994}, "id": "gen-dec-test"}

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(JevDecisionClient, "_begin_usage", staticmethod(lambda model: "ticket"))
    monkeypatch.setattr(JevDecisionClient, "_finish_usage", staticmethod(
        lambda ticket, cost, receipt: settled.append((ticket, cost, receipt))))
    monkeypatch.setattr("backend.app.classification.jev.httpx.post", lambda *args, **kwargs: Response())

    result = JevDecisionClient().decide("turn_route", "turn-route-v1", {"message": "hello"}, {})

    assert result.provider_cost_nano == 14_994
    assert settled == [("ticket", 14_994, "gen-dec-test")]


def test_missing_jev_cost_receipt_retains_reserved_estimate():
    assert JevDecisionClient._usage_receipt({"answers": {}}) == (None, None)


def test_active_mode_classifier_failure_does_not_call_a_second_model(monkeypatch):
    from backend.app.mode_transition_service import ModeTransitionService

    class Provider:
        def complete_json(self, *args, **kwargs):
            raise AssertionError("JEV failure must not invoke a different model classifier")

    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "active")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "hybrid")
    monkeypatch.setattr(ClassificationService, "mode_intent", lambda *args, **kwargs:
        (_ for _ in ()).throw(JevClientError("key_unavailable")))

    result = ModeTransitionService(None).classify(
        "This topic is confusing to me.", [], "ask", provider=Provider())

    assert result.decision == "stay"
    assert result.classification_source == "fallback"


def test_active_turn_route_uses_jev_label(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "active")
    monkeypatch.setattr(ClassificationService, "turn_route", lambda self, message, context=None:
        ClassificationDecision("turn_route", "turn-route-v1", "browser_academic", 0.94,
                               {"browser_academic": 0.94}, "r", "jev-test", 10))

    result = classify_message("Could you take a look at my university portal?")

    assert result.kind == "browser"


def test_shadow_turn_route_never_changes_current_behavior(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "shadow")
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_SHADOW_SAMPLE_RATE", "1")
    monkeypatch.setattr(ClassificationService, "turn_route", lambda self, message, context=None:
        ClassificationDecision("turn_route", "turn-route-v1", "research", 0.99,
                               {"research": 0.99}, "r", "jev-test", 10))

    result = classify_message("Can you explain what a derivative is?")

    assert result.kind == "direct"


def test_active_teaching_intent_uses_jev_class(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_TEACHING_INTENT_MODE", "active")
    monkeypatch.setattr(ClassificationService, "teaching_intent", lambda self, message, context=None:
        ClassificationDecision("teaching_intent", "teaching-intent-v1", "example", 0.96,
                               {"example": 0.96}, "r", "jev-test", 10))

    result = classify_intent(TeachingActionInput(message="Use a concrete case for me"))

    assert result == TeachingIntent.example


def test_active_evidence_classifier_uses_high_confidence_jev_label(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_EVIDENCE_OUTCOME_MODE", "active")
    monkeypatch.setattr(ClassificationService, "evidence_outcome", lambda self, excerpts:
        ClassificationDecision("evidence_outcome", "evidence-outcome-v1", "conflicting_evidence", 0.97,
                               {"conflicting_evidence": 0.97}, "r", "jev-test", 10))

    result = classify_evidence_outcome(["A directly relevant excerpt.", "A conflicting relevant excerpt."])

    assert result == EvidenceOutcome.conflicting_evidence


def test_active_browser_classifier_can_abstain_from_browser_route(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_BROWSER_TASK_MODE", "active")
    monkeypatch.setattr(ClassificationService, "browser_task", lambda self, message, context=None: {
        "task": "none", "task_score": 0.96, "save_requested": False, "save_score": 0.01,
        "reminder_requested": False, "reminder_score": 0.01, "request_id": "r",
        "model": "jev-test", "latency_ms": 10,
    })

    result = compile_intent("Could you explain derivatives?", provider=None)

    assert result.handled is False


def test_active_browser_route_supports_prompts_outside_keyword_prefilter(monkeypatch):
    from backend.app.browser_assistant.contracts import TaskIntent

    class Provider:
        calls = 0

        def complete_json(self, *args, **kwargs):
            self.calls += 1
            return TaskIntent(goal="Inspect the school portal", operations=["browse", "summarize"],
                              source_alias="School portal").model_dump(by_alias=True)

    monkeypatch.setenv("OPENLEARN_CLASSIFIER_BROWSER_TASK_MODE", "active")
    monkeypatch.setattr(ClassificationService, "browser_task", lambda self, message, context=None: {
        "task": "browse_summarize", "task_score": 0.96, "save_requested": False,
        "save_score": 0.01, "reminder_requested": False, "reminder_score": 0.01,
        "request_id": "r", "model": "jev-test", "latency_ms": 10,
    })
    provider = Provider()

    result = compile_intent("Please inspect the school's online portal for my syllabus outline", provider=provider)

    assert provider.calls == 1
    assert result.handled is True
    assert result.operations == ["browse", "summarize"]


def test_active_reminder_classifier_refuses_wrong_operation(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_REMINDER_ACTION_MODE", "active")
    monkeypatch.setattr(ClassificationService, "reminder_action", lambda self, message, scope=None: {
        "action": "list", "action_score": 0.98, "kind": "none", "kind_score": 0.98,
        "activity": "none", "activity_score": 0.98, "request_id": "r",
        "model": "jev-test", "latency_ms": 10,
    })

    result = compile_reminder("remind me about something", {}, provider=object())

    assert "clarification" in result


def test_concept_candidates_select_only_a_strong_separated_candidate(monkeypatch):
    monkeypatch.delenv("OPENLEARN_CLASSIFIER_CONCEPT_CANDIDATE_SELECT_SCORE", raising=False)
    client = StubClient({
        "candidate_0": {"type": "noul", "noul": 0.95},
        "candidate_1": {"type": "noul", "noul": 0.06},
    })

    result = ClassificationService(client).concept_candidates("mitosis", [
        {"id": "concept_1", "title": "Cell division", "definition": "How cells divide."},
        {"id": "concept_2", "title": "Meiosis", "definition": "Reduction division."},
    ])

    assert result["concept_id"] == "concept_1"
    assert result["candidate_scores"]["concept_1"] == 0.95


def test_mode_scope_override_beats_global_rollout(monkeypatch):
    from backend.app.classification.config import rollout_mode

    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "active")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "off")

    assert rollout_mode("mode_intent") == "off"
    assert rollout_mode("turn_route") == "active"
