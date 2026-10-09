from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.storage import Store
from backend.app.models import Concept, Edge, GraphVersion, TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.mode_transition_service import ModeTransitionService
from backend.app.mode_transition_models import ModeTransitionInteraction
from backend.app.learning_routes import build_learning_router
from backend.app.material_routes import material_owner
from backend.app.usage.context import usage_scope
import json
import httpx
from pathlib import Path
from uuid import uuid4
import pytest


@pytest.fixture(autouse=True)
def disable_unrelated_classification_rollouts(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "off")


def _setup_test_db(tmp_path):
    if tmp_path is None:
        test_path = Path(__file__).resolve().parents[1] / "data" / f"test_mode_transition_{uuid4().hex}.db"
        store = Store(test_path)
        store._usage_test_path = test_path
    else:
        store = Store(tmp_path / "test_mode_transition.db")
    scope = TopicScope(
        id="scope-ai",
        topic="Machine Learning",
        resolved_meaning="Machine Learning",
        objective="Learn",
        depth="introductory",
        created_at=utc_now(),
    )
    store.save_scope(scope)
    graph = GraphVersion(
        id="graph-ai",
        scope_id=scope.id,
        title="Machine Learning",
        description="Core concepts",
        publication_state="published",
        trust_summary="",
        generated_by="test",
        created_at=utc_now(),
        concepts=[
            Concept(id="attention", title="Attention Mechanism", label="", summary="", objective=""),
            Concept(id="backprop", title="Backpropagation", label="", summary="", objective=""),
        ],
        edges=[],
    )
    store.save_graph(graph)
    session = LearningSession(
        id="session-trans-1",
        learner_id="local",
        graph_id=graph.id,
        current_concept_id="attention",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    store.save_session(session)
    return store, session


def _close_test_db(store):
    test_path = getattr(store, "_usage_test_path", None)
    store.close()
    if test_path is not None:
        test_path.unlink(missing_ok=True)
        Path(str(test_path) + "-wal").unlink(missing_ok=True)
        Path(str(test_path) + "-shm").unlink(missing_ok=True)


def _add_quiz_attempts(store, session_id, attempts):
    quiz_id = "quiz-transition-fixture"
    ids = [item["id"] for item in attempts]
    quiz = {"id": quiz_id, "sessionId": session_id, "attempts": ids}
    from backend.app.workflow_store import WorkflowStore
    records = WorkflowStore(store)
    with store.transaction() as conn:
        existing = records.read("local", quiz_id, "quiz", conn) if conn.execute(
            text("SELECT 1 FROM practice_records WHERE id=:id AND owner_id='local'"), {"id": quiz_id}
        ).first() else None
        if existing:
            quiz.update({key: value for key, value in existing.items() if key not in {"id", "revision"}})
            quiz["attempts"] = list(dict.fromkeys([*quiz.get("attempts", []), *ids]))
        records.put(conn, "local", "quiz", quiz, session_id,
                    expected=existing["revision"] if existing else None)
        for item in attempts:
            item = {"quizId": quiz_id, "conceptId": "attention", "assisted": False, "status": "evaluated",
                    "outcome": "answer", "score": 0.0, "createdAt": utc_now().isoformat(), **item}
            records.put(conn, "local", "attempt", item, quiz_id)


def test_explicit_learn_signals(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)

    learn_prompts = [
        "Teach me this from the beginning.",
        "I want to actually understand this.",
        "Can you build this up step by step?",
        "Can you teach me backpropagation from the beginning and make sure I understand it?",
        "I don't want just an answer; I want to understand it.",
    ]

    for prompt in learn_prompts:
        result = service.evaluate_intent(
            current_message=prompt,
            recent_turns=[],
            current_mode="ask",
            session_id=session.id,
            concept_title="Attention Mechanism",
            concept_id="attention",
        )
        assert result.intent == "learn", f"Failed for: {prompt}"
        assert result.confidence >= 0.85, f"Low confidence for: {prompt}"
        assert result.target_mode == "learn", f"Wrong target for: {prompt}"
        assert result.decision == "request_transition"
        assert result.suggestion is not None
        assert result.suggestion.action_label == "Continue in Learn"

    store.close()


def test_explicit_quiz_signals(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)

    quiz_prompts = [
        "Quiz me on this.",
        "Test my understanding.",
        "Can you give me practice questions?",
        "Don't tell me the answer; ask me questions.",
        "I want to see if I actually remember this.",
    ]

    for prompt in quiz_prompts:
        result = service.evaluate_intent(
            current_message=prompt,
            recent_turns=[],
            current_mode="ask",
            session_id=session.id,
            concept_title="Attention Mechanism",
            concept_id="attention",
        )
        assert result.intent == "quiz", f"Failed for: {prompt}"
        assert result.confidence >= 0.85, f"Low confidence for: {prompt}"
        assert result.target_mode == "quiz", f"Wrong target for: {prompt}"
        assert result.decision == "request_transition"
        assert result.suggestion is not None
        assert "Quiz" in result.suggestion.action_label

    store.close()


def test_anti_signals_do_not_trigger_learn_or_quiz(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)

    anti_prompts = [
        "Why?",
        "Why does this happen?",
        "Can you explain that?",
        "Can you give me an example?",
        "I'm confused about this one part.",
        "Can you go deeper?",
        "Can you explain it more simply?",
        "What does this term mean?",
        "Just give me the answer.",
        "Keep it quick.",
        "Explain this quiz question.",
        "I have a quiz tomorrow.",
        "Don't quiz me yet.",
        "My professor said ‘quiz me’ is a useful prompt.",
        "Help me prepare for Friday.",
        "Quiz me afterward, but explain it first.",
    ]

    for prompt in anti_prompts:
        result = service.evaluate_intent(
            current_message=prompt,
            recent_turns=[],
            current_mode="ask",
            session_id=session.id,
            concept_title="Attention Mechanism",
            concept_id="attention",
        )
        assert result.target_mode is None, f"Should NOT trigger mode change for: {prompt}"
        assert result.suggestion is None, f"Should NOT have suggestion for: {prompt}"

    store.close()


def test_direct_answer_preference_returns_from_learn_to_ask(tmp_path):
    store, session = _setup_test_db(tmp_path)
    result = ModeTransitionService(store).classify(
        current_message="Just give me the answer.", recent_turns=[], current_mode="learn",
        session_id=session.id, owner="local", concept_title="Attention Mechanism",
        concept_id="attention")
    assert result.decision == "request_transition"
    assert result.target_mode == "ask"
    assert result.suggestion is not None
    assert result.suggestion.target_mode == "ask"
    store.close()


def test_cooldown_and_dismissal_suppression(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)

    # First request triggers Learn suggestion
    result = service.evaluate_intent(
        current_message="Teach me this from the beginning.",
        recent_turns=[],
        current_mode="ask",
        session_id=session.id,
        concept_title="Attention Mechanism",
    )
    assert result.suggestion is not None

    # User dismisses suggestion
    service.record_interaction(
        owner="local",
        interaction=ModeTransitionInteraction(
            suggestion_id=result.suggestion.id,
            action="dismiss",
            target_mode="learn",
            session_id=session.id,
        ),
    )

    # Explicit requests always override recommendation dismissal.
    second_result = service.evaluate_intent(
        current_message="Teach me this from the beginning.",
        recent_turns=[],
        current_mode="ask",
        session_id=session.id,
        concept_title="Attention Mechanism",
    )
    assert second_result.suggestion is not None
    assert second_result.decision == "request_transition"

    store.close()


def test_quiz_to_learn_gap_evaluation(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)

    _add_quiz_attempts(store, session.id, [
        {"id": "attempt-a", "presentationId": "presentation-a", "score": 0.0},
    ])
    # One independent miss should NOT trigger a suggestion.
    sugg_1 = service.evaluate_quiz_gap(
        owner="local",
        session_id=session.id,
        concept_id="attention",
        concept_title="Backpropagation",
        consecutive_misses=1,
    )
    assert sugg_1 is None

    # A second missed, independent question should trigger review.
    _add_quiz_attempts(store, session.id, [
        {"id": "attempt-b", "presentationId": "presentation-b", "score": 0.0,
         "createdAt": utc_now().isoformat()},
    ])
    sugg_2 = service.evaluate_quiz_gap(
        owner="local",
        session_id=session.id,
        concept_id="attention",
        concept_title="Backpropagation",
        consecutive_misses=2,
    )
    assert sugg_2 is not None
    assert sugg_2.target_mode == "learn"
    assert "2 independent questions" in sugg_2.description
    assert sugg_2.action_label == "Review in Learn"

    store.close()


def test_transition_api_endpoints(tmp_path):
    store, session = _setup_test_db(tmp_path)
    _add_quiz_attempts(store, session.id, [
        {"id": "attempt-x", "presentationId": "presentation-x", "score": 0.0},
        {"id": "attempt-y", "presentationId": "presentation-y", "score": 0.0,
         "createdAt": utc_now().isoformat()},
    ])
    app = FastAPI()
    app.include_router(build_learning_router(lambda: store, lambda: None))
    app.dependency_overrides[material_owner] = lambda: "local"
    client = TestClient(app)

    classified = client.post(f"/v1/sessions/{session.id}/mode-classification", json={
        "message": "Quiz me on this.", "currentMode": "ask",
    })
    assert classified.status_code == 200
    assert classified.json()["decision"] == "request_transition"
    assert classified.json()["suggestion"]["targetMode"] == "quiz"

    # 1. Test transition-gap endpoint
    resp = client.get(f"/v1/sessions/{session.id}/transition-gap?concept_id=attention&concept_title=Attention&consecutive_misses=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggestion"] is not None
    assert data["suggestion"]["targetMode"] == "learn"

    # 2. Test transition-interaction endpoint (dismiss)
    sugg_id = data["suggestion"]["id"]
    dismiss_resp = client.post(
        f"/v1/sessions/{session.id}/transition-interaction",
        json={
            "suggestionId": sugg_id,
            "action": "dismiss",
            "targetMode": "learn",
        },
    )
    assert dismiss_resp.status_code == 200
    assert dismiss_resp.json()["status"] == "dismissed"

    # 3. Verify that further gap suggestions for learn are now suppressed
    suppressed_resp = client.get(f"/v1/sessions/{session.id}/transition-gap?concept_id=attention&concept_title=Attention&consecutive_misses=3")
    assert suppressed_resp.status_code == 200
    assert suppressed_resp.json()["suggestion"] is None

    store.close()


def test_accepted_transition_recovers_until_destination_is_applied(tmp_path):
    store, session = _setup_test_db(tmp_path)
    service = ModeTransitionService(store)
    result = service.classify(
        current_message="Quiz me on attention.",
        recent_turns=[],
        current_mode="ask",
        session_id=session.id,
        owner="local",
        concept_title="Attention Mechanism",
        concept_id="attention",
    )
    suggestion = result.suggestion
    assert suggestion is not None

    accepted = service.transition_interaction("local", session.id, ModeTransitionInteraction(
        suggestion_id=suggestion.id, action="accept", target_mode="quiz", session_id=session.id))
    assert accepted["status"] == "accepted"
    assert service.pending("local", session.id)["status"] == "accepted"

    service.transition_interaction("local", session.id, ModeTransitionInteraction(
        suggestion_id=suggestion.id, action="failed", target_mode="quiz", session_id=session.id))
    recovered = service.pending("local", session.id)
    assert recovered is not None
    assert recovered["suggestion"]["status"] == "accepted"
    assert recovered["startupStatus"] == "failed"

    service.transition_interaction("local", session.id, ModeTransitionInteraction(
        suggestion_id=suggestion.id, action="applied", target_mode="quiz", session_id=session.id))
    assert service.pending("local", session.id) is None
    store.close()


def test_ambiguous_classification_uses_configured_provider_with_short_timeout(tmp_path, monkeypatch):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "provider")

    class FakeProvider:
        def complete_json(self, prompt, max_tokens, *, request_timeout=None):
            assert request_timeout == 2.5
            assert "Help me prepare for my quiz." in prompt
            return {"decision": "request_transition", "targetMode": "quiz",
                    "requestType": "explicit", "confidence": 0.93,
                    "reasonCode": "quiz_prep", "rationale": "You asked to practice."}

    try:
        result = ModeTransitionService(store).classify(
            current_message="Help me prepare for my quiz.", recent_turns=[], current_mode="ask",
            session_id=session.id, owner="local", concept_title="Attention Mechanism",
            concept_id="attention", provider=FakeProvider())
        assert result.decision == "request_transition"
        assert result.target_mode == "quiz"
        assert result.classification_source == "model"
    finally:
        store.close()


