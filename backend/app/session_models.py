"""Contracts for the learning-kernel session and teaching-action slice.

These models intentionally live beside the original graph contracts.  The
graph API can evolve independently while a session pins a graph revision and
lesson actions produce typed, resumable artifacts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import utc_now
from .policy_models import ActionContext, PolicyValidationResult, TeachingPlan


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


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
    deepen = "deepen"


class SessionCreate(ApiModel):
    """Start a session on an existing graph, or create one from a topic.

    ``graph_id`` is the stable path used by the web client.  ``topic`` is a
    convenience for a direct prompt flow and is resolved by the API boundary.
    """

    graph_id: str | None = None
    graph_revision: int | None = Field(default=None, ge=1)
    goal: str | None = Field(default=None, max_length=1000)
    scope_id: str | None = None
    topic: str | None = Field(default=None, max_length=200)
    # Local single-user default for the prototype. Hosted authentication will
    # replace this request field with the authenticated learner identity.
    learner_id: str = Field(default="local", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    gear: TeachingGear = TeachingGear.guided

    @field_validator("graph_id", "scope_id", "topic", "goal", "learner_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class LearningSession(ApiModel):
    id: str
    learner_id: str = Field(default="local", min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    graph_id: str
    graph_revision: int = 1
    goal: str | None = None
    current_concept_id: str | None = None
    current_lesson_id: str | None = None
    gear: TeachingGear = TeachingGear.guided
    state_version: int = 1
    created_at: datetime
    updated_at: datetime


class BranchAnchor(ApiModel):
    block_id: str | None = None
    selected_text: str | None = Field(default=None, max_length=2000)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)


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
    anchor: BranchAnchor | None = None
    expected_state_version: int | None = Field(default=None, ge=1)
    curriculum_version: int | None = Field(default=None, ge=1)
    supersedes_action_id: str | None = Field(default=None, max_length=160)

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


class SessionGearUpdate(ApiModel):
    """An explicit preference change; it never rewrites an in-flight lesson."""

    gear: TeachingGear
    expected_state_version: int | None = Field(default=None, ge=1)


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
