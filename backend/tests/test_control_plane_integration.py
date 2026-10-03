from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.graph_generator import GraphGenerator
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.learning_control_plane import LearningControlPlane
from backend.app.evidence_ledger import EvidenceLedger


def test_cold_start_context_decision_and_later_evidence_commit_fence():
    store = Store(Path.cwd() / "backend" / "data" / ("control-" + uuid4().hex + ".db"))
    try:
        scope = TopicScope(id="scope-control", topic="probability", resolved_meaning="probability", objective="conditional probability", depth="introductory", created_at=utc_now())
        store.save_scope(scope)
        graph = GraphGenerator().generate(scope)
        store.save_graph(graph)
        session = LearningSession(id="session-control", learner_id="local", graph_id=graph.id, goal="probability", created_at=utc_now(), updated_at=utc_now())
        store.save_session(session)
        control = LearningControlPlane(store)
        prepared = control.prepare("local", session.id, "ask", "quick", "Explain probability")
        assert prepared["decision"]["selected_action"] == "direct_explanation"
        with store.transaction() as conn:
            control.validate_commit(conn, "local", prepared)
        with store.transaction() as conn:
            EvidenceLedger(store).emit(conn, "local", "new-exposure", "LESSON_VIEWED")
        with store.transaction() as conn, pytest.raises(HTTPException) as failure:
            control.validate_commit(conn, "local", prepared)
        assert failure.value.detail["code"] == "learning_context_changed"
    finally:
        store.close()
