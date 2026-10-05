"""Contracts for the learning-kernel session and teaching-action slice.

These models intentionally live beside the original graph contracts.  The
graph API can evolve independently while a session pins a graph revision and
lesson actions produce typed, resumable artifacts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import utc_now
from .policy_models import ActionContext, PolicyValidationResult, TeachingPlan


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def short_title(text: str | None, limit: int = 60) -> str:
    """Derive a readable conversation title without a model call.

    The first user message (already stored as the session goal) is the
    cheapest honest title source. Longer prompts are cut at a word boundary.
    """
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return "Untitled conversation"
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit].rsplit(" ", 1)[0] or collapsed[:limit]
    return cut.rstrip() + "…"


class ApiModel(BaseModel):
    """JSON uses the camelCase shape already defined by the web client."""

    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class TeachingGear(StrEnum):
    quick = "Quick"
    guided = "Guided"
    deep = "Deep"


class TeachingIntent(StrEnum):
    teach = "teach"
    simplify = "simplify"
    example = "example"
    why = "why"
    visualize = "visualize"
    check_understanding = "check_understanding"
    resume = "resume"


class SessionCreate(ApiModel):
    """Start a session on an existing graph, or create one from a topic.

    ``graph_id`` is the stable path used by the web client.  ``topic`` is a
    convenience for a direct prompt flow and is resolved by the API boundary.
    """

    graph_id: str | None = None
    buddy_id: str | None = Field(default=None, max_length=160)
    graph_revision: int | None = Field(default=None, ge=1)
    goal: str | None = Field(default=None, max_length=1000)
    scope_id: str | None = None
    topic: str | None = Field(default=None, max_length=200)
    # Local single-user default for the prototype. Hosted authentication will
    # replace this request field with the authenticated learner identity.
    learner_id: str = Field(default="local", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    gear: TeachingGear = TeachingGear.quick
    domain_pack_id: str | None = Field(default=None, max_length=120)
    domain_pack_version: int | None = Field(default=None, ge=1)
    course_id: str | None = Field(default=None, max_length=160)

    @field_validator("graph_id", "scope_id", "topic", "goal", "learner_id", "course_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class LearningSession(ApiModel):
    id: str
    buddy_id: str | None = None
    learner_id: str = Field(default="local", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    graph_id: str
    graph_revision: int = 1
    # A session is historical: later pack updates must not alter its source
    # and graph contract.
    domain_pack_id: str | None = None
    domain_pack_version: int | None = None
    course_id: str | None = None
    goal: str | None = None
    title: str | None = Field(default=None, max_length=120)
    current_concept_id: str | None = None
    current_lesson_id: str | None = None
    gear: TeachingGear = TeachingGear.quick
    state_version: int = 1
    authority_revision: int = 1
    current_branch_id: str | None = None
    active_generation_id: str | None = None
    active_quiz_id: str | None = None
    active_review_id: str | None = None
    active_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionTurnSummary(ApiModel):
    index: int = Field(ge=0)
    lesson_id: str | None = None
    concept_id: str | None = None
    mode: Literal["ask", "learn"] | None = None


class SessionSnapshot(ApiModel):
    session: LearningSession
    revision: int = Field(ge=1)
    mode: Literal["ask", "learn"]
    journey_status: str
    journey_revision: int = Field(ge=1)
    journey_position: int = Field(ge=0)
    current_concept_id: str | None = None
    current_lesson_id: str | None = None
    current_branch_id: str | None = None
    active_generation_id: str | None = None
    active_generation_status: str | None = None
    active_quiz_id: str | None = None
    active_review_id: str | None = None
    active_job_id: str | None = None
    current_recommendation_set_id: str | None = None
    last_committed_turn: SessionTurnSummary | None = None


class SessionPositionUpdate(ApiModel):
    expected_revision: int = Field(ge=1)
    current_concept_id: str | None = Field(default=None, max_length=160)
    current_lesson_id: str | None = Field(default=None, max_length=160)
    current_branch_id: str | None = Field(default=None, max_length=160)
    active_generation_id: str | None = Field(default=None, max_length=160)
    active_quiz_id: str | None = Field(default=None, max_length=160)
    active_review_id: str | None = Field(default=None, max_length=160)
    active_job_id: str | None = Field(default=None, max_length=160)


class BranchAnchor(ApiModel):
    block_id: str | None = None
    selected_text: str | None = Field(default=None, max_length=2000)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


class NoteContextSelectionInput(ApiModel):
    """Stable note selection carried by Ask/Learn commands.

    The API only carries note IDs, revisions, and optional body offsets.  The
    server resolves the actual text owner-safely for the active request.
    """

    note_id: str = Field(min_length=1, max_length=160)
    expected_revision: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offsets_are_paired(self) -> "NoteContextSelectionInput":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together.")
        if self.start_offset is not None and self.end_offset is not None and self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset.")
        return self


class NoteContextInput(ApiModel):
    notes: list[NoteContextSelectionInput] = Field(min_length=1, max_length=8)

    @field_validator("notes")
    @classmethod
    def unique_notes(cls, value: list[NoteContextSelectionInput]) -> list[NoteContextSelectionInput]:
        if len({item.note_id for item in value}) != len(value):
            raise ValueError("A note may appear only once in a context manifest.")
        return value


class TeachingActionInput(ApiModel):
    """A typed command sent to the learning kernel.

    ``message`` is optional so the command buttons in the UI can use the same
    endpoint as a free-form ChatGPT-style prompt.
    """

    intent: TeachingIntent = TeachingIntent.teach
    concept_id: str | None = None
    gear: TeachingGear | None = None
    message: str | None = Field(default=None, max_length=4000)
    parent_lesson_id: str | None = None
    parent_block_id: str | None = None
    branch_id: str | None = None
    anchor: BranchAnchor | None = None
    expected_state_version: int | None = Field(default=None, ge=1)
    curriculum_version: int | None = Field(default=None, ge=1)
    note_context: NoteContextInput | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class ConceptTrust(ApiModel):
    status: Literal["supported", "partially_supported", "conflicting", "insufficient"] = "insufficient"
    confidence: float | None = None
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    reviewed_at: datetime | None = None


class LessonPart(ApiModel):
    kind: Literal["text", "visualization"]
    text: str | None = None
    visualization_id: str | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self):
        if self.kind == "text" and self.text is None:
            raise ValueError("text part requires text")
        if self.kind == "visualization" and self.visualization_id is None:
            raise ValueError("visualization part requires a reference")
        return self


class LessonBlock(ApiModel):
    id: str
    kind: Literal["explanation", "example", "analogy", "visual", "check", "reflection", "source_note"]
    heading: str | None = None
    body: str
    concept_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    trust: ConceptTrust = Field(default_factory=ConceptTrust)
    order: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    visualizations: list[dict[str, Any]] = Field(default_factory=list, max_length=4)
    parts: list[LessonPart] = Field(default_factory=list, max_length=30)


class LessonArtifact(ApiModel):
    id: str
    session_id: str
    concept_id: str
    graph_revision: int = 1
    gear: TeachingGear
    title: str
    blocks: list[LessonBlock] = Field(default_factory=list)
    next_action: Literal["continue", "check_understanding", "repair_prerequisite", "review"] | None = None
    status: Literal["pending", "approved", "qualified", "failed", "cancelled"] = "qualified"
    teaching_plan_id: str | None = None
    verification_run_id: str | None = None
    generated_by: str = "deterministic_baseline"
    created_at: datetime = Field(default_factory=utc_now)


class ActionStatus(StrEnum):
    received = "received"
    authorized = "authorized"
    context_ready = "context_ready"
    planned = "planned"
    generated = "generated"
    verified = "verified"
    delivered = "delivered"
    qualified_response = "qualified_response"
    failed = "failed"
    cancelled = "cancelled"


class RunStatus(ApiModel):
    run_id: str
    session_id: str
    status: ActionStatus
    progress: int = Field(ge=0, le=100)
    message: str | None = None
    intent: TeachingIntent | None = None
    action_context: ActionContext | None = None
    teaching_plan: TeachingPlan | None = None
    policy_validation: PolicyValidationResult | None = None
    lesson: LessonArtifact | None = None
    created_at: datetime
    updated_at: datetime


class ActionEvent(ApiModel):
    id: str
    action_id: str
    sequence: int = Field(ge=0)
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TeachingActionResponse(RunStatus):
    """Alias-shaped response for callers that name the record an action."""

    pass


class SessionRenameInput(ApiModel):
    """Rename a conversation. The title is user-supplied, never model-generated."""

    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Title must not be blank.")
        return value


class SessionSummary(ApiModel):
    """Lightweight chat-history entry: metadata only, never lesson content."""

    id: str
    title: str
    goal: str | None = None
    course_id: str | None = None
    updated_at: datetime
    turn_count: int = Field(default=0, ge=0)

    def to_summary_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        if self.course_id is None:
            data.pop("courseId", None)
        return data
