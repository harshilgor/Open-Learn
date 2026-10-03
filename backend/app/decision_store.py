"""Immutable, owner-scoped decision history and correction dependencies.

Write methods accept the caller's transaction so authoritative corrections and
invalidation records commit together. This store does not run a second reducer.
"""
from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import AwareDatetime, TypeAdapter, model_validator
from sqlalchemy import Connection, text

from .shared_contracts import Contract, DecisionSnapshot, Identifier, ReasonCode, RevisionRef


class Invalidation(Contract):
    owner_id: Identifier
    id: Identifier
    dependency: RevisionRef
    reason: ReasonCode
    created_at: AwareDatetime
    replacement: RevisionRef | None = None

    @model_validator(mode="after")
    def replacement_differs(self):
        if self.replacement == self.dependency:
            raise ValueError("A correction cannot replace a revision with itself")
        return self


class DecisionRead(Contract):
    snapshot: DecisionSnapshot
    status: Literal["valid", "invalidated", "pending_analysis"]
    invalidations: tuple[Invalidation, ...]


class DecisionRepository(Protocol):
    """Internal service boundary; owner_id comes from trusted caller context."""

    def save(self, conn: Connection, owner_id: str, snapshot: DecisionSnapshot) -> None: ...
    def read(self, conn: Connection, owner_id: str, snapshot_id: str) -> DecisionRead | None: ...
    def invalidate(self, conn: Connection, owner_id: str, invalidation: Invalidation) -> None: ...


def _owner(owner_id: str, record_owner: str | None = None) -> str:
    validated = TypeAdapter(Identifier).validate_python(owner_id)
    if record_owner is not None and validated != record_owner:
        raise ValueError("Contract owner does not match service context")
    return validated


def _canonical(model: Contract) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class DecisionStore:
    @staticmethod
    def affected_snapshot_ids(conn: Connection, owner_id: str, dependency: RevisionRef) -> tuple[str, ...]:
        """Find direct dependents for the owning service's rebuild/outbox command."""
        return tuple(conn.execute(text("""SELECT snapshot_id FROM decision_dependencies
            WHERE owner_id=:owner AND kind=:kind AND record_id=:id AND revision=:revision
            ORDER BY snapshot_id"""), {
                "owner": _owner(owner_id), "kind": dependency.kind,
                "id": dependency.id, "revision": dependency.revision,
            }).scalars())

    @staticmethod
    def save(conn: Connection, owner_id: str, snapshot: DecisionSnapshot) -> None:
        owner = _owner(owner_id, snapshot.owner_id)
        # Revalidate at the persistence boundary (even model_construct callers).
        snapshot = DecisionSnapshot.model_validate(snapshot.model_dump())
        payload = _canonical(snapshot)
        conn.execute(text("""INSERT INTO decision_snapshots
            (owner_id,id,revision,schema_revision,purpose,created_at,payload)
            VALUES (:owner,:id,:revision,:schema,:purpose,:created,:payload)
            ON CONFLICT(owner_id,id) DO NOTHING"""), {
            "owner": owner, "id": snapshot.id, "revision": snapshot.revision,
            "schema": snapshot.schema_revision, "purpose": snapshot.purpose,
            "created": snapshot.created_at.timestamp(), "payload": payload,
        })
        existing = conn.execute(text("SELECT payload FROM decision_snapshots WHERE owner_id=:owner AND id=:id"),
                                {"owner": owner, "id": snapshot.id}).scalar_one()
        if existing != payload:
            raise ValueError("Decision IDs are immutable; use a new ID for a new decision")
        for ref in snapshot.dependencies():
            conn.execute(text("""INSERT INTO decision_dependencies
                (owner_id,snapshot_id,kind,record_id,revision)
                VALUES (:owner,:snapshot,:kind,:id,:revision)
                ON CONFLICT(owner_id,snapshot_id,kind,record_id) DO NOTHING"""), {
                "owner": owner, "snapshot": snapshot.id, "kind": ref.kind,
                "id": ref.id, "revision": ref.revision,
            })

    @staticmethod
    def read(conn: Connection, owner_id: str, snapshot_id: str) -> DecisionRead | None:
        params = {"owner": _owner(owner_id), "id": TypeAdapter(Identifier).validate_python(snapshot_id)}
        row = conn.execute(text("SELECT payload FROM decision_snapshots WHERE owner_id=:owner AND id=:id"), params).scalar_one_or_none()
        if row is None:
            return None
        snapshot = DecisionSnapshot.model_validate_json(row)
        rows = conn.execute(text("""SELECT i.payload FROM contract_invalidations i
            JOIN decision_dependencies d ON d.owner_id=i.owner_id AND d.kind=i.kind
              AND d.record_id=i.record_id AND d.revision=i.revision
            WHERE d.owner_id=:owner AND d.snapshot_id=:id
            ORDER BY i.created_at,i.id"""), params).scalars()
        invalidations = tuple(Invalidation.model_validate_json(payload) for payload in rows)
        missing = any(slot.state == "unavailable" for slot in (
            snapshot.learner_projection, snapshot.academic_snapshot,
            snapshot.concept_graph, snapshot.context_manifest,
        ))
        status = "invalidated" if invalidations else "pending_analysis" if missing else "valid"
        return DecisionRead(snapshot=snapshot, status=status, invalidations=invalidations)

    @staticmethod
    def invalidate(conn: Connection, owner_id: str, invalidation: Invalidation) -> None:
        owner = _owner(owner_id, invalidation.owner_id)
        invalidation = Invalidation.model_validate(invalidation.model_dump())
        ref = invalidation.dependency
        payload = _canonical(invalidation)
        conn.execute(text("""INSERT INTO contract_invalidations
            (owner_id,id,kind,record_id,revision,reason,created_at,schema_revision,payload)
            VALUES (:owner,:id,:kind,:record,:revision,:reason,:created,:schema,:payload)
            ON CONFLICT(owner_id,id) DO NOTHING"""), {
            "owner": owner, "id": invalidation.id, "kind": ref.kind, "record": ref.id,
            "revision": ref.revision, "reason": invalidation.reason,
            "created": invalidation.created_at.timestamp(), "schema": invalidation.schema_revision,
            "payload": payload,
        })
        existing = conn.execute(text("SELECT payload FROM contract_invalidations WHERE owner_id=:owner AND id=:id"),
                                {"owner": owner, "id": invalidation.id}).scalar_one()
        if existing != payload:
            raise ValueError("Invalidation ID reused with different content")

    @staticmethod
    def delete_owner(conn: Connection, owner_id: str) -> None:
        """Only call within the authorized account deletion workflow.

        The identity service must fence outstanding jobs before this operation.
        Normal source corrections must call invalidate, not delete history.
        """
        params = {"owner": _owner(owner_id)}
        conn.execute(text("DELETE FROM decision_dependencies WHERE owner_id=:owner"), params)
        conn.execute(text("DELETE FROM decision_snapshots WHERE owner_id=:owner"), params)
        conn.execute(text("DELETE FROM contract_invalidations WHERE owner_id=:owner"), params)


