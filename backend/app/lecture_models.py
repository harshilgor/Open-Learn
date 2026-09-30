"""Validated lecture commands and provider-neutral structured analysis contracts."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, field_validator, model_validator

from .session_models import ApiModel

SectionType = Literal["review", "new_concept", "definition", "derivation", "proof", "worked_example", "discussion", "student_question", "administrative", "exam_guidance", "other"]
EntityType = Literal["concept", "definition", "formula", "equation", "derivation", "proof", "worked_example", "procedure", "intuition", "analogy", "warning", "common_mistake", "student_question", "professor_answer", "administrative", "exam_hint", "assignment", "lecture_reference", "correction", "uncertainty"]
Depth = Literal["concise", "standard", "detailed"]


class LecturePreferences(ApiModel):
    depth: Depth = "standard"
    definitions: bool = True
    examples: bool = True
    equations: bool = True
    derivations: bool = True
    student_questions: bool = True
    professor_emphasis: bool = True
    exam_hints: bool = True
    administrative: bool = False
    keep_audio: bool = True


class LectureCreate(ApiModel):
    id: str = Field(pattern=r"^rec_[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=240)
    course_id: str | None = Field(default=None, max_length=160)
    started_at_ms: int = Field(ge=0)
    note_folder: str | None = Field(default=None, max_length=120)
    preferences: LecturePreferences = Field(default_factory=LecturePreferences)


class LectureFinalize(ApiModel):
    expected_chunk_count: int = Field(ge=1, le=10000)
    duration_ms: int = Field(gt=0, le=24 * 60 * 60 * 1000)
    markers_ms: list[int] = Field(default_factory=list, max_length=500)
    capture_interrupted: bool = False

    @field_validator("markers_ms")
    @classmethod
    def ordered_markers(cls, values: list[int]) -> list[int]:
        if any(value < 0 for value in values) or values != sorted(values):
            raise ValueError("Markers must be nonnegative and chronological.")
        return values


class EvidenceProposal(ApiModel):
    segment_id: str = Field(min_length=1, max_length=80)


class SectionProposal(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    section_type: SectionType = "other"
    summary: str = Field(min_length=1, max_length=3000)
    segment_ids: list[str] = Field(min_length=1, max_length=150)
    confidence: float | None = Field(default=None, ge=0, le=1)


class SectionBatch(ApiModel):
    sections: list[SectionProposal] = Field(min_length=1, max_length=30)


class EntityProposal(ApiModel):
    kind: EntityType
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=4000)
    segment_ids: list[str] = Field(min_length=1, max_length=30)
    spoken_form: str | None = Field(default=None, max_length=1000)
    latex: str | None = Field(default=None, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_kind: Literal["professor", "student", "unknown", "ai_enrichment"] = "unknown"
    corrected_by_segment_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def cautious_math(self):
        if self.latex and (self.kind not in {"equation", "formula", "derivation", "proof"} or self.confidence is None or self.confidence < 0.8 or not self.spoken_form):
            self.latex = None
        return self


class EntityBatch(ApiModel):
    entities: list[EntityProposal] = Field(default_factory=list, max_length=60)


class VerificationItem(ApiModel):
    index: int = Field(ge=0)
    status: Literal["supported", "normalized", "uncertain", "unsupported"]
    reason: str = Field(min_length=1, max_length=500)


class VerificationBatch(ApiModel):
    results: list[VerificationItem]
