from pathlib import Path
from uuid import uuid4

from backend.app.assessment_models import QuizCreate
from backend.app.graph_generator import GraphGenerator
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.stable_concept_models import ConceptCreate
from backend.app.stable_concept_service import StableConceptService
from backend.app.storage import Store
from backend.app.quiz_service import QuizService


def test_quiz_task_scope_maps_stable_ids_to_reviewed_current_graph_nodes():
    store = Store(Path.cwd() / "backend" / "data" / ("task-scope-" + uuid4().hex + ".db"))
    try:
        owner = "local"
        scope = TopicScope(id="scope-task", topic="probability", resolved_meaning="probability",
            objective="conditional probability", depth="introductory", created_at=utc_now())
        store.save_scope(scope)
        graph = GraphGenerator().generate(scope)
        store.save_graph(graph)
        session = LearningSession(id="session-task", learner_id=owner, graph_id=graph.id,
            goal="conditional probability", created_at=utc_now(), updated_at=utc_now())
        store.save_session(session)
        concepts = StableConceptService(store)
        stable = concepts.create(owner, ConceptCreate(title="Conditional probability",
            definition="Probability within the event on which we condition.", discipline="mathematics",
            expected_grain="One conditional probability idea."))["concept"]
        graph_node = graph.concepts[0]
        import json
        from sqlalchemy import text
        with store.transaction() as conn:
            conn.execute(text("""INSERT INTO legacy_concept_mappings(owner_id,id,revision,payload,graph_id,graph_revision,node_id,concept_id)
                VALUES(:owner,:id,1,:payload,:graph,:graph_revision,:node,:concept)"""), {
                "owner": owner, "id": "legacy-map-task", "payload": json.dumps({"review_state": "reviewed"}),
                "graph": graph.id, "graph_revision": graph.version, "node": graph_node.id, "concept": stable["id"]})
            quiz = QuizService(store, None).create(owner, QuizCreate(session_id=session.id, task_id="task-1",
                canonical_concept_ids=[stable["id"]], count=1), conn, "quiz-task-1")
        assert quiz["taskId"] == "task-1"
        assert quiz["conceptIds"] == [graph_node.id]
        assert quiz["canonicalConceptIds"] == [stable["id"]]
    finally:
        store.close()