class LearningDecisionStore:
    """Compatibility adapter for the original cloud decision contract.

    New workflow integrations should use the revision-addressed DecisionStore
    above. This adapter keeps old immutable decision records readable while
    both migrations coexist.
    """

    def __init__(self, store):
        self.store = store

    def save(self, owner, command_key, decision, connection=None):
        import hashlib
        from .shared_contracts import LearningDecision
        from .material_service import problem
        if connection is None:
            with self.store.transaction() as conn:
                return self.save(owner, command_key, decision, conn)
        decision = LearningDecision.model_validate(decision.model_dump())
        payload = json.dumps(decision.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        connection.execute(text("""INSERT INTO learning_decisions(id,owner_id,command_key,request_hash,workflow,schema_revision,payload,created_at)
            VALUES(:id,:owner,:key,:hash,:workflow,:schema,:payload,:created) ON CONFLICT DO NOTHING"""), {
            "id": decision.id, "owner": owner, "key": command_key, "hash": digest,
            "workflow": decision.workflow, "schema": decision.schema_revision,
            "payload": payload, "created": __import__("time").time(),
        })
        row = connection.execute(text("SELECT id,request_hash FROM learning_decisions WHERE owner_id=:owner AND command_key=:key"),
                                 {"owner": owner, "key": command_key}).first()
        if row is None or row[0] != decision.id or row[1] != digest:
            problem("idempotency_conflict", "The decision key already has different input.", 409)
        for dependency in decision.snapshot.dependencies:
            connection.execute(text("""INSERT INTO learning_decision_dependencies(decision_id,owner_id,kind,entity_id,revision)
                VALUES(:id,:owner,:kind,:entity,:revision) ON CONFLICT DO NOTHING"""), {
                "id": decision.id, "owner": owner, "kind": dependency.kind,
                "entity": dependency.entity_id, "revision": dependency.revision,
            })
        return self.get(owner, decision.id, connection)

    def get(self, owner, decision_id, connection=None):
        if connection is None:
            with self.store.engine.connect() as conn:
                return self.get(owner, decision_id, conn)
        row = connection.execute(text("SELECT payload FROM learning_decisions WHERE id=:id AND owner_id=:owner"),
                                 {"id": decision_id, "owner": owner}).scalar_one_or_none()
        if row is None:
            from .material_service import problem
            problem("not_found", "This decision is not available.", 404)
        from .shared_contracts import LearningDecision
        decision = LearningDecision.model_validate_json(row)
        invalidations = connection.execute(text("""SELECT correction_id,reason,created_at FROM learning_decision_invalidations
            WHERE owner_id=:owner AND decision_id=:id ORDER BY created_at,correction_id"""),
            {"owner": owner, "id": decision_id}).mappings().all()
        return {"decision": decision, "valid": not invalidations, "invalidations": [dict(item) for item in invalidations]}

    def invalidate(self, conn, owner, dependency, correction_id, reason):
        rows = conn.execute(text("""SELECT d.id FROM learning_decisions d JOIN learning_decision_dependencies x
            ON x.decision_id=d.id AND x.owner_id=d.owner_id
            WHERE d.owner_id=:owner AND x.kind=:kind AND x.entity_id=:entity AND x.revision=:revision ORDER BY d.id"""), {
            "owner": owner, "kind": dependency.kind, "entity": dependency.entity_id, "revision": dependency.revision,
        }).scalars().all()
        now = __import__("time").time()
        for decision_id in rows:
            result = conn.execute(text("""INSERT INTO learning_decision_invalidations(decision_id,owner_id,correction_id,reason,created_at)
                VALUES(:id,:owner,:correction,:reason,:now) ON CONFLICT DO NOTHING"""), {
                "id": decision_id, "owner": owner, "correction": correction_id, "reason": reason, "now": now,
            })
            existing = conn.execute(text("SELECT reason FROM learning_decision_invalidations WHERE decision_id=:id AND owner_id=:owner AND correction_id=:correction"), {
                "id": decision_id, "owner": owner, "correction": correction_id,
            }).scalar_one()
            if existing != reason:
                from .material_service import problem
                problem("idempotency_conflict", "The correction key was already used for another invalidation.", 409)
            if result.rowcount == 0:
                continue
        return list(rows)
