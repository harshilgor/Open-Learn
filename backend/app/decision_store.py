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
