"""Versioned records shared across owning services, not writable API claims.

Quality, strength, hypothesis support and academic confidence deliberately use
different enums. None encodes an uncalibrated probability of knowledge.
"""
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
