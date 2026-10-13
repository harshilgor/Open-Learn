"""Draft-only AI note contracts.

Draft bodies are learner-visible artifacts. They are never evidence and are not
written to the Markdown vault until an explicit save or replacement command.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from .session_models import ApiModel, NoteContextInput

DraftOriginKind = Literal["lesson", "selection", "quiz_feedback", "mentioned_notes"]

class NoteDraftSourceAnchor(ApiModel):
    kind: Literal["lesson_block", "quiz_attempt", "note_excerpt", "material_passage"]
    id: str = Field(min_length=1, max_length=360)
    label: str = Field(min_length=1, max_length=240)

class NoteDraftReplacement(ApiModel):
    note_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset.")
        return self

class CreateNoteDraft(ApiModel):
    """An explicit request to compose an editable note, never to save one."""
    origin_kind: DraftOriginKind
    lesson_id: str | None = Field(default=None, max_length=160)
    block_id: str | None = Field(default=None, max_length=160)
    selected_text: str | None = Field(default=None, max_length=6000)
    quiz_attempt_id: str | None = Field(default=None, max_length=160)
    note_context: NoteContextInput | None = None
    replacement: NoteDraftReplacement | None = None
    edit_request: str | None = Field(default=None,max_length=1000)

    @model_validator(mode="after")
    def authorized_origin(self):
        if self.origin_kind == "lesson" and not self.lesson_id:
            raise ValueError("lesson_id is required for a lesson draft.")
        if self.origin_kind == "selection" and (not self.lesson_id or not self.block_id or not self.selected_text):
            raise ValueError("lesson_id, block_id, and selected_text are required for a selected passage draft.")
        if self.origin_kind == "quiz_feedback" and not self.quiz_attempt_id:
            raise ValueError("quiz_attempt_id is required for a quiz feedback draft.")
        if self.origin_kind == "mentioned_notes" and not self.note_context:
            raise ValueError("note_context is required when drafting from mentioned notes.")
        if self.replacement and self.origin_kind not in {"lesson", "selection", "quiz_feedback", "mentioned_notes"}:
            raise ValueError("This draft origin cannot replace a note section.")
        return self

class NoteDraft(ApiModel):
    id: str
    session_id: str
    status: Literal["ready", "saved", "replaced", "discarded"] = "ready"
    generated_label: Literal["ai_generated_draft"] = "ai_generated_draft"
    title: str
    body: str
    proposed_tags: list[str] = Field(default_factory=list)
    proposed_links: list[NoteDraftSourceAnchor] = Field(default_factory=list)
    source_anchors: list[NoteDraftSourceAnchor] = Field(default_factory=list)
    origin_kind: DraftOriginKind
    origin_reference: str
    replacement: NoteDraftReplacement | None = None
    provider: str
    created_at: datetime

class NoteDraftReplaceCommand(ApiModel):
    expected_note_revision: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset.")
        return self