def test_hybrid_classifier_handles_paraphrased_quiz_intent(tmp_path, monkeypatch):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "hybrid")

    class FakeProvider:
        def complete_json(self, prompt, max_tokens, *, request_timeout=None):
            assert "meaning and conversation context rather than matching a fixed vocabulary" in prompt
            assert "hello dude test my maths" in prompt
            return {"decision": "request_transition", "targetMode": "quiz",
                    "requestType": "explicit", "confidence": 0.91,
                    "reasonCode": "requested_practice", "rationale": "They asked to be tested on maths."}

    try:
        result = ModeTransitionService(store).classify(
            current_message="hello dude test my maths", recent_turns=[], current_mode="ask",
            session_id=session.id, owner="local", concept_title="Mathematics",
            concept_id="maths", provider=FakeProvider())
        assert result.decision == "request_transition"
        assert result.target_mode == "quiz"
        assert result.classification_source == "model"
        assert result.confidence == 0.91
    finally:
        store.close()


def test_hybrid_classifier_abstains_below_confidence_threshold(tmp_path, monkeypatch):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "hybrid")

    class FakeProvider:
        def complete_json(self, prompt, max_tokens, *, request_timeout=None):
            return {"decision": "suggest", "targetMode": "quiz", "requestType": "implicit",
                    "confidence": 0.7, "reasonCode": "maybe_practice", "rationale": "Possibly helpful."}

    try:
        result = ModeTransitionService(store).classify(
            current_message="Could use some help with maths.", recent_turns=[], current_mode="ask",
            session_id=session.id, owner="local", concept_title="Mathematics",
            concept_id="maths", provider=FakeProvider())
        assert result.decision == "stay"
        assert result.suggestion is None
        assert result.reason == "model_low_confidence"
    finally:
        store.close()


