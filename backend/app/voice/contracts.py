from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Focus(Contract):
    revision: int = Field(default=0, ge=0)
    note_id: str | None = Field(default=None, max_length=160)
    quiz_id: str | None = Field(default=None, max_length=160)
    presentation_id: str | None = Field(default=None, max_length=160)
    lesson_id: str | None = Field(default=None, max_length=160)
    visualization_id: str | None = Field(default=None, max_length=160)
    expected_revision: int | None = Field(default=None, ge=1)


class SessionCreate(Contract):
    chat_id: str = Field(min_length=1, max_length=160)
    timezone: str = Field(default='America/Los_Angeles', max_length=100)
    language: Literal['en'] = 'en'
    consent: bool
    focus: Focus = Field(default_factory=Focus)

    @field_validator('timezone')
    @classmethod
    def timezone_exists(cls, value):
        ZoneInfo(value)
        return value


class TurnCreate(Contract):
    utterance_id: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=4000)


class Confirmation(Contract):
    arguments_hash: str = Field(min_length=64, max_length=64)
    approve: bool


class Playback(Contract):
    segment_id: str = Field(max_length=160)
    epoch: int = Field(ge=0)
    status: Literal['played', 'interrupted']
