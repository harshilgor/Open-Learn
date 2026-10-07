from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..flashcards.contracts import FlashcardRequest


class Contract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')


class Attachment(Contract):
    version_id: str = Field(alias='versionId', min_length=1, max_length=160)
    name: str = Field(default='', max_length=200)


class Message(Contract):
    schema_version: Literal[2] = Field(default=2, alias='schemaVersion')
    client_message_id: str = Field(alias='clientMessageId', min_length=1, max_length=160)
    session_id: str = Field(alias='sessionId', min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=16000)
    previous_browser_task_id: str | None = Field(default=None, alias='previousBrowserTaskId', max_length=160)
    course_id: str | None = Field(default=None, alias='courseId', max_length=160)
    presentation: Literal['conversation','ask','learn','quiz'] = 'conversation'
    timezone: str = Field(default='America/Los_Angeles', max_length=100)
    accepted_usage_cap_micro: int | None = Field(default=None, alias='acceptedUsageCapMicro', ge=1)
    capability: Literal['lab_analysis', 'research', 'sandbox_lab', 'flashcards'] | None = None
    flashcard_spec: FlashcardRequest | None = Field(default=None, alias='flashcardSpec')
    research_spec: dict | None = Field(default=None, alias='researchSpec')
    # Bounded CSV text is a development intake, not an arbitrary local path.
    csv_text: str | None = Field(default=None, alias='csvText', max_length=50000)
    material_version_id: str | None = Field(default=None, alias='materialVersionId',max_length=160)
    reply_to_request_id: str | None = Field(default=None, alias='replyToRequestId', max_length=160)
    target_task_id: str | None = Field(default=None, alias='targetTaskId', max_length=160)
    expected_revision: int | None = Field(default=None, alias='expectedRevision', ge=1)
    expected_request_revision: int | None = Field(default=None, alias='expectedRequestRevision', ge=1)
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)


class Command(Contract):
    schema_version: Literal[2] = Field(default=2, alias='schemaVersion')
    command_id: str = Field(alias='commandId', min_length=1, max_length=160)
    action: Literal['answer_input', 'steer', 'pause', 'resume', 'cancel']
    expected_revision: int = Field(alias='expectedRevision', ge=1)
    request_id: str | None = Field(default=None, alias='requestId', max_length=160)
    expected_request_revision: int | None = Field(default=None, alias='expectedRequestRevision', ge=1)
    message_id: str | None = Field(default=None, alias='messageId', max_length=160)
    text: str | None = Field(default=None, max_length=16000)
    answer: dict | None = None
