"""Versioned inter-service contracts for Open Learn 2.0.

These are not replacements for legacy HTTP request models. Domain services own
authorization and persistence; an owner_id supplied by a client is not identity.
Unknown fields/revisions fail closed instead of silently losing new evidence.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from enum import Enum
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")]
Revision = Annotated[int, Field(strict=True, ge=1)]
ReasonCode = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def new_id(prefix: str) -> str:
    """Opaque IDs retain the repository's prefix_UUID convention."""
    if not prefix.isascii() or not prefix.isidentifier() or len(prefix) > 40:
        raise ValueError("Invalid identifier prefix")
    return f"{prefix}_{uuid4().hex}"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_revision: Literal[1] = 1

    @field_validator("schema_revision", mode="before")
    @classmethod
    def supported_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported contract schema revision")
        return value


# Compatibility vocabulary for the separately supervised worker and the
# original cloud foundation API. Core feature services use the stricter
# revision-addressed contracts below.
class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_revision: Literal[1] = 1


class EvidenceQuality(str, Enum):
    valid = "valid"
    uncertain = "uncertain"
    excluded = "excluded"
    legacy_unknown = "legacy_unknown"


class EvidenceStrength(str, Enum):
    insufficient = "insufficient"
    limited = "limited"
    supported = "supported"
    conflicting = "conflicting"


class HypothesisSupport(str, Enum):
    tentative = "tentative"
    supported = "supported"
    contradicted = "contradicted"


class AcademicConfidence(str, Enum):
    direct = "direct"
    inferred = "inferred"
    tentative = "tentative"
    unknown = "unknown"


class Capability(str, Enum):
    recognition = "recognition"
    recall = "recall"
    explanation = "explanation"
    procedural_execution = "procedural_execution"
    transfer = "transfer"


class ObservationType(str, Enum):
    quiz_response = "QUIZ_RESPONSE"
    review_response = "REVIEW_RESPONSE"
    hint_requested = "HINT_REQUESTED"
    answer_exposed = "ANSWER_EXPOSED"
    retry_submitted = "RETRY_SUBMITTED"
    concept_taught = "CONCEPT_TAUGHT"
    lesson_viewed = "LESSON_VIEWED"
    lecture_concept_observed = "LECTURE_CONCEPT_OBSERVED"
    self_report = "SELF_REPORT"
    skipped = "SKIPPED"
    source_corrected = "SOURCE_CORRECTED"
    evidence_retracted = "EVIDENCE_RETRACTED"


class Dependency(Record):
    kind: Literal["source", "evaluation", "learner", "academic", "graph", "policy", "context"]
    entity_id: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=160)


class RevisionSnapshot(Record):
    learner_projection_revision: int = Field(ge=0)
    academic_snapshot_revision: int = Field(ge=0)
    concept_graph_revision: str = Field(min_length=1, max_length=160)
    policy_revision: str = Field(min_length=1, max_length=160)
    context_manifest_id: str = Field(min_length=1, max_length=160)
    dependencies: tuple[Dependency, ...] = Field(default_factory=tuple, max_length=500)

    @model_validator(mode="after")
    def unique_dependencies(self):
        identities = [(d.kind, d.entity_id, d.revision) for d in self.dependencies]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate decision dependency")
        return self


class LearningDecision(Record):
    id: str = Field(min_length=1, max_length=160)
    workflow: Literal["ask", "learn", "quiz", "review", "readiness", "planning"]
    gear: Literal["Quick", "Guided", "Deep"] = "Quick"
    action: str = Field(min_length=1, max_length=80)
    target_concepts: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=40)
    snapshot: RevisionSnapshot
    learner_confirmation: Literal["not_required", "pending", "accepted", "declined"] = "not_required"


class Assistance(Record):
    independence: Literal["observed_independent", "assisted", "unknown"]
    exposure_lineage_id: str = Field(min_length=1, max_length=160)
    question_family_id: str = Field(min_length=1, max_length=160)
    hint_level: int = Field(default=0, ge=0, le=10)
    answer_revealed: bool = False
    worked_solution_seen: bool = False
    external_help_disclosed: bool | None = None

    @model_validator(mode="after")
    def independent_has_no_recorded_assistance(self):
        if self.independence == "observed_independent" and (self.hint_level or self.answer_revealed or self.worked_solution_seen or self.external_help_disclosed):
            raise ValueError("Recorded assistance contradicts independence")
        return self


