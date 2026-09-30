from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.storage import Store
from backend.app.models import Concept, Edge, GraphVersion, TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.mode_transition_service import ModeTransitionService
from backend.app.mode_transition_models import ModeTransitionInteraction
from backend.app.learning_routes import build_learning_router
import json
import os
import httpx


def _setup_test_db(tmp_path):
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


def _add_quiz_attempts(store, session_id, attempts):
    quiz_id = "quiz-transition-fixture"
    ids = [item["id"] for item in attempts]
    quiz = {"id": quiz_id, "sessionId": session_id, "attempts": ids}
    with store.transaction() as conn:
        from sqlalchemy import text
        existing = conn.execute(text("SELECT payload FROM practice_records WHERE id=:id AND owner_id='local'"), {"id": quiz_id}).first()
        if existing:
            quiz.update(json.loads(existing[0]))
            quiz["attempts"] = list(dict.fromkeys([*quiz.get("attempts", []), *ids]))
            conn.execute(text("UPDATE practice_records SET payload=:payload WHERE id=:id"), {"id": quiz_id, "payload": json.dumps(quiz)})
        else:
            conn.execute(text("INSERT INTO practice_records(id,owner_id,kind,parent_id,revision,payload) VALUES(:id,'local','quiz',:sid,1,:payload)"),
                {"id": quiz_id, "sid": session_id, "payload": json.dumps(quiz)})
        for item in attempts:
            item = {"quizId": quiz_id, "conceptId": "attention", "assisted": False, "status": "evaluated",
                    "outcome": "answer", "score": 0.0, "createdAt": f"2026-09-27T00:00:{len(item['id']):02d}+00:00", **item}
            conn.execute(text("INSERT INTO practice_records(id,owner_id,kind,parent_id,revision,payload) VALUES(:id,'local','attempt',:parent,1,:payload)"),
                {"id": item["id"], "parent": quiz_id, "payload": json.dumps(item)})


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
         "createdAt": "2026-09-27T00:01:00+00:00"},
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
         "createdAt": "2026-09-27T00:01:00+00:00"},
    ])
    app = FastAPI()
    app.include_router(build_learning_router(lambda: store, lambda: None))
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


def test_ambiguous_classification_uses_configured_provider_with_short_timeout(tmp_path):
    store, session = _setup_test_db(tmp_path)
    previous_mode = os.environ.get("AI_TUTOR_MODE_CLASSIFICATION")
    os.environ["AI_TUTOR_MODE_CLASSIFICATION"] = "provider"

    class FakeProvider:
        def complete_json(self, prompt, max_tokens, *, request_timeout=None):
            assert request_timeout == 2.5
            assert "Help me prepare for my quiz." in prompt
            return {"decision": "request_transition", "targetMode": "quiz",
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
        if previous_mode is None:
            os.environ.pop("AI_TUTOR_MODE_CLASSIFICATION", None)
        else:
            os.environ["AI_TUTOR_MODE_CLASSIFICATION"] = previous_mode


def test_jev_ambiguous_classification_uses_openrouter_decisions(monkeypatch, tmp_path):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"answers": {
            "quiz_now": {"type": "noul", "noul": 0.96},
            "quiz_discussed_or_deferred": {"type": "noul", "noul": 0.03},
            "workflow": {"type": "choice", "choice": "quiz", "confidence": 0.9,
                         "probabilities": {"ask": 0.02, "learn": 0.02, "quiz": 0.94, "none": 0.02}},
        }})

    monkeypatch.setattr(httpx, "post", post)
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
    store.close()


def test_jev_missing_key_and_uncertain_result_fall_back_safely(monkeypatch, tmp_path):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = ModeTransitionService(store)
    missing = service.classify("Help me prepare for my quiz.", [], "ask", session_id=session.id)
    assert missing.decision == "stay"
    assert missing.target_mode is None

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(200,
        request=httpx.Request("POST", url), json={"answers": {
            "quiz_now": {"noul": 0.51}, "quiz_discussed_or_deferred": {"noul": 0.3},
            "workflow": {"choice": "quiz", "confidence": 0.55},
        }}))
    uncertain = service.classify("Help me prepare for my quiz.", [], "ask", session_id=session.id)
    assert uncertain.decision == "stay"
    assert uncertain.target_mode is None
    store.close()


def test_jev_does_not_call_api_for_explicit_rules(monkeypatch, tmp_path):
    store, session = _setup_test_db(tmp_path)
    monkeypatch.setenv("AI_TUTOR_MODE_CLASSIFICATION", "jev")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected network")))
    result = ModeTransitionService(store).classify("Quiz me on this.", [], "ask", session_id=session.id)
    assert result.decision == "request_transition"
    assert result.target_mode == "quiz"
    store.close()
