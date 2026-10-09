from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..flashcards.contracts import FlashcardRequest


class Contract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')


class Attachment(Contract):
    version_id: str = Field(alias='versionId', min_length=1, max_length=160)
    name: str = Field(default='', max_length=200)


class InputRequest(Contract):
    """Durable, revisioned human input request shared by agent capabilities."""
    request_id: str = Field(alias='requestId', min_length=1, max_length=160)
    task_id: str = Field(alias='taskId', min_length=1, max_length=160)
    revision: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=1200)
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=12)
    input_kind: Literal['text','choice','file','voice_transcript','confirmation'] = Field(default='text', alias='inputKind')
    state: Literal['open','answered','superseded','expired','cancelled'] = 'open'

    @model_validator(mode='after')
    def validate_options(self):
        if self.input_kind == 'choice' and not self.options:
            raise ValueError('Choice input requires options.')
        if self.input_kind in {'file','voice_transcript','confirmation'} and self.options:
            raise ValueError('This input kind does not accept suggestion options.')
        return self


class InputAnswer(Contract):
    text: str | None = Field(default=None, max_length=16000)
    selected_option: str | None = Field(default=None, alias='selectedOption', max_length=500)
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def require_content(self):
        if not (self.text and self.text.strip()) and not self.selected_option and not self.attachments:
            raise ValueError('Provide text, a selected option, or an attachment.')
        return self


class TaskDependency(Contract):
    """Versioned prerequisite reference; owning service remains authoritative."""
    id: str = Field(min_length=1, max_length=160)
    kind: Literal['task','input','approval','tool','resource','source','artifact']
    status: Literal['pending','satisfied','failed','cancelled'] = 'pending'
    required: bool = True
    source_id: str | None = Field(default=None, alias='sourceId', max_length=160)
    source_revision: int | None = Field(default=None, alias='sourceRevision', ge=1)
    result_ref: str | None = Field(default=None, alias='resultRef', max_length=160)
    reason_code: str | None = Field(default=None, alias='reasonCode', max_length=100)


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

    @model_validator(mode='after')
    def validate_reply_target(self):
        if self.reply_to_request_id and self.expected_request_revision is None:
            raise ValueError('A request reply requires its current request revision.')
        if self.expected_request_revision is not None and not self.reply_to_request_id:
            raise ValueError('A request revision requires a request ID.')
        if (self.target_task_id or self.reply_to_request_id) and self.expected_revision is None:
            raise ValueError('A task reply requires its current task revision.')
        return self


class Command(Contract):
    schema_version: Literal[2] = Field(default=2, alias='schemaVersion')
    command_id: str = Field(alias='commandId', min_length=1, max_length=160)
    action: Literal['answer_input', 'steer', 'pause', 'resume', 'cancel']
    expected_revision: int = Field(alias='expectedRevision', ge=1)
    request_id: str | None = Field(default=None, alias='requestId', max_length=160)
    expected_request_revision: int | None = Field(default=None, alias='expectedRequestRevision', ge=1)
    message_id: str | None = Field(default=None, alias='messageId', max_length=160)
    text: str | None = Field(default=None, max_length=16000)
    answer: InputAnswer | None = None

    @model_validator(mode='after')
    def validate_input_reply(self):
        if self.action == 'answer_input' and (not self.request_id or self.expected_request_revision is None or self.answer is None):
            raise ValueError('Answering input requires the exact request revision and typed answer.')
        if self.action != 'answer_input' and (self.request_id is not None or self.expected_request_revision is not None):
            raise ValueError('Only input answers may reference an input request.')
        return self