class SourceSpan(Record):
    revision_id: str = Field(min_length=1, max_length=160)
    origin_id: str = Field(min_length=1, max_length=160)
    extraction_method: str = Field(min_length=1, max_length=80)
    page_index: int | None = Field(default=None, ge=0)
    text_start: int = Field(ge=0)
    text_end: int = Field(gt=0)
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.text_end <= self.text_start:
            raise ValueError("Invalid text span")
        if (self.audio_start_ms is None) != (self.audio_end_ms is None):
            raise ValueError("Audio span requires both bounds")
        if self.audio_start_ms is not None and self.audio_end_ms <= self.audio_start_ms:
            raise ValueError("Invalid audio span")
        return self


class OwnedRecord(Contract):
    owner_id: Identifier
    id: Identifier
    revision: Revision


class RevisionRef(Contract):
    kind: ReasonCode
    id: Identifier
    revision: Revision


class SnapshotInput(Contract):
    state: Literal["available", "unavailable", "not_applicable"]
    reference: RevisionRef | None = None
    reason: ReasonCode | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.state == "available") != (self.reference is not None):
            raise ValueError("Only available inputs have revision references")
        if self.state != "available" and self.reason is None:
            raise ValueError("Missing snapshot inputs require an explicit reason")
        return self


class DecisionSnapshot(OwnedRecord):
    created_at: AwareDatetime
    purpose: ReasonCode
    learner_projection: SnapshotInput
    academic_snapshot: SnapshotInput
    concept_graph: SnapshotInput
    policy: RevisionRef
    context_manifest: SnapshotInput
    sources: tuple[RevisionRef, ...] = ()
    additional_dependencies: tuple[RevisionRef, ...] = ()
    reason_codes: tuple[ReasonCode, ...] = ()

    def dependencies(self) -> tuple[RevisionRef, ...]:
        refs = [self.policy, *self.sources, *self.additional_dependencies]
        refs.extend(slot.reference for slot in (
            self.learner_projection, self.academic_snapshot, self.concept_graph,
            self.context_manifest,
        ) if slot.reference is not None)
        return tuple(refs)

    @model_validator(mode="after")
    def unique_dependencies(self):
        for slot, kind in ((self.learner_projection, "learner_projection"),
                           (self.academic_snapshot, "academic_snapshot"),
                           (self.concept_graph, "concept_graph"),
                           (self.context_manifest, "context_manifest")):
            if slot.reference is not None and slot.reference.kind != kind:
                raise ValueError(f"Snapshot input must reference {kind}")
        if self.policy.kind != "policy" or any(ref.kind != "source_revision" for ref in self.sources):
            raise ValueError("Snapshot policy/source references use canonical kinds")
        seen: dict[tuple[str, str], int] = {}
        for ref in self.dependencies():
            key = (ref.kind, ref.id)
            if key in seen and seen[key] != ref.revision:
                raise ValueError("A decision cannot pin two revisions of one dependency")
            seen[key] = ref.revision
        return self


class Capability(StrEnum):
    recall = "recall"
    explain = "explain"
    apply = "apply"
    transfer = "transfer"


class EvidenceQuality(Contract):
    """Trustworthiness of item, grade and source; never mastery probability."""
    status: Literal["usable", "tentative", "disputed", "invalid", "unknown"]
    reason_codes: tuple[ReasonCode, ...]


class EvidenceStrength(Contract):
    """Diversity/independence of observations, not an average model score."""
    status: Literal["insufficient_evidence", "tentative", "supported", "conflicting"]
    independent_observations: int = Field(ge=0)
    distinct_families: int = Field(ge=0)
    delayed_observations: int = Field(ge=0)

    @model_validator(mode="after")
    def counts(self):
        if self.delayed_observations > self.independent_observations:
            raise ValueError("Delayed observations count independent delayed checks only")
        return self


class HypothesisSupport(Contract):
    status: Literal["tentative", "supported", "contradicted", "inconclusive"]
    supporting_event_ids: tuple[Identifier, ...] = ()
    contradicting_event_ids: tuple[Identifier, ...] = ()