def test_hybrid_classification_api_uses_configured_provider(tmp_path, monkeypatch):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "hybrid")

    class FakeProvider:
        def complete_json(self, prompt, max_tokens, *, request_timeout=None):
            assert "Could we check how much attention I remember?" in prompt
            return {"decision": "request_transition", "targetMode": "quiz",
                    "requestType": "explicit", "confidence": 0.9,
                    "reasonCode": "requested_recall", "rationale": "The learner wants a recall check."}

    app = FastAPI()
    app.include_router(build_learning_router(lambda: store, lambda: FakeProvider()))
    app.dependency_overrides[material_owner] = lambda: "local"
    client = TestClient(app)
    try:
        response = client.post(f"/v1/sessions/{session.id}/mode-classification", json={
            "message": "Could we check how much attention I remember?", "currentMode": "ask",
        })
        assert response.status_code == 200
        assert response.json()["decision"] == "request_transition"
        assert response.json()["suggestion"]["targetMode"] == "quiz"
    finally:
        store.close()


def test_jev_ambiguous_classification_uses_openrouter_decisions(monkeypatch):
    store, session = _setup_test_db(None)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "active")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENLEARN_JEV_USD_PER_REQUEST", "0.001")
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id":"gen-dec-mode-test", "usage":{"cost":0.000014994}, "answers": {
            "quiz_now": {"type": "noul", "noul": 0.96},
            "quiz_discussed_or_deferred": {"type": "noul", "noul": 0.03},
            "workflow": {"type": "choice", "choice": "quiz", "confidence": 0.9,
                         "probabilities": {"ask": 0.02, "learn": 0.02, "quiz": 0.94, "none": 0.02}},
            "request_type": {"type": "choice", "choice": "implicit", "confidence": 0.9,
                             "probabilities": {"explicit": 0.05, "implicit": 0.9, "none": 0.05}},
        }})

    monkeypatch.setattr(httpx, "post", post)
    with usage_scope(store, "local", session.id):
        result = ModeTransitionService(store).classify(
            current_message="Help me prepare for my quiz.", recent_turns=[], current_mode="ask",
            session_id=session.id, owner="local", concept_title="Attention Mechanism", concept_id="attention")
    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert captured["json"]["model"] == "typesafe/jev-1.13"
    assert isinstance(captured["json"]["questions"], dict)
    assert result.decision == "suggest"  # Jev suggestions remain subject to learner confirmation.
    assert result.target_mode == "quiz"
    assert result.classification_source == "model"
    with store.engine.connect() as conn:
        event = conn.execute(text("SELECT component,cost_nano,source FROM usage_events WHERE owner_id='local'")).one()
    assert event.component == "tool"
    assert event.cost_nano == 14_994
    assert event.source == "exact"
    _close_test_db(store)


