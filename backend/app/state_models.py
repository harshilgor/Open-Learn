"""Typed contracts for durable learner state and learner-owned artifacts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .session_models import ApiModel, TeachingGear


class ConceptStateStatus(StrEnum):
    unexplored = "unexplored"
    exposed = "exposed"
    developing = "developing"
    demonstrated = "demonstrated"
    review_due = "review_due"
    misconception_detected = "misconception_detected"


class EvidenceCondition(StrEnum):
    independent = "independent"
    assisted = "assisted"


class EvidenceAdmissionStatus(StrEnum):
    accepted = "accepted"
    rejected = "rejected"
    superseded = "superseded"


class LearnerConceptState(ApiModel):
    learner_id: str
    concept_id: str
    graph_id: str
    graph_version: int
    status: ConceptStateStatus
    confidence: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    version: int = Field(ge=1)
    last_evidence_id: str | None = None
    policy_version: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class LearnerStateResponse(ApiModel):
    learner_id: str
    states: list[LearnerConceptState] = Field(default_factory=list)


class StateEventCreate(ApiModel):
    kind: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    concept_id: str | None = Field(default=None, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    action_id: str | None = Field(default=None, max_length=160)
    correlation_id: str | None = Field(default=None, max_length=160)
    causation_id: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, max_length=200)
    schema_version: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class StateEvent(ApiModel):
    id: str
    learner_id: str
    kind: str
    concept_id: str | None = None
    session_id: str | None = None
    action_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None
    schema_version: int
    payload: dict[str, Any]
    provenance: dict[str, Any]
    occurred_at: datetime
    recorded_at: datetime


class EvidenceCreate(ApiModel):
    evidence_key: str = Field(min_length=1, max_length=200)
    concept_id: str = Field(min_length=1, max_length=160)
    graph_id: str = Field(min_length=1, max_length=160)
    graph_version: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    outcome: Literal["correct", "partial", "incorrect"]
    condition: EvidenceCondition
    score: float | None = Field(default=None, ge=0, le=1)
    evaluator: str = Field(min_length=1, max_length=160)
    reliability: float = Field(ge=0, le=1)
    source_event_id: str | None = Field(default=None, max_length=160)
    supersedes_evidence_id: str | None = Field(default=None, max_length=160)
    misconception_code: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    policy_version: Literal["learner-reducer-v1"] = "learner-reducer-v1"
    provenance: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class EvidenceRecord(ApiModel):
    id: str
    learner_id: str
    evidence_key: str
    concept_id: str
    graph_id: str
    graph_version: int
    kind: str
    outcome: str
    condition: EvidenceCondition
    score: float | None = None
    evaluator: str
    reliability: float
    admission_status: EvidenceAdmissionStatus
    admission_reason: str | None = None
    source_event_id: str | None = None
    supersedes_evidence_id: str | None = None
    superseded_by_evidence_id: str | None = None
    policy_version: str
    provenance: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class EvidenceAdmissionResponse(ApiModel):
    evidence: EvidenceRecord
    learner_state: LearnerConceptState | None = None
    idempotent_replay: bool = False


class ReviewSchedule(ApiModel):
    id: str
    learner_id: str
    concept_id: str
    originating_evidence_id: str
    due_at: datetime
    status: Literal["scheduled", "due", "completed", "cancelled", "superseded"]
    interval_days: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class Position(ApiModel):
    concept_id: str | None = None
    lesson_id: str | None = None
    block_id: str | None = None
    offset: int | None = Field(default=None, ge=0)


class DurableBranchAnchor(ApiModel):
    concept_id: str | None = None
    lesson_id: str | None = None
    block_id: str | None = None
    selected_text: str | None = Field(default=None, max_length=2000)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> DurableBranchAnchor:
        if self.start_offset is not None and self.end_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("endOffset must be greater than or equal to startOffset")
        return self


class BranchCreate(ApiModel):
    session_id: str = Field(min_length=1, max_length=160)
    parent_branch_id: str | None = Field(default=None, max_length=160)
    anchor: DurableBranchAnchor
    return_position: Position
    local_gear: TeachingGear | None = None
    summary: str | None = Field(default=None, max_length=4000)


class BranchUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    return_position: Position | None = None
    local_gear: TeachingGear | None = None
    summary: str | None = Field(default=None, max_length=4000)


class BranchRecord(ApiModel):
    id: str
    learner_id: str
    session_id: str
    parent_branch_id: str | None = None
    anchor: DurableBranchAnchor
    return_position: Position
    lifecycle: Literal["open", "closed"]
    local_gear: TeachingGear | None = None
    summary: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class NoteCreate(ApiModel):
    scope: Literal["learner", "private"] = "private"
    body: str = Field(min_length=1, max_length=20000)
    concept_id: str | None = Field(default=None, max_length=160)
    lesson_id: str | None = Field(default=None, max_length=160)
    branch_id: str | None = Field(default=None, max_length=160)
    # A document is a valid learning anchor even before the learner has chosen
    # a curriculum concept or started a lesson.
    document_id: str | None = Field(default=None, max_length=160)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_anchor(self) -> NoteCreate:
        if not any((self.concept_id, self.lesson_id, self.branch_id, self.document_id)):
            raise ValueError("A note must have a conceptId, lessonId, branchId, or documentId anchor")
        return self


class NoteUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=20000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class NoteRecord(ApiModel):
    id: str
    learner_id: str
    scope: Literal["learner", "private"]
    body: str
    concept_id: str | None = None
    lesson_id: str | None = None
    branch_id: str | None = None
    document_id: str | None = None
    revision: int
    provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class NoteRevision(ApiModel):
    note_id: str
    revision: int
    body: str
    provenance: dict[str, Any]
    created_at: datetime