class AcademicFactConfidence(Contract):
    basis: Literal["explicit_source", "user_confirmed", "inferred", "unknown"]
    status: Literal["tentative", "supported", "conflicting", "insufficient_evidence"]


class AssistanceLineage(Contract):
    condition: Literal["independent", "assisted", "unknown"]
    scope: Literal["question", "family", "capability"]
    supporting_event_ids: tuple[Identifier, ...] = ()
    prior_solution_exposure: Literal["yes", "no", "unknown"]

    @model_validator(mode="after")
    def independent(self):
        if self.condition == "independent" and self.prior_solution_exposure != "no":
            raise ValueError("Independence requires known absence of solution exposure")
        return self


class AccountRecord(OwnedRecord):
    auth_subject: str | None = Field(default=None, min_length=1, max_length=300)
    timezone: str = Field(min_length=1, max_length=100)
    consent_revision: Revision
    deleted_at: AwareDatetime | None = None


class DeviceRecord(OwnedRecord):
    grants: tuple[ReasonCode, ...]
    revoked_at: AwareDatetime | None = None


class SourceRevision(OwnedRecord):
    source_id: Identifier
    kind: ReasonCode
    origin: str = Field(min_length=1, max_length=2000)
    content_hash: Digest
    locator: str = Field(min_length=1, max_length=2000)
    access_state: Literal["available", "revoked", "deleted", "unavailable"]


class SourceSpan(OwnedRecord):
    source_revision: RevisionRef
    page: int | None = Field(default=None, ge=1)
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, ge=0)
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, ge=0)
    extraction_method: ReasonCode

    @model_validator(mode="after")
    def ranges(self):
        for start, end in ((self.text_start, self.text_end), (self.audio_start_ms, self.audio_end_ms)):
            if (start is None) != (end is None) or (start is not None and end <= start):
                raise ValueError("Spans require paired increasing half-open bounds")
        if self.page is None and self.text_start is None and self.audio_start_ms is None:
            raise ValueError("A span needs at least one location")
        return self


class ConceptRecord(OwnedRecord):
    definition: str = Field(min_length=1, max_length=4000)
    aliases: tuple[str, ...] = ()
    discipline: str = Field(min_length=1, max_length=200)
    review_state: Literal["proposed", "reviewed", "retired"]


class ConceptMapping(OwnedRecord):
    concept_id: Identifier
    course_id: Identifier
    outcome_id: Identifier
    review_state: Literal["proposed", "reviewed", "rejected"]


class ConceptRelationship(OwnedRecord):
    from_concept_id: Identifier
    to_concept_id: Identifier
    relationship: Literal["prerequisite", "related", "part_of"]
    source: RevisionRef
    confidence: Literal["proposed", "reviewed"]
    effective_graph_revision: Revision

    @model_validator(mode="after")
    def not_self(self):
        if self.from_concept_id == self.to_concept_id:
            raise ValueError("Concept relationships cannot point to themselves")
        return self


class LearningObservation(StrEnum):
    exposure = "exposure"
    answer = "answer"
    skip = "skip"
    dont_know = "dont_know"
    assistance = "assistance"
    challenge = "challenge"
    correction = "correction"
    completion = "completion"


class LearningEvent(OwnedRecord):
    observation: LearningObservation
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    deduplication_key: str = Field(min_length=1, max_length=300)
    attempt_id: Identifier | None = None
    source: RevisionRef | None = None
    supersedes_event_id: Identifier | None = None
    related_event_ids: tuple[Identifier, ...] = ()


class EventConceptLink(OwnedRecord):
    event_id: Identifier
    concept_id: Identifier
    capability: Capability
    role: Literal["target", "prerequisite", "incidental"]
    attribution_basis: Literal["rubric", "reviewed_mapping", "model_proposed", "unknown"]
    uncertainty: Literal["resolved", "ambiguous", "unknown"]


class EvidenceEvaluation(OwnedRecord):
    event_id: Identifier
    rubric: RevisionRef
    outcome: Literal["correct", "partial", "incorrect", "ungraded"]
    assistance: AssistanceLineage
    validity: Literal["active", "suspended", "invalid", "superseded"]
    grading_method: ReasonCode
    quality: EvidenceQuality
    supersedes_evaluation_id: Identifier | None = None


