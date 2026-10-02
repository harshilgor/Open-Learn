import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.decision_store import DecisionStore
from backend.app.shared_contracts import Assistance, Dependency, LearningDecision, RevisionSnapshot, SourceSpan


def decision(decision_id="decision1", revision="v1"):
    return LearningDecision(id=decision_id, workflow="quiz", action="independent_check", reason_codes=("assisted_success_needs_verification",),
        snapshot=RevisionSnapshot(learner_projection_revision=7, academic_snapshot_revision=2, concept_graph_revision="g1", policy_revision="p1", context_manifest_id="context1",
            dependencies=(Dependency(kind="source", entity_id="source1", revision=revision),)))


def test_contracts_reject_unrecorded_claims_and_contradictory_assistance():
    with pytest.raises(ValidationError):
        LearningDecision.model_validate({**decision().model_dump(), "mastery_probability": .9})
    with pytest.raises(ValidationError):
        RevisionSnapshot.model_validate({**decision().snapshot.model_dump(), "learner_projection_revision": "7"})
    with pytest.raises(ValidationError):
        Assistance(independence="observed_independent", exposure_lineage_id="lineage1", question_family_id="family1", answer_revealed=True)
    for kwargs in [{"text_start": 5, "text_end": 4}, {"text_start": 0, "text_end": 4, "audio_start_ms": 10}]:
        with pytest.raises(ValidationError):
            SourceSpan(revision_id="r1", origin_id="o1", extraction_method="text", **kwargs)


def test_owner_scoped_immutable_decision_and_corrections(tmp_path):
    store = Store(tmp_path / "decision.db")
    service = DecisionStore(store)
    original = decision()
    assert service.save("alice", "key1", original)["valid"]
    assert service.save("alice", "key1", original)["decision"] == original
    with pytest.raises(HTTPException):
        service.save("alice", "key1", decision(revision="v2"))
    with pytest.raises(HTTPException) as denied:
        service.get("bob", original.id)
    assert denied.value.status_code == 404
    with store.transaction() as conn:
        assert service.invalidate(conn, "bob", original.snapshot.dependencies[0], "correction1", "source_corrected") == []
        assert service.invalidate(conn, "alice", Dependency(kind="source", entity_id="source1", revision="v2"), "correction2", "source_corrected") == []
        assert service.invalidate(conn, "alice", original.snapshot.dependencies[0], "correction1", "source_corrected") == [original.id]
        service.invalidate(conn, "alice", original.snapshot.dependencies[0], "correction1", "source_corrected")
    corrected = service.get("alice", original.id)
    assert not corrected["valid"] and len(corrected["invalidations"]) == 1
    assert corrected["decision"] == original
    with pytest.raises(HTTPException):
        with store.transaction() as conn:
            service.invalidate(conn, "alice", original.snapshot.dependencies[0], "correction1", "source_removed")
    newer = decision("decision2", "v2")
    assert service.save("alice", "key2", newer)["valid"]
    store.close()


def test_decision_and_invalidation_participate_in_parent_transaction(tmp_path):
    store = Store(tmp_path / "decision.db")
    service = DecisionStore(store)
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            service.save("alice", "key1", decision(), conn)
            raise RuntimeError("simulated command failure")
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM learning_decisions")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM learning_decision_dependencies")).scalar_one() == 0
    store.close()
