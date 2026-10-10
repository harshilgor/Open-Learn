"""Provider-neutral contracts for durable streamed teaching generations."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import Field

from .assessment_models import JourneyCommand
from .session_models import ApiModel
from .visualization_models import VisualType

GenerationStatus = Literal["queued", "preparing", "streaming", "finalizing", "completed", "cancel_requested", "cancelled", "failed", "interrupted"]
GenerationEventType = Literal[
    "message.accepted",
    "generation.queued",
    "generation.started",
    "generation.context_ready",
    "text.delta",
    "generation.checkpoint",
    "lesson.block_started",
    "visualization.planning",
    "visualization.ready",
    "visualization.skipped",
    "visualization.error", "visualization.queued",
    "lesson.block_completed",
    "source.added",
    "tool.started",
    "tool.completed",
    "generation.completed",
    "generation.interrupted",
    "generation.cancel_requested",
    "generation.cancelled",
    "generation.error",
    "branch.updated",
]


class GenerationRequest(JourneyCommand):
    """A message-producing Journey command observed through the generation API."""
    client_message_id: str | None = Field(default=None, alias="clientMessageId", min_length=1, max_length=160)
    reply_to_generation_id: str | None = Field(default=None, alias="replyToGenerationId", max_length=160)
    parent_generation_id: str | None = Field(default=None, alias="parentGenerationId", max_length=160)
    action: Literal["message", "start", "next", "repair"] = "message"
    selected_span_ids: list[str] = Field(default_factory=list, max_length=6)
    selected_text: str | None = Field(default=None, max_length=2000)
    selected_lesson_id: str | None = Field(default=None, max_length=160)
    selected_block_id: str | None = Field(default=None, max_length=160)
    visual_type: VisualType | Literal["auto"] = "auto"


class GenerationDescriptor(ApiModel):
    id: str | None = None
    session_id: str
    mode: Literal["ask", "learn"]
    status: GenerationStatus
    sequence: int = 0
    provider: str
    model: str
    journey_revision: int | None = None
    final_revision: int | None = None
    error_code: str | None = None
    message_id: str | None = None
    conversation_seq: int | None = None
    context_revision: int | None = None
    parent_generation_id: str | None = None
    branch_id: str | None = None
    relation: str | None = None
    branch_revision: int | None = None
    selected_branch_id: str | None = None
    cancel_target_generation_id: str | None = None
    cancel_target_status: str | None = None
    accepted: bool = True
    scheduled_generation_ids: list[str] = Field(default_factory=list)
    active_generation_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | bool | str | None] = Field(default_factory=dict)


class BranchSelectionRequest(ApiModel):
    expected_branch_revision: int = Field(alias="expectedBranchRevision", ge=0)


class OutboxMetricsRequest(ApiModel):
    client_id: str = Field(alias="clientId", min_length=8, max_length=80)
    queued_count: int = Field(alias="queuedCount", ge=0, le=30)
    sending_count: int = Field(alias="sendingCount", ge=0, le=30)
    accepted_count: int = Field(alias="acceptedCount", ge=0, le=30)
    failed_count: int = Field(alias="failedCount", ge=0, le=30)
    choice_count: int = Field(default=0, alias="choiceCount", ge=0, le=30)
    oldest_pending_age_seconds: float = Field(alias="oldestPendingAgeSeconds", ge=0, le=604800)


class GenerationEvent(ApiModel):
    generation_id: str
    sequence: int
    type: GenerationEventType
    data: dict[str, Any] = Field(default_factory=dict)