class LearnerProjection(OwnedRecord):
    concept_id: Identifier
    capability: Capability
    state: Literal["unobserved", "exposed", "developing", "demonstrated", "review_due"]
    evidence_strength: EvidenceStrength
    conflict_event_ids: tuple[Identifier, ...] = ()
    effective_event_ids: tuple[Identifier, ...]
    reducer: RevisionRef
    event_watermark: int = Field(ge=0)


class Hypothesis(OwnedRecord):
    concept_id: Identifier
    explanation: str = Field(min_length=1, max_length=4000)
    support: HypothesisSupport
    status: Literal["open", "resolved", "expired", "rejected"]
    previous_revision: RevisionRef | None = None


class AcademicFact(OwnedRecord):
    subject_id: Identifier
    predicate: ReasonCode
    value: str | int | float | bool | None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    observed_at: AwareDatetime
    source: RevisionRef
    confidence: AcademicFactConfidence
    supersedes_fact_id: Identifier | None = None

    @model_validator(mode="after")
    def valid_period(self):
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Fact validity interval must increase")
        return self


class QuestionRecord(OwnedRecord):
    """Private authoring contract; never serialize directly to a public route."""
    family_id: Identifier
    presented_content: str = Field(min_length=1)
    private_key_reference: Identifier
    rubric: RevisionRef
    sources: tuple[RevisionRef, ...]
    objective: ReasonCode
    validation_ids: tuple[Identifier, ...]


class InterventionRecord(OwnedRecord):
    action: ReasonCode
    concept_ids: tuple[Identifier, ...]
    decision_snapshot_id: Identifier
    content_reference: RevisionRef | None = None
    exposed_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None


class TaskCompletionRule(Contract):
    kind: Literal["activity_submitted", "artifact_created", "user_confirmed"]
    activity_kind: ReasonCode
    minimum_count: int = Field(default=1, ge=1)


class StudyTask(OwnedRecord):
    goal_id: Identifier
    plan: RevisionRef
    activity_kind: ReasonCode
    status: Literal["planned", "active", "paused", "completed", "cancelled"]
    prerequisite_task_ids: tuple[Identifier, ...] = ()
    completion_rule: TaskCompletionRule
    linked_activity_ids: tuple[Identifier, ...] = ()


class StudyPlan(OwnedRecord):
    goal_id: Identifier
    availability_revision: RevisionRef
    timezone: str = Field(min_length=1, max_length=100)
    task_ids: tuple[Identifier, ...]
    decision_snapshot_id: Identifier


class JobDecisionTrace(OwnedRecord):
    job_id: Identifier
    decision_snapshot_id: Identifier
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    reason_codes: tuple[ReasonCode, ...]
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)


# No arbitrary object deserialization. A new family or schema revision requires
# a deliberate parser/consumer migration; legacy payloads remain in legacy APIs.
PAYLOAD_TYPES: dict[str, type[Contract]] = {
    "account": AccountRecord, "device": DeviceRecord,
    "source_revision": SourceRevision, "source_span": SourceSpan,
    "concept": ConceptRecord, "concept_mapping": ConceptMapping,
    "concept_relationship": ConceptRelationship, "learning_event": LearningEvent,
    "event_concept_link": EventConceptLink, "evidence_evaluation": EvidenceEvaluation,
    "learner_projection": LearnerProjection, "hypothesis": Hypothesis,
    "academic_fact": AcademicFact, "question": QuestionRecord,
    "intervention": InterventionRecord, "study_plan": StudyPlan,
    "study_task": StudyTask, "job_decision_trace": JobDecisionTrace,
    "decision_snapshot": DecisionSnapshot,
}


def parse_payload(family: str, schema_revision: int, payload: str) -> Contract:
    if type(schema_revision) is not int or schema_revision != 1:
        raise ValueError("Unsupported contract schema revision")
    model = PAYLOAD_TYPES.get(family)
    if model is None:
        raise ValueError("Unsupported contract family")
    return TypeAdapter(model).validate_json(payload)
