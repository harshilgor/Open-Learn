"""Domain models and contracts for the Courses system."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import utc_now
from .session_models import ApiModel


class CourseTeachingPreferences(ApiModel):
    depth: Literal["introductory", "standard", "deep"] = "standard"
    pace: Literal["brisk", "steady", "thorough"] = "steady"
    math_level: Literal["minimal", "standard", "rigorous"] = "standard"
    visual_emphasis: bool = True
    code_examples: bool = True
    first_principles: bool = True


class CourseReminderPreferences(ApiModel):
    enabled: bool = False
    days: list[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    time: str = "19:00"
    target_minutes: int = 10


class CourseCreate(ApiModel):
    name: str = Field(min_length=1, max_length=300)
    goal: str = Field(default="", max_length=2000)
    teaching_preferences: CourseTeachingPreferences | None = None
    reminder_preferences: CourseReminderPreferences | None = None

    @field_validator("name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Field must contain at least one non-whitespace character.")
        return value

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return " ".join(value.split())


class CourseUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=300)
    goal: str | None = Field(default=None, max_length=2000)
    teaching_preferences: CourseTeachingPreferences | None = None
    reminder_preferences: CourseReminderPreferences | None = None
    archived: bool | None = None

    @field_validator("name", "goal")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


RoadmapNodeStatus = Literal["planned", "in_progress", "completed", "needs_review"]


class RoadmapNodeCreate(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    phase: str = Field(min_length=1, max_length=120, default="Core Curriculum")
    concept_id: str | None = None

    @field_validator("title", "phase")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Field must contain at least one non-whitespace character.")
        return value


class RoadmapNodeUpdate(ApiModel):
    title: str | None = Field(default=None, max_length=300)
    phase: str | None = Field(default=None, max_length=120)
    concept_id: str | None = None
    status: RoadmapNodeStatus | None = None
    order_index: int | None = None

    @field_validator("title", "phase")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class RoadmapGenerateRequest(ApiModel):
    prompt: str | None = Field(default=None, max_length=1000)
    replace_existing: bool = True


class RoadmapReorderRequest(ApiModel):
    node_ids: list[str] = Field(min_length=1)


class CourseRoadmapNode(ApiModel):
    id: str
    course_id: str
    phase: str
    concept_id: str | None = None
    title: str
    status: RoadmapNodeStatus = "planned"
    order_index: int = 0
    created_at: datetime


class RoadmapProgressionResult(ApiModel):
    course_id: str
    nodes_updated: int
    completed_count: int
    total_count: int
    due_review_count: int
    roadmap: list[CourseRoadmapNode]


class CourseSummary(ApiModel):
    id: str
    name: str
    goal: str
    session_count: int = 0
    note_count: int = 0
    material_count: int = 0
    due_review_count: int = 0
    roadmap_progress: int = 0
    updated_at: datetime
    archived_at: datetime | None = None


class CoursePublic(ApiModel):
    id: str
    name: str
    goal: str
    teaching_preferences: CourseTeachingPreferences = Field(default_factory=CourseTeachingPreferences)
    reminder_preferences: CourseReminderPreferences = Field(default_factory=CourseReminderPreferences)
    roadmap: list[CourseRoadmapNode] = Field(default_factory=list)
    summary: CourseSummary
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
