"""Public commands and private authoring contracts; solutions never reach the UI."""
from typing import Literal
from pydantic import Field, model_validator
from .session_models import ApiModel, NoteContextInput, TeachingGear


class QuizCreate(ApiModel):
    session_id: str
    requested_topic: str | None = Field(default=None, max_length=500)
    lesson_note_id: str | None = Field(default=None, max_length=120)
    source_transition_id: str | None = Field(default=None, max_length=120)
    concept_ids: list[str] = Field(default_factory=list, max_length=10)
    count: int = Field(default=5, ge=1, le=10)
    difficulty: Literal["adaptive", "foundational", "standard", "stretch"] = "adaptive"
    origin: Literal["quiz", "learn_inline", "ask", "learn"] = "ask"
    mode: Literal["topic_drill", "timed_short_quiz"] = "topic_drill"
    mode_config: dict[str, int] = Field(default_factory=dict)
    selected_span_ids: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_mode(self):
        allowed = {"duration_seconds"} if self.mode == "timed_short_quiz" else set()
        unknown = set(self.mode_config) - allowed
        if unknown:
            raise ValueError("Unsupported mode configuration")
        if self.mode == "timed_short_quiz":
            seconds = self.mode_config.get("duration_seconds")
            if seconds is None or not 60 <= seconds <= 7200:
                raise ValueError("Timed quizzes need a duration between 60 seconds and 2 hours")
        elif self.mode_config:
            raise ValueError("Topic drills do not accept mode configuration")
        return self


class AnswerCommand(ApiModel):
    presentation_id: str
    expected_revision: int = Field(ge=1)
    response: str = Field(default="", max_length=6000)
    selected_ids: list[str] = Field(default_factory=list, max_length=8)
    outcome: Literal["answer", "dont_know", "skip"] = "answer"


class RevisionCommand(ApiModel):
    expected_revision: int = Field(ge=1)


class ChallengeCommand(ApiModel):
    reason: str = Field(min_length=5, max_length=2000)


class Option(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=1000)


class Criterion(ApiModel):
    id: str
    description: str = Field(min_length=5, max_length=1000)
    weight: float = Field(gt=0, le=1)


class Candidate(ApiModel):
    concept_id: str
    kind: Literal["single", "multiple", "short"]
    stem: str = Field(min_length=15, max_length=4000)
    reasoning_target: str = Field(min_length=10, max_length=1000)
    family: str = Field(min_length=3, max_length=160)
    options: list[Option] = Field(default_factory=list, max_length=6)
    correct_ids: list[str] = Field(default_factory=list)
    solution: str = Field(min_length=15, max_length=4000)
    criteria: list[Criterion] = Field(min_length=1, max_length=5)
    hints: list[str] = Field(min_length=1, max_length=3)
    source_ids: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def coherent(self):
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids) or len(set(self.correct_ids)) != len(self.correct_ids):
            raise ValueError("Option IDs must be unique")
        if abs(sum(c.weight for c in self.criteria) - 1) > .001:
            raise ValueError("Rubric weights must sum to one")
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Rubric IDs must be unique")
        if self.kind == "short":
            if ids or self.correct_ids:
                raise ValueError("Written questions have no choices")
        elif len(ids) < 2 or not self.correct_ids or not set(self.correct_ids).issubset(ids):
            raise ValueError("Selection questions require a valid answer key")
        elif self.kind == "single" and len(self.correct_ids) != 1:
            raise ValueError("Single choice needs exactly one correct option")
        return self


class JourneyCommand(ApiModel):
    expected_revision: int = Field(default=1, ge=1)
    classification_bypass_id: str | None = Field(default=None, max_length=100)
    action: Literal["message", "start", "next", "repair", "pause", "resume", "adjust", "mode"] = "message"
    mode: Literal["ask", "learn"] = "learn"
    gear: TeachingGear = TeachingGear.quick
    message: str = Field(default="", max_length=4000)
    note_context: NoteContextInput | None = None


class RouteStep(ApiModel):
    concept_id: str
    title: str = Field(min_length=1, max_length=150)
    objective: str = Field(min_length=5, max_length=600)


class RouteProposal(ApiModel):
    steps: list[RouteStep] = Field(min_length=1, max_length=5)
