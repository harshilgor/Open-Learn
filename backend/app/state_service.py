"""Canonical learner-state reducer and learner-owned persistence services."""

from __future__ import annotations

import json
import base64
import binascii
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, text

from .models import GraphVersion, utc_now
from .state_models import (
    BranchCreate,
    BranchContextResponse,
    BranchRecord,
    BranchUpdate,
    DurableBranchAnchor,
    EvidenceAdmissionResponse,
    EvidenceCreate,
    EvidenceRecord,
    LearnerConceptState,
    LearnerStateResponse,
    NoteCreate,
    NoteRecord,
    NoteRevision,
    NoteUpdate,
    Position,
    ReviewSchedule,
    StateEvent,
    StateEventCreate,
    ConceptStateExplanation,
    TimelineEntry,
    TimelinePage,
    EvidenceChallenge,
)
from .storage import Store


class StateServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _object(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return json.loads(value) if isinstance(value, str) else value


def _utc(value: datetime | None = None) -> datetime:
    current = value or utc_now()
    return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


class LearnerStateService:
    """The only writer of ``learner_concept_states``.

    The deterministic reducer is deliberately conservative and uncalibrated.
    Its policy is versioned, and every state mutation points to accepted
    evidence. Other modules may only append activity events or request evidence
    admission through this service.
    """

    def __init__(self, store: Store):
        self.store = store

    def _ensure_learner(self, connection: Connection, learner_id: str) -> None:
        now = utc_now()
        exists = connection.execute(text("SELECT 1 FROM learners WHERE id=:id"), {"id": learner_id}).first()
        if exists:
            connection.execute(text("UPDATE learners SET updated_at=:now WHERE id=:id"), {"now": now, "id": learner_id})
        else:
            connection.execute(text("""
                INSERT INTO learners(id, identity_kind, display_name, created_at, updated_at)
                VALUES (:id, 'development_local', NULL, :now, :now)
            """), {"id": learner_id, "now": now})

    def _register_curriculum(self, connection: Connection, graph: GraphVersion) -> None:
        self.store._put(connection, "curriculum_scopes", "id", f"curriculum_{graph.id}", {
            "owner_learner_id": None,
            "graph_id": graph.id,
            "graph_version": graph.version,
            "compatibility_key": f"{graph.scope_id}:v{graph.version}",
            "schema_version": 1,
            "metadata_json": _json({
                "scopeId": graph.scope_id,
                "publicationState": graph.publication_state,
                "conceptIds": [concept.id for concept in graph.concepts],
                "generatedBy": graph.generated_by,
            }),
            "created_at": graph.created_at,
        })

    @staticmethod
    def _state_from_row(row: Any) -> LearnerConceptState:
        return LearnerConceptState(
            learner_id=row["learner_id"], concept_id=row["concept_id"], graph_id=row["graph_id"],
            graph_version=row["graph_version"], status=row["status"], confidence=row["confidence"],
            uncertainty=row["uncertainty"], version=row["version"], last_evidence_id=row["last_evidence_id"],
            policy_version=row["policy_version"], provenance=_object(row["provenance_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_from_row(row: Any) -> StateEvent:
        return StateEvent(
            id=row["id"], learner_id=row["learner_id"], kind=row["kind"], concept_id=row["concept_id"],
            session_id=row["session_id"], action_id=row["action_id"], correlation_id=row["correlation_id"],
            causation_id=row["causation_id"], idempotency_key=row["idempotency_key"],
            schema_version=row["schema_version"], payload=_object(row["payload_json"]),
            provenance=_object(row["provenance_json"]), occurred_at=row["occurred_at"], recorded_at=row["recorded_at"],
        )

    @staticmethod
    def _evidence_from_row(row: Any) -> EvidenceRecord:
        return EvidenceRecord(
            id=row["id"], learner_id=row["learner_id"], evidence_key=row["evidence_key"],
            concept_id=row["concept_id"], graph_id=row["graph_id"], graph_version=row["graph_version"],
            kind=row["kind"], outcome=row["outcome"], condition=row["condition"], score=row["score"],
            evaluator=row["evaluator"], reliability=row["reliability"], admission_status=row["admission_status"],
            admission_reason=row["admission_reason"], source_event_id=row["source_event_id"],
            supersedes_evidence_id=row["supersedes_evidence_id"], superseded_by_evidence_id=row["superseded_by_evidence_id"],
            policy_version=row["policy_version"], provenance=_object(row["provenance_json"]),
            occurred_at=row["occurred_at"], created_at=row["created_at"],
        )

    def mirror_capability_projections(self, connection, learner_id):
        """Compatibility labels/schedules are views of the capability authority."""
        from .unified_learner_state import UnifiedLearnerState
        from hashlib import sha256
        result = UnifiedLearnerState(self.store).read(connection, learner_id)
        grouped = {}
        for row in result["states"]:
            grouped.setdefault(row["conceptId"], []).append(row)
        now = utc_now()
        for concept, rows in grouped.items():
            statuses = {row["state"] for row in rows}
            status = "demonstrated" if len(rows) == 4 and statuses == {"demonstrated"} else "developing" if statuses & {"developing", "demonstrated"} else "exposed" if "exposed" in statuses else "unexplored"
            connection.execute(text("UPDATE learner_concept_states SET status=:status,policy_version=:policy,version=:revision,updated_at=:now WHERE learner_id=:owner AND concept_id=:concept"), {
                "status": status, "policy": result["policyRevision"], "revision": max(1, result["eventWatermark"]), "now": now, "owner": learner_id, "concept": concept})
            connection.execute(text("UPDATE review_schedules SET status='superseded',updated_at=:now WHERE learner_id=:owner AND concept_id=:concept AND status IN ('scheduled','due')"), {"now": now, "owner": learner_id, "concept": concept})
            due_rows = [row for row in rows if row["dueAt"]]
            for row in due_rows:
                identifier = "capability_review_" + sha256((learner_id + ":" + concept + ":" + row["capability"]).encode()).hexdigest()[:32]
                connection.execute(text("""INSERT INTO review_schedules(id,learner_id,concept_id,originating_evidence_id,due_at,status,interval_days,created_at,updated_at,due_reason,activity_type,scheduler_version)
                    VALUES(:id,:owner,:concept,NULL,:due,'scheduled',:interval,:now,:now,:reason,:activity,:policy)
                    ON CONFLICT(id) DO UPDATE SET due_at=excluded.due_at,status='scheduled',interval_days=excluded.interval_days,updated_at=excluded.updated_at,due_reason=excluded.due_reason,scheduler_version=excluded.scheduler_version"""), {
                        "id": identifier, "owner": learner_id, "concept": concept, "due": datetime.fromisoformat(row["dueAt"]),
                        "interval": row["intervalDays"], "now": now, "reason": "Independent " + row["capability"] + " check",
                        "activity": row["capability"], "policy": result["policyRevision"]})
            if due_rows:
                earliest = min(due_rows, key=lambda row: row["dueAt"])
                connection.execute(text("UPDATE concept_memory_states SET next_review_at=:due,mastery_estimate=:state,updated_at=:now WHERE learner_id=:owner AND concept_id=:concept"), {
                    "due": datetime.fromisoformat(earliest["dueAt"]), "state": "strong" if status == "demonstrated" else "developing", "now": now, "owner": learner_id, "concept": concept})

    def get_state(self, learner_id: str) -> LearnerStateResponse:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT * FROM learner_concept_states WHERE learner_id = :learner_id ORDER BY concept_id"
            ), {"learner_id": learner_id}).mappings().all()
        return LearnerStateResponse(learner_id=learner_id, states=[self._state_from_row(row) for row in rows])

    def explain_state(self, learner_id: str, concept_id: str) -> ConceptStateExplanation:
        """Projection only: evidence remains canonical and is never changed here."""
        with self.store.engine.connect() as connection:
            state_row = connection.execute(text("SELECT * FROM learner_concept_states WHERE learner_id=:owner AND concept_id=:concept"), {"owner": learner_id, "concept": concept_id}).mappings().first()
            if state_row is None:
                raise StateServiceError("concept_state_not_found", "There is no recorded learning state for this concept.", 404)
            evidence_rows = connection.execute(text("""SELECT * FROM evidence WHERE learner_id=:owner AND concept_id=:concept
                AND admission_status='accepted' ORDER BY occurred_at DESC, created_at DESC LIMIT 20"""), {"owner": learner_id, "concept": concept_id}).mappings().all()
            review_row = connection.execute(text("""SELECT * FROM review_schedules WHERE learner_id=:owner AND concept_id=:concept
                AND status IN ('scheduled','due') ORDER BY due_at ASC LIMIT 1"""), {"owner": learner_id, "concept": concept_id}).mappings().first()
        state = self._state_from_row(state_row)
        evidence = [self._evidence_from_row(row) for row in evidence_rows]
        latest = evidence[0] if evidence else None
        rationale = f"{state.status.value.replace('_', ' ')} from {len(evidence)} admitted evidence record{'s' if len(evidence) != 1 else ''}."
        if latest:
            rationale += f" Latest result was {latest.outcome} under {latest.condition.value} conditions."
        return ConceptStateExplanation(state=state, admitted_evidence=evidence, rationale=rationale, review=ReviewSchedule(**dict(review_row)) if review_row else None)

    def timeline(self, learner_id: str, cursor: str | None = None, limit: int = 30) -> TimelinePage:
        """A display-safe, cursor-paginated projection of durable activity events."""
        marker_time: datetime | None = None
        marker_id: str | None = None
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
                value = json.loads(decoded)
                marker_time = datetime.fromisoformat(value["recordedAt"])
                marker_id = value["id"]
                if not isinstance(marker_id, str) or not marker_id:
                    raise ValueError("missing event id")
            except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
                raise StateServiceError("invalid_timeline_cursor", "The timeline cursor is invalid. Reload the timeline.", 422) from exc
        with self.store.engine.connect() as connection:
            if marker_time is None:
                query = text("""SELECT id, kind, concept_id, payload_json, recorded_at FROM state_events
                    WHERE learner_id=:owner ORDER BY recorded_at DESC, id DESC LIMIT :limit""")
                params = {"owner": learner_id, "limit": limit + 1}
            else:
                query = text("""SELECT id, kind, concept_id, payload_json, recorded_at FROM state_events
                    WHERE learner_id=:owner AND (recorded_at < :marker_time OR (recorded_at = :marker_time AND id < :marker_id))
                    ORDER BY recorded_at DESC, id DESC LIMIT :limit""")
                params = {"owner": learner_id, "marker_time": marker_time, "marker_id": marker_id, "limit": limit + 1}
            rows = connection.execute(query, params).mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        entries: list[TimelineEntry] = []
        for row in rows:
            payload = _object(row["payload_json"])
            link: dict[str, str] = {}
            if payload.get("lessonId"): link = {"kind": "lesson", "id": str(payload["lessonId"])}
            elif payload.get("evidenceId"): link = {"kind": "evidence", "id": str(payload["evidenceId"])}
            entries.append(TimelineEntry(id=row["id"], kind=row["kind"], occurred_at=row["recorded_at"], concept_id=row["concept_id"], summary=row["kind"].replace(".", " ").replace("_", " "), deep_link=link))
        next_cursor = None
        if has_more and entries:
            payload = json.dumps({"recordedAt": entries[-1].occurred_at.isoformat(), "id": entries[-1].id}, separators=(",", ":"))
            next_cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        return TimelinePage(entries=entries, next_cursor=next_cursor)

    def challenge_evidence(self, learner_id: str, evidence_id: str, reason: str) -> EvidenceChallenge:
        """Audit the learner challenge then delegate invalidation and reduction to the sole state writer."""
        now = utc_now()
        challenge_id = f"evidence_challenge_{uuid4().hex}"
        with self.store.transaction() as connection:
            evidence = connection.execute(text("SELECT 1 FROM evidence WHERE id=:id AND learner_id=:owner"), {"id": evidence_id, "owner": learner_id}).first()
            if evidence is None:
                raise StateServiceError("evidence_not_found", "This evidence is not available.", 404)
            connection.execute(text("""INSERT INTO evidence_challenges(id, learner_id, evidence_id, reason, status, created_at)
                VALUES (:id,:owner,:evidence,:reason,'accepted',:now)"""), {"id": challenge_id, "owner": learner_id, "evidence": evidence_id, "reason": reason, "now": now})
            self.withdraw_evidence(learner_id, evidence_id, "learner_challenged", connection=connection)
        return EvidenceChallenge(id=challenge_id, evidence_id=evidence_id, learner_id=learner_id, reason=reason, created_at=now)

    def append_event(
        self,
        learner_id: str,
        request: StateEventCreate,
        *,
        connection: Connection | None = None,
    ) -> tuple[StateEvent, bool]:
        now = utc_now()
        occurred_at = _utc(request.occurred_at)
        with (nullcontext(connection) if connection is not None else self.store.transaction()) as connection:
            self._ensure_learner(connection, learner_id)
            if request.idempotency_key:
                existing = connection.execute(text(
                    "SELECT * FROM state_events WHERE learner_id = :learner_id AND idempotency_key = :key"
                ), {"learner_id": learner_id, "key": request.idempotency_key}).mappings().first()
                if existing:
                    return self._event_from_row(existing), True
            event_id = f"state_event_{uuid4().hex}"
            values = {
                "id": event_id, "learner_id": learner_id, "kind": request.kind,
                "concept_id": request.concept_id, "session_id": request.session_id, "action_id": request.action_id,
                "correlation_id": request.correlation_id, "causation_id": request.causation_id,
                "idempotency_key": request.idempotency_key, "schema_version": request.schema_version,
                "payload_json": _json(request.payload), "provenance_json": _json(request.provenance),
                "occurred_at": occurred_at, "recorded_at": now,
            }
            connection.execute(text("""
                INSERT INTO state_events
                (id, learner_id, kind, concept_id, session_id, action_id, correlation_id, causation_id,
                 idempotency_key, schema_version, payload_json, provenance_json, occurred_at, recorded_at)
                VALUES (:id, :learner_id, :kind, :concept_id, :session_id, :action_id, :correlation_id, :causation_id,
                        :idempotency_key, :schema_version, :payload_json, :provenance_json, :occurred_at, :recorded_at)
            """), values)
            from .evidence_ledger import EvidenceLedger
            category = {"concept.taught": "CONCEPT_TAUGHT", "lesson.completed": "CONCEPT_TAUGHT",
                "lesson.viewed": "LESSON_VIEWED", "confidence.reported": "SELF_REPORT",
                "hint.requested": "HINT_REQUESTED", "answer.exposed": "ANSWER_EXPOSED"}.get(request.kind)
            if category:
                EvidenceLedger(self.store).emit(connection, learner_id, "state:" + event_id, category,
                    concept_id=request.concept_id, activity_id=request.session_id, occurred_at=occurred_at,
                    detail=str(request.payload)[:2000] if category == "SELF_REPORT" else None)
            row = connection.execute(text("SELECT * FROM state_events WHERE id = :id"), {"id": event_id}).mappings().one()
            return self._event_from_row(row), False

    def list_events(self, learner_id: str, limit: int = 100) -> list[StateEvent]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT * FROM state_events WHERE learner_id = :learner_id ORDER BY recorded_at DESC LIMIT :limit"
            ), {"learner_id": learner_id, "limit": limit}).mappings().all()
        return [self._event_from_row(row) for row in rows]

    def list_evidence(self, learner_id: str, limit: int = 100) -> list[EvidenceRecord]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT * FROM evidence WHERE learner_id = :learner_id ORDER BY created_at DESC LIMIT :limit"
            ), {"learner_id": learner_id, "limit": limit}).mappings().all()
        return [self._evidence_from_row(row) for row in rows]

    def admit_evidence(self, learner_id: str, request: EvidenceCreate, *, connection: Connection | None = None) -> EvidenceAdmissionResponse:
        graph = self.store.get_graph(request.graph_id)
        now = utc_now()
        with (nullcontext(connection) if connection is not None else self.store.transaction()) as connection:
            self._ensure_learner(connection, learner_id)
            duplicate = connection.execute(text(
                "SELECT * FROM evidence WHERE learner_id = :learner_id AND evidence_key = :key"
            ), {"learner_id": learner_id, "key": request.evidence_key}).mappings().first()
            if duplicate:
                evidence = self._evidence_from_row(duplicate)
                state = self._get_state_in_transaction(connection, learner_id, evidence.concept_id)
                return EvidenceAdmissionResponse(evidence=evidence, learner_state=state, idempotent_replay=True)

            reason: str | None = None
            if graph is None:
                reason = "graph_not_found"
            elif graph.version != request.graph_version:
                reason = "incompatible_curriculum_version"
            elif request.concept_id not in {concept.id for concept in graph.concepts}:
                reason = "concept_not_in_curriculum_version"
            if graph is not None:
                self._register_curriculum(connection, graph)

            if request.supersedes_evidence_id:
                superseded = connection.execute(text(
                    "SELECT * FROM evidence WHERE id = :id AND learner_id = :learner_id"
                ), {"id": request.supersedes_evidence_id, "learner_id": learner_id}).mappings().first()
                if superseded is None:
                    reason = reason or "superseded_evidence_not_found"
                elif superseded["concept_id"] != request.concept_id:
                    reason = reason or "supersession_concept_mismatch"
                elif superseded["admission_status"] != "accepted":
                    reason = reason or "superseded_evidence_not_active"

            evidence_id = f"evidence_{uuid4().hex}"
            status = "rejected" if reason else "accepted"
            values = {
                "id": evidence_id, "learner_id": learner_id, "evidence_key": request.evidence_key,
                "concept_id": request.concept_id, "graph_id": request.graph_id, "graph_version": request.graph_version,
                "kind": request.kind, "outcome": request.outcome, "condition": request.condition.value,
                "score": request.score, "evaluator": request.evaluator, "reliability": request.reliability,
                "admission_status": status, "admission_reason": reason, "source_event_id": request.source_event_id,
                "supersedes_evidence_id": request.supersedes_evidence_id, "superseded_by_evidence_id": None,
                "policy_version": request.policy_version, "provenance_json": _json(request.provenance),
                "occurred_at": _utc(request.occurred_at), "created_at": now,
            }
            connection.execute(text("""
                INSERT INTO evidence
                (id, learner_id, evidence_key, concept_id, graph_id, graph_version, kind, outcome, condition, score,
                 evaluator, reliability, admission_status, admission_reason, source_event_id, supersedes_evidence_id,
                 superseded_by_evidence_id, policy_version, provenance_json, occurred_at, created_at)
                VALUES (:id, :learner_id, :evidence_key, :concept_id, :graph_id, :graph_version, :kind, :outcome,
                        :condition, :score, :evaluator, :reliability, :admission_status, :admission_reason,
                        :source_event_id, :supersedes_evidence_id, :superseded_by_evidence_id, :policy_version,
                        :provenance_json, :occurred_at, :created_at)
            """), values)

            state: LearnerConceptState | None = None
            if status == "accepted":
                if request.supersedes_evidence_id:
                    connection.execute(text("""
                        UPDATE evidence SET admission_status = 'superseded', superseded_by_evidence_id = :new_id
                        WHERE id = :old_id AND learner_id = :learner_id
                    """), {"new_id": evidence_id, "old_id": request.supersedes_evidence_id, "learner_id": learner_id})
                    connection.execute(text("""
                        UPDATE review_schedules SET status = 'superseded', updated_at = :now
                        WHERE learner_id = :learner_id AND originating_evidence_id = :old_id
                    """), {"now": now, "learner_id": learner_id, "old_id": request.supersedes_evidence_id})
                    self._refresh_misconception_lifecycle(connection, learner_id, request.concept_id, now)
                if request.misconception_code:
                    self._record_misconception(connection, learner_id, request, evidence_id, now)
                state = self._reduce_state(connection, learner_id, request.concept_id, request.graph_id, request.graph_version, request.policy_version)
                if request.kind == "review":
                    self._record_review_completion(connection, learner_id, request, evidence_id, now)
                if request.outcome in {"correct", "partial"}:
                    self._schedule_review(connection, learner_id, request, evidence_id, now)
            self._insert_system_event(connection, learner_id, "evidence.admitted", request.concept_id, {
                "evidenceId": evidence_id, "admissionStatus": status, "reason": reason,
            }, request.provenance, now)
            row = connection.execute(text("SELECT * FROM evidence WHERE id = :id"), {"id": evidence_id}).mappings().one()
            return EvidenceAdmissionResponse(evidence=self._evidence_from_row(row), learner_state=state)

    def _get_state_in_transaction(self, connection: Connection, learner_id: str, concept_id: str) -> LearnerConceptState | None:
        row = connection.execute(text("""
            SELECT * FROM learner_concept_states WHERE learner_id = :learner_id AND concept_id = :concept_id
        """), {"learner_id": learner_id, "concept_id": concept_id}).mappings().first()
        return self._state_from_row(row) if row else None

    def _reduce_state(self, connection: Connection, learner_id: str, concept_id: str, graph_id: str, graph_version: int, policy_version: str) -> LearnerConceptState:
        rows = connection.execute(text("""
            SELECT * FROM evidence WHERE learner_id = :learner_id AND concept_id = :concept_id
            AND admission_status = 'accepted' ORDER BY occurred_at ASC, created_at ASC
        """), {"learner_id": learner_id, "concept_id": concept_id}).mappings().all()
        latest = rows[-1] if rows else {"id": None, "reliability": 0, "condition": "independent", "outcome": None}
        reliability = float(latest["reliability"])
        independent = latest["condition"] == "independent"
        outcome = latest["outcome"]
        misconception = connection.execute(text("""
            SELECT 1 FROM misconception_hypotheses WHERE learner_id = :learner_id AND concept_id = :concept_id AND status = 'active'
        """), {"learner_id": learner_id, "concept_id": concept_id}).first()
        if not rows:
            state_status, confidence = "unexplored", 0.0
        elif outcome == "incorrect" and misconception:
            state_status, confidence = "misconception_detected", 0.1 * reliability
        elif outcome == "correct" and independent and reliability >= 0.5:
            state_status, confidence = "demonstrated", min(0.85, 0.7 * reliability + 0.1)
        elif outcome == "correct":
            state_status, confidence = "developing", min(0.55, (0.4 if independent else 0.3) + 0.2 * reliability)
        elif outcome == "partial":
            state_status, confidence = "developing", min(0.5, (0.3 if independent else 0.2) + 0.2 * reliability)
        else:
            state_status, confidence = "developing", max(0.05, 0.2 * (1 - reliability))
        uncertainty = max(0.1, 1 - reliability * (0.9 if independent else 0.65))
        existing = self._get_state_in_transaction(connection, learner_id, concept_id)
        now = utc_now()
        values = {
            "learner_id": learner_id, "concept_id": concept_id, "graph_id": graph_id,
            "graph_version": graph_version, "status": state_status, "confidence": round(confidence, 4),
            "uncertainty": round(uncertainty, 4), "version": (existing.version + 1) if existing else 1,
            "last_evidence_id": latest["id"], "policy_version": policy_version,
            "provenance_json": _json({"evidenceIds": [row["id"] for row in rows], "reducer": policy_version}),
            "created_at": existing.created_at if existing else now, "updated_at": now,
        }
        if existing:
            connection.execute(text("""
                UPDATE learner_concept_states SET graph_id=:graph_id, graph_version=:graph_version, status=:status,
                confidence=:confidence, uncertainty=:uncertainty, version=:version, last_evidence_id=:last_evidence_id,
                policy_version=:policy_version, provenance_json=:provenance_json, updated_at=:updated_at
                WHERE learner_id=:learner_id AND concept_id=:concept_id
            """), values)
        else:
            connection.execute(text("""
                INSERT INTO learner_concept_states
                (learner_id, concept_id, graph_id, graph_version, status, confidence, uncertainty, version,
                 last_evidence_id, policy_version, provenance_json, created_at, updated_at)
                VALUES (:learner_id, :concept_id, :graph_id, :graph_version, :status, :confidence, :uncertainty,
                        :version, :last_evidence_id, :policy_version, :provenance_json, :created_at, :updated_at)
            """), values)
        self._insert_system_event(connection, learner_id, "learner_state.updated", concept_id, {
            "evidenceId": latest["id"], "policyVersion": policy_version, "stateVersion": values["version"],
            "status": state_status,
        }, {"owner": "learner_state_service"}, now)
        return LearnerConceptState(
            learner_id=learner_id, concept_id=concept_id, graph_id=graph_id, graph_version=graph_version,
            status=state_status, confidence=values["confidence"], uncertainty=values["uncertainty"],
            version=values["version"], last_evidence_id=latest["id"], policy_version=policy_version,
            provenance=_object(values["provenance_json"]), created_at=values["created_at"], updated_at=now,
        )

    def withdraw_evidence(self, learner_id: str, evidence_id: str, reason: str, *, connection: Connection) -> None:
        """Exclude disputed evidence and recompute through the canonical reducer."""
        row = connection.execute(text("SELECT * FROM evidence WHERE id=:id AND learner_id=:owner"),
                                 {"id": evidence_id, "owner": learner_id}).mappings().first()
        if row is None or row["admission_status"] != "accepted":
            return
        now = utc_now()
        connection.execute(text("UPDATE evidence SET admission_status='rejected',admission_reason=:reason WHERE id=:id AND learner_id=:owner"),
                           {"id": evidence_id, "owner": learner_id, "reason": reason})
        connection.execute(text("UPDATE review_schedules SET status='superseded',updated_at=:now WHERE learner_id=:owner AND originating_evidence_id=:id"),
                           {"now": now, "owner": learner_id, "id": evidence_id})
        self._refresh_misconception_lifecycle(connection, learner_id, row["concept_id"], now)
        self._reduce_state(connection, learner_id, row["concept_id"], row["graph_id"], row["graph_version"], row["policy_version"])
        self._insert_system_event(connection, learner_id, "evidence.withdrawn", row["concept_id"],
                                  {"evidenceId": evidence_id, "reason": reason}, {"owner": "learner_state_service"}, now)

    def _insert_system_event(self, connection: Connection, learner_id: str, kind: str, concept_id: str | None, payload: dict[str, Any], provenance: dict[str, Any], now: datetime) -> None:
        connection.execute(text("""
            INSERT INTO state_events
            (id, learner_id, kind, concept_id, session_id, action_id, correlation_id, causation_id,
             idempotency_key, schema_version, payload_json, provenance_json, occurred_at, recorded_at)
            VALUES (:id, :learner_id, :kind, :concept_id, NULL, NULL, NULL, NULL, NULL, 1,
                    :payload_json, :provenance_json, :occurred_at, :recorded_at)
        """), {"id": f"state_event_{uuid4().hex}", "learner_id": learner_id, "kind": kind,
                 "concept_id": concept_id, "payload_json": _json(payload), "provenance_json": _json(provenance),
                 "occurred_at": now, "recorded_at": now})

    def _schedule_review(self, connection: Connection, learner_id: str, request: EvidenceCreate, evidence_id: str, now: datetime) -> None:
        from .review import memory as memory_store
        from .review.scheduling_authority import apply_timing, decide_timing, insert_evidence_linked_schedule

        memory_store.ensure_learner(connection, learner_id)
        existing = memory_store.get_memory(connection, learner_id, request.concept_id)
        if existing is None:
            memory_store.seed_memory(
                connection, learner_id=learner_id, concept_id=request.concept_id,
                graph_id=request.graph_id, graph_version=request.graph_version,
            )
            existing = memory_store.get_memory(connection, learner_id, request.concept_id)
        confidence = None
        if isinstance(request.provenance, dict):
            confidence = request.provenance.get("confidence") or request.provenance.get("learnerConfidence")
        decision = decide_timing(
            outcome=request.outcome,
            confidence=confidence,
            condition=request.condition.value,
            memory=existing,
            now=now,
        )
        if existing and request.kind == "review" and request.provenance.get("schedulerPendingConfidence"):
            # Review sessions finalize interval when confidence is submitted.
            interval = max(1, int(round(decision.interval_days)))
            due_at = now + __import__("datetime").timedelta(days=interval)
            insert_evidence_linked_schedule(
                connection,
                learner_id=learner_id,
                concept_id=request.concept_id,
                evidence_id=evidence_id,
                due_at=due_at,
                interval_days=interval,
                due_reason="Pending confidence",
                activity_type=(request.provenance or {}).get("questionType") or request.kind,
                confidence=confidence,
                scheduler_version=decision.scheduler_version,
                now=now,
            )
            return
        apply_timing(
            connection,
            learner_id=learner_id,
            concept_id=request.concept_id,
            decision=decision,
            outcome=request.outcome,
            confidence=confidence,
            score=request.score,
            question_type=(request.provenance or {}).get("questionType"),
            evidence_id=evidence_id,
            activity_type=(request.provenance or {}).get("questionType") or request.kind,
            apply_memory=bool(existing),
            mirror_schedule=True,
            now=now,
            source="evidence",
        )

    def _record_misconception(self, connection: Connection, learner_id: str, request: EvidenceCreate, evidence_id: str, now: datetime) -> None:
        row = connection.execute(text("""
            SELECT id FROM misconception_hypotheses WHERE learner_id=:learner_id AND concept_id=:concept_id AND code=:code
        """), {"learner_id": learner_id, "concept_id": request.concept_id, "code": request.misconception_code}).mappings().first()
        hypothesis_id = row["id"] if row else f"misconception_{uuid4().hex}"
        if row:
            connection.execute(text("""
                UPDATE misconception_hypotheses SET status='active', confidence=:confidence, updated_at=:now WHERE id=:id
            """), {"confidence": request.reliability, "now": now, "id": hypothesis_id})
        else:
            connection.execute(text("""
                INSERT INTO misconception_hypotheses(id, learner_id, concept_id, code, status, confidence, created_at, updated_at)
                VALUES (:id, :learner_id, :concept_id, :code, 'active', :confidence, :now, :now)
            """), {"id": hypothesis_id, "learner_id": learner_id, "concept_id": request.concept_id,
                     "code": request.misconception_code, "confidence": request.reliability, "now": now})
        connection.execute(text("""
            INSERT INTO misconception_evidence_links(hypothesis_id, evidence_id, relationship)
            VALUES (:hypothesis_id, :evidence_id, 'supports')
        """), {"hypothesis_id": hypothesis_id, "evidence_id": evidence_id})

    def _refresh_misconception_lifecycle(self, connection: Connection, learner_id: str, concept_id: str, now: datetime) -> None:
        connection.execute(text("""
            UPDATE misconception_hypotheses SET status='resolved', updated_at=:now
            WHERE learner_id=:learner_id AND concept_id=:concept_id AND status='active'
            AND NOT EXISTS (
                SELECT 1 FROM misconception_evidence_links links
                JOIN evidence evidence_record ON evidence_record.id = links.evidence_id
                WHERE links.hypothesis_id = misconception_hypotheses.id
                AND evidence_record.admission_status = 'accepted'
            )
        """), {"now": now, "learner_id": learner_id, "concept_id": concept_id})

    def _record_review_completion(self, connection: Connection, learner_id: str, request: EvidenceCreate, evidence_id: str, now: datetime) -> None:
        schedule = connection.execute(text("""
            SELECT id FROM review_schedules WHERE learner_id=:learner_id AND concept_id=:concept_id
            AND status IN ('scheduled', 'due') ORDER BY due_at ASC LIMIT 1
        """), {"learner_id": learner_id, "concept_id": request.concept_id}).mappings().first()
        if schedule is None:
            return
        connection.execute(text("UPDATE review_schedules SET status='completed', updated_at=:now WHERE id=:id"),
                           {"now": now, "id": schedule["id"]})
        connection.execute(text("""
            INSERT INTO review_history(id, schedule_id, learner_id, evidence_id, outcome, reviewed_at)
            VALUES (:id, :schedule_id, :learner_id, :evidence_id, :outcome, :now)
        """), {"id": f"review_history_{uuid4().hex}", "schedule_id": schedule["id"],
                 "learner_id": learner_id, "evidence_id": evidence_id, "outcome": request.outcome, "now": now})

    def review_queue(self, learner_id: str, as_of: datetime | None = None, include_future: bool = False) -> list[ReviewSchedule]:
        now = _utc(as_of)
        with self.store.transaction() as connection:
            connection.execute(text("""
                UPDATE review_schedules SET status='due', updated_at=:now
                WHERE learner_id=:learner_id AND status='scheduled' AND due_at <= :now
            """), {"now": now, "learner_id": learner_id})
            clause = "status IN ('scheduled', 'due')" if include_future else "status = 'due'"
            rows = connection.execute(text(f"""
                SELECT * FROM review_schedules WHERE learner_id=:learner_id AND {clause} ORDER BY due_at ASC
            """), {"learner_id": learner_id}).mappings().all()
        return [ReviewSchedule(**dict(row)) for row in rows]

    @staticmethod
    def _branch_from_row(row: Any) -> BranchRecord:
        return BranchRecord(
            id=row["id"], learner_id=row["learner_id"], session_id=row["session_id"],
            parent_branch_id=row["parent_branch_id"], anchor=DurableBranchAnchor(**_object(row["anchor_json"])),
            return_position=Position(**_object(row["return_position_json"])), lifecycle=row["lifecycle"],
            local_gear=row["local_gear"], summary=row["summary"], revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"], closed_at=row["closed_at"],
        )

    def create_branch(self, learner_id: str, request: BranchCreate) -> BranchRecord:
        session = self.store.get_session(request.session_id)
        if session is None or session.learner_id != learner_id:
            raise StateServiceError("session_not_found", "The learner-owned session does not exist.", 404)
        now = utc_now()
        branch_id = f"branch_{uuid4().hex}"
        with self.store.transaction() as connection:
            self._ensure_learner(connection, learner_id)
            if request.parent_branch_id:
                parent = connection.execute(text("""
                    SELECT * FROM branches WHERE id=:id AND learner_id=:learner_id AND session_id=:session_id
                """), {"id": request.parent_branch_id, "learner_id": learner_id, "session_id": request.session_id}).mappings().first()
                if parent is None:
                    raise StateServiceError("parent_branch_not_found", "The parent branch is outside this learner session.", 404)
                if parent["lifecycle"] != "open":
                    raise StateServiceError("parent_branch_closed", "A child cannot be added to a closed branch.", 409)
            connection.execute(text("""
                INSERT INTO branches
                (id, learner_id, session_id, parent_branch_id, anchor_json, return_position_json, lifecycle,
                 local_gear, summary, revision, created_at, updated_at, closed_at)
                VALUES (:id, :learner_id, :session_id, :parent_branch_id, :anchor_json, :return_position_json,
                        'open', :local_gear, :summary, 1, :now, :now, NULL)
            """), {"id": branch_id, "learner_id": learner_id, "session_id": request.session_id,
                     "parent_branch_id": request.parent_branch_id, "anchor_json": request.anchor.model_dump_json(by_alias=True),
                     "return_position_json": request.return_position.model_dump_json(by_alias=True),
                     "local_gear": request.local_gear.value if request.local_gear else None, "summary": request.summary, "now": now})
            row = connection.execute(text("SELECT * FROM branches WHERE id=:id"), {"id": branch_id}).mappings().one()
            return self._branch_from_row(row)

    def get_branch(self, learner_id: str, branch_id: str) -> BranchRecord:
        with self.store.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM branches WHERE id=:id AND learner_id=:learner_id"),
                                     {"id": branch_id, "learner_id": learner_id}).mappings().first()
        if row is None:
            raise StateServiceError("branch_not_found", "Branch does not exist for this learner.", 404)
        return self._branch_from_row(row)

    def list_branches(self, learner_id: str, session_id: str | None = None, include_closed: bool = False) -> list[BranchRecord]:
        """List a learner's sidecars in stable tree order."""
        filters = ["learner_id=:learner_id"]
        params: dict[str, Any] = {"learner_id": learner_id}
        if session_id:
            filters.append("session_id=:session_id")
            params["session_id"] = session_id
        if not include_closed:
            filters.append("lifecycle='open'")
        with self.store.engine.connect() as connection:
            rows = connection.execute(text(
                f"SELECT * FROM branches WHERE {' AND '.join(filters)} ORDER BY created_at ASC"
            ), params).mappings().all()
        return [self._branch_from_row(row) for row in rows]

    def get_branch_context(self, learner_id: str, branch_id: str) -> BranchContextResponse:
        """Return a branch with its parent chain, children, and anchored notes."""
        branch = self.get_branch(learner_id, branch_id)
        with self.store.engine.connect() as connection:
            child_rows = connection.execute(text(
                "SELECT * FROM branches WHERE learner_id=:learner_id AND parent_branch_id=:parent_id ORDER BY created_at ASC"
            ), {"learner_id": learner_id, "parent_id": branch_id}).mappings().all()
            note_rows = connection.execute(text(
                "SELECT * FROM notes WHERE learner_id=:learner_id AND branch_id=:branch_id AND deleted_at IS NULL ORDER BY updated_at ASC"
            ), {"learner_id": learner_id, "branch_id": branch_id}).mappings().all()

            ancestors: list[BranchRecord] = []
            parent_id = branch.parent_branch_id
            while parent_id:
                row = connection.execute(text(
                    "SELECT * FROM branches WHERE id=:id AND learner_id=:learner_id"
                ), {"id": parent_id, "learner_id": learner_id}).mappings().first()
                if row is None:
                    break
                parent = self._branch_from_row(row)
                ancestors.insert(0, parent)
                parent_id = parent.parent_branch_id
        return BranchContextResponse(
            branch=branch,
            ancestors=ancestors,
            children=[self._branch_from_row(row) for row in child_rows],
            notes=[self._note_from_row(row) for row in note_rows],
        )

    def update_branch(self, learner_id: str, branch_id: str, request: BranchUpdate) -> BranchRecord:
        with self.store.transaction() as connection:
            row = connection.execute(text("SELECT * FROM branches WHERE id=:id AND learner_id=:learner_id"),
                                     {"id": branch_id, "learner_id": learner_id}).mappings().first()
            if row is None:
                raise StateServiceError("branch_not_found", "Branch does not exist for this learner.", 404)
            if row["lifecycle"] != "open":
                raise StateServiceError("branch_closed", "Closed branches are immutable.", 409)
            if row["revision"] != request.expected_revision:
                raise StateServiceError("revision_conflict", "The branch changed; reload before updating.", 409)
            values = {"id": branch_id, "learner_id": learner_id, "revision": row["revision"] + 1, "now": utc_now(),
                      "return_position_json": request.return_position.model_dump_json(by_alias=True) if request.return_position else row["return_position_json"],
                      "local_gear": request.local_gear.value if request.local_gear else row["local_gear"],
                      "summary": request.summary if request.summary is not None else row["summary"]}
            connection.execute(text("""
                UPDATE branches SET return_position_json=:return_position_json, local_gear=:local_gear,
                summary=:summary, revision=:revision, updated_at=:now WHERE id=:id AND learner_id=:learner_id
            """), values)
            updated = connection.execute(text("SELECT * FROM branches WHERE id=:id"), {"id": branch_id}).mappings().one()
            return self._branch_from_row(updated)

    def close_branch(self, learner_id: str, branch_id: str) -> BranchRecord:
        with self.store.transaction() as connection:
            row = connection.execute(text("SELECT * FROM branches WHERE id=:id AND learner_id=:learner_id"),
                                     {"id": branch_id, "learner_id": learner_id}).mappings().first()
            if row is None:
                raise StateServiceError("branch_not_found", "Branch does not exist for this learner.", 404)
            if row["lifecycle"] == "open":
                now = utc_now()
                connection.execute(text("""
                    UPDATE branches SET lifecycle='closed', revision=revision+1, updated_at=:now, closed_at=:now
                    WHERE id=:id AND learner_id=:learner_id
                """), {"now": now, "id": branch_id, "learner_id": learner_id})
            updated = connection.execute(text("SELECT * FROM branches WHERE id=:id"), {"id": branch_id}).mappings().one()
            return self._branch_from_row(updated)

    @staticmethod
    def _note_from_row(row: Any) -> NoteRecord:
        return NoteRecord(
            id=row["id"], learner_id=row["learner_id"], scope=row["scope"], body=row["body"],
            concept_id=row["concept_id"], lesson_id=row["lesson_id"], branch_id=row["branch_id"],
            revision=row["revision"], provenance=_object(row["provenance_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def create_note(self, learner_id: str, request: NoteCreate) -> NoteRecord:
        now = utc_now()
        note_id = f"note_{uuid4().hex}"
        with self.store.transaction() as connection:
            self._ensure_learner(connection, learner_id)
            if request.branch_id:
                branch = connection.execute(text("SELECT 1 FROM branches WHERE id=:id AND learner_id=:learner_id"),
                                            {"id": request.branch_id, "learner_id": learner_id}).first()
                if branch is None:
                    raise StateServiceError("branch_not_found", "The note branch anchor is outside this learner.", 404)
            values = {"id": note_id, "learner_id": learner_id, "scope": request.scope, "body": request.body,
                      "concept_id": request.concept_id, "lesson_id": request.lesson_id, "branch_id": request.branch_id,
                      "revision": 1, "provenance_json": _json(request.provenance), "now": now}
            connection.execute(text("""
                INSERT INTO notes(id, learner_id, scope, body, concept_id, lesson_id, branch_id, revision,
                                  provenance_json, created_at, updated_at, deleted_at)
                VALUES (:id, :learner_id, :scope, :body, :concept_id, :lesson_id, :branch_id, :revision,
                        :provenance_json, :now, :now, NULL)
            """), values)
            connection.execute(text("""
                INSERT INTO note_revisions(note_id, revision, body, provenance_json, created_at)
                VALUES (:id, 1, :body, :provenance_json, :now)
            """), values)
            row = connection.execute(text("SELECT * FROM notes WHERE id=:id"), {"id": note_id}).mappings().one()
            return self._note_from_row(row)

    def get_note(self, learner_id: str, note_id: str) -> NoteRecord:
        with self.store.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM notes WHERE id=:id AND learner_id=:learner_id AND deleted_at IS NULL"),
                                     {"id": note_id, "learner_id": learner_id}).mappings().first()
        if row is None:
            raise StateServiceError("note_not_found", "Note does not exist for this learner.", 404)
        return self._note_from_row(row)

    def list_notes(self, learner_id: str) -> list[NoteRecord]:
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM notes WHERE learner_id=:learner_id AND deleted_at IS NULL ORDER BY updated_at DESC
            """), {"learner_id": learner_id}).mappings().all()
        return [self._note_from_row(row) for row in rows]

    def update_note(self, learner_id: str, note_id: str, request: NoteUpdate) -> NoteRecord:
        now = utc_now()
        with self.store.transaction() as connection:
            row = connection.execute(text("SELECT * FROM notes WHERE id=:id AND learner_id=:learner_id AND deleted_at IS NULL"),
                                     {"id": note_id, "learner_id": learner_id}).mappings().first()
            if row is None:
                raise StateServiceError("note_not_found", "Note does not exist for this learner.", 404)
            if row["revision"] != request.expected_revision:
                raise StateServiceError("revision_conflict", "The note changed; reload before updating.", 409)
            revision = row["revision"] + 1
            values = {"id": note_id, "learner_id": learner_id, "body": request.body, "revision": revision,
                      "provenance_json": _json(request.provenance), "now": now}
            connection.execute(text("""
                UPDATE notes SET body=:body, revision=:revision, provenance_json=:provenance_json, updated_at=:now
                WHERE id=:id AND learner_id=:learner_id
            """), values)
            connection.execute(text("""
                INSERT INTO note_revisions(note_id, revision, body, provenance_json, created_at)
                VALUES (:id, :revision, :body, :provenance_json, :now)
            """), values)
            updated = connection.execute(text("SELECT * FROM notes WHERE id=:id"), {"id": note_id}).mappings().one()
            return self._note_from_row(updated)

    def note_revisions(self, learner_id: str, note_id: str) -> list[NoteRevision]:
        self.get_note(learner_id, note_id)
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT note_id, revision, body, provenance_json, created_at FROM note_revisions
                WHERE note_id=:id ORDER BY revision ASC
            """), {"id": note_id}).mappings().all()
        return [NoteRevision(note_id=row["note_id"], revision=row["revision"], body=row["body"],
                             provenance=_object(row["provenance_json"]), created_at=row["created_at"]) for row in rows]

    def delete_note(self, learner_id: str, note_id: str) -> None:
        now = utc_now()
        with self.store.transaction() as connection:
            result = connection.execute(text("""
                UPDATE notes SET deleted_at=:now, updated_at=:now WHERE id=:id AND learner_id=:learner_id AND deleted_at IS NULL
            """), {"now": now, "id": note_id, "learner_id": learner_id})
            if result.rowcount == 0:
                raise StateServiceError("note_not_found", "Note does not exist for this learner.", 404)
