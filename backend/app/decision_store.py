"""Immutable decision records and append-only dependency invalidations.

The calling service owns authorization of each dependency before creating a
decision. Retrieval here is always owner-scoped, including correction lookup.
"""
import hashlib
import time
from sqlalchemy import text
from .shared_contracts import LearningDecision, Dependency
from .workflow_store import encoded
from .material_service import problem


class DecisionStore:
    def __init__(self, store):
        self.store = store

    def save(self, owner, command_key, decision: LearningDecision, connection=None):
        if connection is None:
            with self.store.transaction() as conn:
                return self.save(owner, command_key, decision, conn)
        payload = encoded(decision.model_dump(mode="json"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        args = {"id": decision.id, "owner": owner, "key": command_key, "hash": digest,
                "workflow": decision.workflow, "schema": decision.schema_revision, "payload": payload, "now": time.time()}
        connection.execute(text("""INSERT INTO learning_decisions(id,owner_id,command_key,request_hash,workflow,schema_revision,payload,created_at)
            VALUES(:id,:owner,:key,:hash,:workflow,:schema,:payload,:now) ON CONFLICT DO NOTHING"""), args)
        row = connection.execute(text("SELECT id,request_hash FROM learning_decisions WHERE owner_id=:owner AND command_key=:key"), args).first()
        if row is None or row[0] != decision.id or row[1] != digest:
            problem("idempotency_conflict", "The decision key already has different input.", 409)
        for dependency in decision.snapshot.dependencies:
            connection.execute(text("""INSERT INTO learning_decision_dependencies(decision_id,owner_id,kind,entity_id,revision)
                VALUES(:id,:owner,:kind,:entity,:revision) ON CONFLICT DO NOTHING"""),
                {"id": decision.id, "owner": owner, "kind": dependency.kind, "entity": dependency.entity_id, "revision": dependency.revision})
        return self.get(owner, decision.id, connection)

    def get(self, owner, decision_id, connection=None):
        if connection is None:
            with self.store.engine.connect() as conn:
                return self.get(owner, decision_id, conn)
        row = connection.execute(text("SELECT payload FROM learning_decisions WHERE id=:id AND owner_id=:owner"), {"id": decision_id, "owner": owner}).first()
        if row is None:
            problem("not_found", "This decision is not available.", 404)
        invalidations = connection.execute(text("SELECT correction_id,reason FROM learning_decision_invalidations WHERE decision_id=:id AND owner_id=:owner ORDER BY created_at,correction_id"), {"id": decision_id, "owner": owner}).mappings().all()
        return {"decision": LearningDecision.model_validate_json(row[0]), "valid": not invalidations, "invalidations": [dict(r) for r in invalidations]}

    def invalidate(self, connection, owner, dependency: Dependency, correction_id, reason):
        if reason not in {"source_corrected", "source_removed", "evaluation_corrected", "evidence_retracted", "scope_changed", "policy_changed", "graph_changed"}:
            raise ValueError("Invalid correction reason")
        args = {"owner": owner, "kind": dependency.kind, "entity": dependency.entity_id, "revision": dependency.revision,
                "correction": correction_id, "reason": reason, "now": time.time()}
        incompatible = connection.execute(text("SELECT 1 FROM learning_decision_invalidations WHERE owner_id=:owner AND correction_id=:correction AND reason<>:reason LIMIT 1"), args).first()
        if incompatible:
            problem("idempotency_conflict", "The correction key already has a different reason.", 409)
        connection.execute(text("""INSERT INTO learning_decision_invalidations(decision_id,owner_id,correction_id,reason,created_at)
            SELECT decision_id,owner_id,:correction,:reason,:now FROM learning_decision_dependencies
            WHERE owner_id=:owner AND kind=:kind AND entity_id=:entity AND revision=:revision ON CONFLICT DO NOTHING"""), args)
        return list(connection.execute(text("SELECT decision_id FROM learning_decision_invalidations WHERE owner_id=:owner AND correction_id=:correction"), args).scalars())
