"""Phase 6 closed-loop E2E: Teach → Check misses → Repair → assisted → fresh Check → Continue."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.models import Concept, Edge, GraphVersion, TopicScope, utc_now
from backend.app.recommendation_routes import build_recommendation_router
from backend.app.recommendation_service import RecommendationService
from backend.app.session_models import LearningSession
from backend.app.session_snapshot_routes import build_session_snapshot_router
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.state_models import EvidenceCreate
from backend.app.state_routes import build_state_router
from backend.app.state_service import LearnerStateService
from backend.app.storage import Store


def _seed(store: Store):
    from backend.app.identity import Principal, principal_context
    principal_token = principal_context.set(Principal("local", "local"))
    now = utc_now()
    scope = TopicScope(
        id="scope-loop", topic="Closed loop", resolved_meaning="Closed loop",
        objective="Learn", depth="introductory", created_at=now,
    )
    store.save_scope(scope)
    graph = GraphVersion(
        id="graph-loop", scope_id=scope.id, title="Closed loop", description="",
        publication_state="published", trust_summary="", generated_by="test", created_at=now,
        concepts=[
            Concept(id="intro", title="Introduction", label="", summary="", objective=""),
            Concept(id="next", title="Next idea", label="", summary="", objective=""),
        ],
        edges=[Edge(id="e1", source="intro", target="next", type="requires", justification="", support_status="supported")],
    )
    store.save_graph(graph)
    session = LearningSession(
        id="session-loop", learner_id="local", graph_id=graph.id,
        current_concept_id="intro", created_at=now, updated_at=now,
    )
    store.save_session(session)
    principal_context.reset(principal_token)
    return graph, session


def _admit(state: LearnerStateService, graph, *, key: str, outcome: str, condition: str, family: str, assisted=False, score=None):
    return state.admit_evidence("local", EvidenceCreate(
        evidence_key=key,
        concept_id="intro",
        graph_id=graph.id,
        graph_version=1,
        kind="assessment",
        outcome=outcome,
        condition=condition,
        score=1.0 if score is None and outcome == "correct" else (0.0 if score is None else score),
        evaluator="test",
        reliability=0.4,
        provenance={
            "itemId": f"item-{key}",
            "itemFamily": family,
            "sessionId": "session-loop",
            "presentationId": f"presentation-{key}",
            "attemptId": f"attempt-{key}",
            "hintIds": ["hint-1"] if assisted else [],
        },
    )).evidence


def test_closed_loop_teach_check_repair_assisted_fresh_continue(tmp_path):
    store = Store(tmp_path / "closed-loop.db")
    graph, session = _seed(store)
    recommendations = RecommendationService(store)
    state = LearnerStateService(store)

    teach = recommendations.get_or_create("local", session.id)
    assert teach.recommendations[0].pedagogical_action == "teach"

    # Lesson exposure is represented by first check after teach; simulate taught_without_check
    # via a lesson-completed signal isn't needed once evidence starts arriving.

    first_miss = _admit(state, graph, key="miss-1", outcome="incorrect", condition="independent", family="family-a")
    after_first = recommendations.get_or_create("local", session.id)
    assert after_first.recommendations[0].pedagogical_action == "check"
    assert after_first.recommendations[0].why_code == "first_independent_miss"

    second_miss = _admit(state, graph, key="miss-2", outcome="incorrect", condition="independent", family="family-b")
    repair = recommendations.get_or_create("local", session.id)
    assert repair.recommendations[0].pedagogical_action == "repair"
    assert repair.recommendations[0].why_code == "repeated_distinct_miss"

    assisted = _admit(
        state, graph, key="assisted-1", outcome="correct", condition="assisted",
        family="family-c", assisted=True,
    )
    after_assist = recommendations.get_or_create("local", session.id)
    assert after_assist.recommendations[0].pedagogical_action == "check"
    assert after_assist.recommendations[0].why_code == "assisted_success_needs_fresh_check"

    fresh = _admit(state, graph, key="fresh-1", outcome="correct", condition="independent", family="family-d")
    continue_set = recommendations.get_or_create("local", session.id)
    assert continue_set.recommendations[0].pedagogical_action == "teach"
    assert continue_set.recommendations[0].why_code == "fresh_independent_success"

    recommendations.record_interaction(
        "local", continue_set.recommendations[0].id, "completion", None, "complete-fresh", fresh.id,
    )

    app = FastAPI()
    app.include_router(build_state_router(lambda: store))
    app.include_router(build_recommendation_router(lambda: store))
    app.include_router(build_session_snapshot_router(lambda: store))
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    with TestClient(app, headers={"X-Dev-Learner-Id": "local"}) as client:
        chain = client.get(
            "/v1/learners/local/adaptive/closed-loop",
            params={"sessionId": session.id, "conceptId": "intro"},
        )
        assert chain.status_code == 200, chain.text
        body = chain.json()
        assert body["sessionId"] == session.id
        kinds = [link["kind"] for link in body["links"]]
        assert "recommendation_set" in kinds
        assert "evidence" in kinds
        assert body["complete"] is True

        # Snapshot survives without client state.
        snapshot = client.get(f"/v1/sessions/{session.id}/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["currentConceptId"] == "intro"

        # Challenge withdraws evidence and reopens adaptation.
        challenged = client.post(
            f"/v1/learners/local/evidence/{fresh.id}/challenge",
            json={"reason": "Learner contests this result."},
        )
        assert challenged.status_code == 201, challenged.text

    # Two-tab stale recommendation selection remains rejected.
    with TestClient(app, headers={"X-Dev-Learner-Id": "local"}) as client:
        current_response = client.get(f"/v1/sessions/{session.id}/recommendations")
        assert current_response.status_code == 200, current_response.text
        current = current_response.json()
        stale_id = teach.recommendations[0].id
        stale = client.post(f"/v1/recommendations/{stale_id}/interactions", json={"eventType": "selection"})
        assert stale.status_code == 409
        assert current["recommendations"][0]["id"] != stale_id

    assert first_miss.id and second_miss.id and assisted.id and fresh.id
    store.close()


def test_session_position_fault_injection_stale_revision_and_cross_owner(tmp_path):
    store = Store(tmp_path / "fault-session.db")
    graph, session = _seed(store)
    app = FastAPI()
    app.include_router(build_session_snapshot_router(lambda: store))
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    with TestClient(app, headers={"X-Dev-Learner-Id": "local"}) as client:
        snap = client.get(f"/v1/sessions/{session.id}/snapshot").json()
        revision = snap["revision"]
        ok = client.patch(
            f"/v1/sessions/{session.id}/position",
            json={"expectedRevision": revision, "activeQuizId": "quiz-1"},
        )
        assert ok.status_code == 200
        stale = client.patch(
            f"/v1/sessions/{session.id}/position",
            json={"expectedRevision": revision, "activeQuizId": "quiz-2"},
        )
        assert stale.status_code == 409
        foreign = client.get(
            f"/v1/sessions/{session.id}/snapshot",
            headers={"X-Dev-Learner-Id": "other"},
        )
        assert foreign.status_code == 404
    store.close()
