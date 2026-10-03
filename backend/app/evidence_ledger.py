"""Append-only interpretations of authoritative observations, never attempt copies.

Call inside the owning command transaction. Receipt sequence is a commit fence;
meaningful occurrence time and opaque ID determine reproducible replay order.
This module deliberately does not implement a second mastery reducer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import text

from .shared_contracts import Contract, LearningEvent, EventConceptLink, Identifier, RevisionRef
from .execution import ProjectionWatermarks


class Observation(Contract):
    event: LearningEvent
    event_type: Literal["QUIZ_RESPONSE", "REVIEW_RESPONSE", "HINT_REQUESTED", "ANSWER_EXPOSED",
        "RETRY_SUBMITTED", "CONCEPT_TAUGHT", "LESSON_VIEWED", "LECTURE_CONCEPT_OBSERVED",
        "SELF_REPORT", "SKIP", "INTERRUPTED_EXPOSURE", "SOURCE_CORRECTED", "EVIDENCE_RETRACTED", "EVALUATION_CORRECTED"]
    course_id: Identifier | None = None
    activity_id: Identifier | None = None
    session_id: Identifier | None = None
    family_id: str | None = Field(default=None, max_length=160)
    graph: RevisionRef | None = None
    concept_outcomes: dict[str, Literal["correct", "partial", "incorrect", "ungraded"]] = Field(default_factory=dict)
    origin_command: str = Field(min_length=1, max_length=300)
    concepts: tuple[EventConceptLink, ...] = ()
    presentation: RevisionRef | None = None
    evaluation: RevisionRef | None = None
    rubric: RevisionRef | None = None
    assistance: Literal["independent", "assisted", "unknown"] = "unknown"
    outcome: Literal["correct", "partial", "incorrect", "ungraded"] = "ungraded"
    admission: Literal["admitted", "excluded", "not_performance"] = "not_performance"
    exclusion_reasons: tuple[str, ...] = ()
    target_event_id: Identifier | None = None
    detail: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        for link in self.concepts:
            if link.owner_id != self.event.owner_id or link.event_id != self.event.id:
                raise ValueError("Concept attribution belongs to another event")
        if self.admission == "admitted":
            if self.event_type not in {"QUIZ_RESPONSE", "REVIEW_RESPONSE", "EVALUATION_CORRECTED"}:
                raise ValueError("Exposure, skips and self-report are not scored performance")
            if not all((self.presentation, self.evaluation, self.rubric, self.event.attempt_id)) or self.outcome == "ungraded":
                raise ValueError("Performance requires original presentation, rubric, attempt and evaluation")
            if self.exclusion_reasons:
                raise ValueError("Excluded observations cannot be admitted")
        if self.admission == "excluded" and not self.exclusion_reasons:
            raise ValueError("Exclusion requires an explanation")
        if self.event_type in {"SOURCE_CORRECTED", "EVIDENCE_RETRACTED", "EVALUATION_CORRECTED"} and not self.target_event_id:
            raise ValueError("Corrections must reference original evidence")
        return self


def event_id(owner: str, key: str) -> str:
    return "observation_" + sha256((owner + "\0" + key).encode()).hexdigest()[:40]


def _fingerprint(observation: Observation):
    data = observation.model_dump(mode="json")
    data["event"].pop("received_at")
    return data


class EvidenceLedger:
    def __init__(self, store):
        self.store = store

    def backfill(self, conn, owner):
        """Deterministic, conservative legacy admission; original rows untouched."""
        from .identity import assert_owner_active
        assert_owner_active(conn, owner)
        rows = conn.execute(text("SELECT id,payload FROM practice_records WHERE owner_id=:owner AND kind='attempt' ORDER BY id"), {"owner": owner}).mappings().all()
        for row in rows:
            key = "attempt:" + row["id"]
            if conn.execute(text("SELECT 1 FROM learning_event_ledger WHERE owner_id=:owner AND deduplication_key=:key"), {"owner": owner, "key": key}).first():
                continue
            attempt = json.loads(row["payload"])
            self.emit(conn, owner, key, "SKIP" if attempt.get("outcome") == "skip" else "REVIEW_RESPONSE" if attempt.get("reviewSessionId") else "QUIZ_RESPONSE",
                concept_id=attempt.get("conceptId"), occurred_at=attempt.get("createdAt") or datetime(1970, 1, 1, tzinfo=timezone.utc),
                attempt_id=row["id"], activity_id=attempt.get("quizId") or attempt.get("reviewSessionId"),
                admission="not_performance" if attempt.get("outcome") == "skip" else "excluded",
                exclusion_reasons=() if attempt.get("outcome") == "skip" else ("legacy_admission_requires_review",))
        rows = conn.execute(text("SELECT * FROM state_events WHERE learner_id=:owner ORDER BY id"), {"owner": owner}).mappings().all()
        for row in rows:
            category = {"lesson.completed": "CONCEPT_TAUGHT", "concept.taught": "CONCEPT_TAUGHT", "lesson.viewed": "LESSON_VIEWED",
                "confidence.reported": "SELF_REPORT", "hint.requested": "HINT_REQUESTED", "answer.exposed": "ANSWER_EXPOSED"}.get(row["kind"])
            if not category:
                continue
            key = "state:" + row["id"]
            if conn.execute(text("SELECT 1 FROM learning_event_ledger WHERE owner_id=:owner AND deduplication_key=:key"), {"owner": owner, "key": key}).first():
                continue
            self.emit(conn, owner, key, category, concept_id=row["concept_id"], occurred_at=row["occurred_at"],
                activity_id=row["session_id"], detail=row["payload_json"][:2000] if category == "SELF_REPORT" else None)
        return {"status": "completed", "watermark": self.history(conn, owner)["watermark"]}

    def record_learning_event(self, conn, owner: str, observation: Observation) -> tuple[str, int]:
        from .identity import assert_owner_active
        assert_owner_active(conn, owner)
        if observation.event.owner_id != owner:
            raise ValueError("Observation owner mismatch")
        # Lock this owner's sequence before checking idempotency; concurrent
        # retries cannot race past the check on either supported database.
        conn.execute(text("INSERT INTO learning_event_sequences(owner_id,sequence) VALUES(:owner,0) ON CONFLICT(owner_id) DO NOTHING"), {"owner": owner})
        conn.execute(text("UPDATE learning_event_sequences SET sequence=sequence WHERE owner_id=:owner"), {"owner": owner})
        existing = conn.execute(text("SELECT id,sequence,payload FROM learning_event_ledger WHERE owner_id=:owner AND deduplication_key=:key"), {"owner": owner, "key": observation.event.deduplication_key}).mappings().first()
        if existing:
            if _fingerprint(Observation.model_validate_json(existing["payload"])) != _fingerprint(observation):
                raise ValueError("Observation idempotency key reused with different input")
            return existing["id"], existing["sequence"]
        if observation.target_event_id:
            target = conn.execute(text("SELECT payload FROM learning_event_ledger WHERE owner_id=:owner AND id=:id"), {"owner": owner, "id": observation.target_event_id}).scalar_one_or_none()
            if target is None:
                raise ValueError("Correction target is unavailable for this owner")
            original = Observation.model_validate_json(target)
            if original.target_event_id:
                raise ValueError("Corrections reference the original observation, not another correction")
            if observation.event.attempt_id and observation.event.attempt_id != original.event.attempt_id:
                raise ValueError("Correction cannot substitute another attempt")
        sequence = conn.execute(text("UPDATE learning_event_sequences SET sequence=sequence+1 WHERE owner_id=:owner RETURNING sequence"), {"owner": owner}).scalar_one()
        conn.execute(text("""INSERT INTO learning_event_ledger(owner_id,id,sequence,deduplication_key,occurred_at,received_at,event_type,attempt_id,payload)
            VALUES(:owner,:id,:sequence,:key,:occurred,:received,:type,:attempt,:payload)"""), {
                "owner": owner, "id": observation.event.id, "sequence": sequence,
                "key": observation.event.deduplication_key, "occurred": observation.event.occurred_at.timestamp(),
                "received": observation.event.received_at.timestamp(), "type": observation.event_type,
                "attempt": observation.event.attempt_id, "payload": observation.model_dump_json()})
        for link in observation.concepts:
            conn.execute(text("INSERT INTO learning_event_concepts(owner_id,event_id,concept_id,capability,payload) VALUES(:owner,:event,:concept,:capability,:payload)"), {
                "owner": owner, "event": observation.event.id, "concept": link.concept_id,
                "capability": link.capability.value, "payload": link.model_dump_json()})
        if observation.target_event_id and original.evaluation:
            from .decision_store import DecisionStore, Invalidation
            DecisionStore().invalidate(conn, owner, Invalidation(owner_id=owner, id=observation.event.id,
                dependency=original.evaluation, reason="evidence_corrected",
                created_at=observation.event.received_at, replacement=observation.evaluation))
        ProjectionWatermarks.advance(conn, owner, "evidence_ledger", "all", sequence)
        from .unified_learner_state import UnifiedLearnerState
        UnifiedLearnerState(self.store).rebuild(conn, owner)
        from .hypothesis_service import HypothesisService
        HypothesisService(self.store).refresh(conn, owner)
        if observation.admission == "admitted" and observation.event_type in {"QUIZ_RESPONSE", "REVIEW_RESPONSE"} and observation.outcome in {"partial", "incorrect"}:
            from .execution import Outbox
            key = "hypothesis:" + observation.event.id
            Outbox.emit(conn, owner, "execution.job.requested", observation.event.id, key,
                {"kind": "hypothesis_analyze", "input": {"event_id": observation.event.id}, "key": key})
        return observation.event.id, sequence

    def history(self, conn, owner: str, concept_id: str | None = None):
        from .identity import assert_owner_active
        assert_owner_active(conn, owner)
        rows = conn.execute(text("SELECT sequence,payload FROM learning_event_ledger WHERE owner_id=:owner ORDER BY occurred_at,id"), {"owner": owner}).mappings().all()
        observations = [(r["sequence"], Observation.model_validate_json(r["payload"])) for r in rows]
        # Resolve validity in a separate pass, so a correction still applies to
        # an original with a later offline occurrence timestamp.
        corrections = {}
        correction_sequences = {}
        for sequence, value in observations:
            if value.target_event_id:
                # Interpretation revisions are ordered by committed receipt,
                # while performance remains ordered by original occurrence.
                # Regrades retain occurrence time and must supersede a later
                # dated challenge withdrawal, including offline observations.
                if sequence > correction_sequences.get(value.target_event_id, -1):
                    corrections[value.target_event_id] = value
                    correction_sequences[value.target_event_id] = sequence
        entries = []
        for sequence, value in observations:
            if value.target_event_id:
                continue
            if concept_id and concept_id not in {link.concept_id for link in value.concepts}:
                continue
            correction = corrections.get(value.event.id)
            effective = correction if correction and correction.event_type == "EVALUATION_CORRECTED" else value
            excluded = bool(correction and correction.event_type != "EVALUATION_CORRECTED") or effective.admission == "excluded"
            category = "excluded" if excluded else "exposure"
            if not excluded and effective.admission == "admitted":
                category = "failure" if effective.outcome == "incorrect" else f"{effective.assistance}_{effective.outcome}"
            elif not excluded and value.event_type == "SELF_REPORT":
                category = "self_report"
            elif not excluded and value.event_type in {"HINT_REQUESTED", "ANSWER_EXPOSED", "RETRY_SUBMITTED"}:
                category = "assistance"
            elif not excluded and value.event_type == "SKIP":
                category = "skip"
            question = None
            if value.presentation:
                saved = conn.execute(text("SELECT payload FROM practice_records WHERE owner_id=:owner AND id=:id AND kind='presentation'"), {"owner": owner, "id": value.presentation.id}).scalar_one_or_none()
                if saved:
                    public = json.loads(saved)
                    question = {"id": value.presentation.id, "stem": public.get("stem", "")}
            entries.append({"id": value.event.id, "sequence": sequence, "eventType": value.event_type,
                "occurredAt": value.event.occurred_at.isoformat(), "category": category,
                "attemptId": value.event.attempt_id, "activityId": value.activity_id,
                "sessionId": value.session_id, "familyId": effective.family_id or value.family_id,
                "assistance": effective.assistance, "outcome": effective.outcome,
                "conceptOutcomes": effective.concept_outcomes,
                "graph": value.graph.model_dump(mode="json") if value.graph else None,
                "question": question,
                "source": value.event.source.model_dump(mode="json") if value.event.source else None,
                "reasons": list(correction.exclusion_reasons if excluded and correction else effective.exclusion_reasons),
                "correctionId": correction.event.id if correction else None,
                "concepts": [link.model_dump(mode="json") for link in (effective.concepts or value.concepts)]})
        return {"policyRevision": "ledger-history-v1", "watermark": max((n for n, _ in observations), default=0), "entries": entries}

    def emit(self, conn, owner, key, event_type, *, concept_id=None, occurred_at=None, attempt_id=None,
             activity_id=None, source=None, target_event_id=None, concepts=None, **kwargs):
        now = datetime.now(timezone.utc)
        if occurred_at is None:
            previous = conn.execute(text("SELECT occurred_at FROM learning_event_ledger WHERE owner_id=:owner AND deduplication_key=:key"), {"owner": owner, "key": key}).scalar_one_or_none()
            if previous is not None:
                occurred_at = datetime.fromtimestamp(previous, timezone.utc)
        if isinstance(occurred_at, (float, int)):
            occurred_at = datetime.fromtimestamp(occurred_at, timezone.utc)
        occurred = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) if isinstance(occurred_at, str) else occurred_at or now
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        identifier = event_id(owner, key)
        kind = "correction" if target_event_id else "answer" if event_type.endswith("RESPONSE") else "skip" if event_type == "SKIP" else "assistance" if event_type in {"HINT_REQUESTED", "ANSWER_EXPOSED", "RETRY_SUBMITTED"} else "exposure"
        links = concepts if concepts is not None else (EventConceptLink(owner_id=owner, id=identifier + "_link", revision=1, event_id=identifier,
            concept_id=concept_id, capability="explain", role="target", attribution_basis="unknown", uncertainty="unknown"),) if concept_id else ()
        observation = Observation(event=LearningEvent(owner_id=owner, id=identifier, revision=1,
            observation=kind, occurred_at=occurred, received_at=now, deduplication_key=key,
            attempt_id=attempt_id, source=source), event_type=event_type, origin_command=key,
            concepts=links, activity_id=activity_id, target_event_id=target_event_id, **kwargs)
        return self.record_learning_event(conn, owner, observation)
