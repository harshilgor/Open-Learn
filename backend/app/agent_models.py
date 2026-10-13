"""Typed contracts for bounded, learner-owned agent tasks.

These models deliberately describe commands and audit records rather than a
free-form autonomous loop.  A task can only read documents owned by its
learner and can only write a learner note through the existing state service.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .session_models import ApiModel


class AgentTaskStatus(StrEnum):
    queued = "queued"
    planning = "planning"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AgentTaskKind(StrEnum):
    summarize_to_note = "summarize_to_note"


class AgentDocumentCreate(ApiModel):
    """Text extracted in the browser from an explicitly selected file.

    Binary PDF, DOCX, image, and audio extraction is intentionally outside
    this first trust boundary.  Those formats need a sandboxed extractor and
    provenance-preserving chunker, rather than pretending that a file picker
    has read them.
    """

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=300_000)
    mime_type: Literal["text/plain", "text/markdown", "text/csv"] = "text/plain"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Document title cannot be blank")
        return value


class AgentDocument(ApiModel):
    id: str
    learner_id: str
    title: str
    mime_type: str
    character_count: int = Field(ge=1)
    content_sha256: str
    created_at: datetime


class AgentTaskCreate(ApiModel):
    kind: AgentTaskKind = AgentTaskKind.summarize_to_note
    goal: str = Field(min_length=1, max_length=1000)
    document_ids: list[str] = Field(min_length=1, max_length=12)
    note_style: Literal["outline", "study"] = "study"
    note_scope: Literal["learner", "private"] = "private"

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Task goal cannot be blank")
        return value

    @model_validator(mode="after")
    def documents_are_unique(self) -> "AgentTaskCreate":
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("A document can only appear once in a task")
        return self


class AgentTaskStep(ApiModel):
    tool: Literal["read_owned_document", "extract_key_points", "create_learner_note"]
    status: Literal["pending", "completed", "skipped", "failed"]
    detail: str


class AgentTaskResult(ApiModel):
    note_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    summary: str | None = None
    limitations: list[str] = Field(default_factory=list)


class AgentTask(ApiModel):
    id: str
    learner_id: str
    kind: AgentTaskKind
    goal: str
    document_ids: list[str]
    note_style: Literal["outline", "study"]
    note_scope: Literal["learner", "private"]
    status: AgentTaskStatus
    steps: list[AgentTaskStep] = Field(default_factory=list)
    result: AgentTaskResult | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentTaskEvent(ApiModel):
    id: str
    task_id: str
    sequence: int = Field(ge=0)
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