def test_jev_missing_usage_rate_falls_back_without_network(monkeypatch):
    store, session = _setup_test_db(None)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "active")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    monkeypatch.delenv("OPENLEARN_JEV_USD_PER_REQUEST", raising=False)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unmetered Jev request")))

    with usage_scope(store, "local", session.id):
        result = ModeTransitionService(store).classify(
            current_message="Help me prepare for my quiz.", recent_turns=[], current_mode="ask",
            session_id=session.id, owner="local", concept_title="Attention Mechanism", concept_id="attention")

    assert result.decision == "stay"
    assert result.target_mode is None
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM usage_events WHERE owner_id='local'")).scalar_one() == 0
    _close_test_db(store)


def test_jev_missing_key_and_uncertain_result_fall_back_safely(monkeypatch, tmp_path):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "active")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = ModeTransitionService(store)
    missing = service.classify("Help me prepare for my quiz.", [], "ask", session_id=session.id)
    assert missing.decision == "stay"
    assert missing.target_mode is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENLEARN_JEV_USD_PER_REQUEST", "0.001")
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request("POST", url), json={"answers": {
            "quiz_now": {"type":"noul", "noul": 0.51},
            "quiz_discussed_or_deferred": {"type":"noul", "noul": 0.3},
            "workflow": {"type":"choice", "choice":"quiz", "probabilities":{"ask":0.2,"learn":0.2,"quiz":0.55,"none":0.05}},
            "request_type": {"type":"choice", "choice":"implicit", "probabilities":{"explicit":0.1,"implicit":0.55,"none":0.35}},
        }}))
    with usage_scope(store, "local", session.id):
        uncertain = service.classify("Help me prepare for my quiz.", [], "ask", session_id=session.id)
    assert uncertain.decision == "stay"
    assert uncertain.target_mode is None
    store.close()


def test_jev_classifies_explicit_request_instead_of_bypassing(monkeypatch, tmp_path):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("OPENLEARN_CLASSIFICATION_MODE", "off")
    monkeypatch.setenv("OPENLEARN_CLASSIFIER_MODE_INTENT_MODE", "active")
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENLEARN_JEV_USD_PER_REQUEST", "0.001")
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-provider-rates-v1")
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"answers": {
            "workflow": {"choice": "quiz", "probabilities": {"ask": 0.01, "learn": 0.01, "quiz": 0.96, "none": 0.02}},
            "request_type": {"choice": "explicit", "probabilities": {"explicit": 0.96, "implicit": 0.02, "none": 0.02}},
            "quiz_now": {"noul": 0.97}, "quiz_discussed_or_deferred": {"noul": 0.01},
        }})

    monkeypatch.setattr(httpx, "post", post)
    with usage_scope(store, "local", session.id):
        result = ModeTransitionService(store).classify("Quiz me on this.", [], "ask", session_id=session.id)

    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert result.decision == "request_transition"
    assert result.target_mode == "quiz"
    store.close()
