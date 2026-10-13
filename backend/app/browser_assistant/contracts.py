from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True, alias_generator=to_camel)


class ConnectionCreate(Contract):
    label: str = Field(min_length=1, max_length=120)
    origin: str = Field(max_length=2048)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    category: Literal['university_lms', 'study', 'public_web'] = 'study'
    platform: Literal['canvas', 'generic'] = 'generic'
    executor: Literal['local', 'cloud', 'public_fetch'] = 'local'
    timezone: str = 'America/Los_Angeles'
    term: str = 'current'
    preferred: bool = False
    cloud_login: bool = False
    approved_origins: list[str] = Field(default_factory=list, max_length=12)


class ConnectionPatch(Contract):
    expected_revision: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=12)
    preferred: bool | None = None
    cloud_login: bool | None = None
    approved_origins: list[str] | None = Field(default=None, max_length=12)
    timezone: str | None = None


class ReminderPolicyInput(Contract):
    course_id: str | None = None
    entity_id: str | None = None
    entity_ids: list[str] | None = Field(default=None, max_length=300)
    connection_id: str | None = None
    entity_kinds: list[Literal['assessment','assignment','meeting','coverage']] | None = None
    offsets_minutes: list[int] = Field(default_factory=lambda: [1440], min_length=1, max_length=8)
    channels: list[Literal['inbox', 'desktop', 'push']] = Field(default_factory=lambda: ['inbox'], min_length=1, max_length=3)
    timezone: str = 'America/Los_Angeles'
    date_only_time: str | None = None
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    catchup_minutes: int = Field(default=120, ge=0, le=1440)
    active: bool = True
    expected_revision: int | None = None


class TaskCreate(Contract):
    message: str = Field(min_length=1, max_length=4000)
    connection_id: str | None = None
    session_id: str | None = None
    previous_task_id: str | None = None
    course_id: str | None = None
    max_actions: int = Field(default=80, ge=1, le=200)
    max_pages: int = Field(default=40, ge=1, le=100)
    reminder_policy: ReminderPolicyInput | None = None


class TaskCommand(Contract):
    action: Literal['cancel', 'pause', 'resume', 'resolve', 'takeover', 'return_control']
    expected_revision: int = Field(ge=1)
    connection_id: str | None = None
    course_id: str | None = None
    answer: str | None = Field(default=None, max_length=4000)
    reply_to_request_id: str | None = Field(default=None, max_length=160)
    expected_request_revision: int | None = Field(default=None, ge=1)


class TaskIntent(Contract):
    schema_revision: Literal[1] = 1
    handled: bool = True
    goal: str = Field(max_length=4000)
    operations: list[Literal['browse', 'discover_courses', 'collect_exam_dates', 'collect_assignments',
                             'save_academic_facts', 'summarize', 'query_saved', 'create_study_tasks']] = Field(max_length=8)
    source_url: str | None = Field(default=None, max_length=2048)
    source_alias: str | None = Field(default=None, max_length=120)
    save: bool = False
    reminder_requested: bool = False
    external_write_requests: list[str] = Field(default_factory=list, max_length=5)
    clarification: str | None = Field(default=None, max_length=500)


class BrowserAction(Contract):
    tool: Literal['navigate', 'observe', 'find', 'click', 'fill', 'press_key', 'scroll',
                  'capture_screenshot', 'read_document', 'read_platform_resource']
    url: str | None = Field(default=None, max_length=2048)
    element_ref: str | None = Field(default=None, max_length=180)
    snapshot_id: str | None = Field(default=None, max_length=180)
    query: str | None = Field(default=None, max_length=500)
    value: str | None = Field(default=None, max_length=1000)
    direction: Literal['up', 'down'] = 'down'
    amount: int = Field(default=650, ge=100, le=2000)
    resource: Literal['courses', 'assignments', 'calendar', 'syllabus', 'announcements', 'modules'] | None = None
    external_course_id: str | None = Field(default=None, pattern=r'^\d+$', max_length=40)
    cursor: str | None = Field(default=None, max_length=2048)


class TextBlock(Contract):
    ref: str = Field(max_length=180)
    text: str = Field(max_length=20000)


class Control(Contract):
    ref: str = Field(max_length=180)
    role: str = Field(max_length=40)
    name: str = Field(max_length=300)
    href: str | None = Field(default=None, max_length=2048)
    writable: bool = False
    x: float | None = None
    y: float | None = None


class Observation(Contract):
    url: str = Field(max_length=2048)
    title: str = Field(default='', max_length=300)
    document_revision: str = Field(max_length=180)
    tab_id: str = Field(default='', max_length=80)
    blocks: list[TextBlock] = Field(default_factory=list, max_length=100)
    controls: list[Control] = Field(default_factory=list, max_length=250)
    truncated: bool = False
    complete: bool = False
    status: Literal['completed', 'partial', 'login_required', 'account_changed', 'unsupported', 'tab_closed'] = 'completed'
    platform_items: list[dict] = Field(default_factory=list, max_length=200)
    account_id: str | None = Field(default=None, max_length=160)
    next_cursor: str | None = Field(default=None, max_length=2048)
    screenshot: str | None = Field(default=None, max_length=3000000)
    image_mime: Literal['image/png','image/jpeg','image/webp'] = 'image/png'
    document_text: str | None = Field(default=None, max_length=150000)


class DocumentResult(Contract):
    url: str = Field(max_length=2048)
    content_type: str = Field(max_length=120)
    document_bytes: str = Field(max_length=11000000)


class BrowserResult(Contract):
    generation: str = Field(max_length=160)
    connection_revision: int
    observation: Observation | None = None
    document: DocumentResult | None = None
    error: Literal['login_required', 'device_offline', 'tab_closed', 'stale_reference', 'origin_not_approved',
                   'capability_unavailable', 'unsupported_file', 'action_blocked', 'outcome_unknown', 'account_changed'] | None = None


class DateValue(Contract):
    kind: Literal['instant', 'date_only', 'timezone_unknown', 'unknown']
    value: str | None = Field(default=None, max_length=160)


class EvidenceCandidate(Contract):
    kind: Literal['assessment', 'assignment', 'meeting', 'coverage']
    title: str = Field(min_length=1, max_length=300)
    snapshot_id: str = Field(max_length=160)
    block_ref: str = Field(max_length=160)
    quote: str = Field(min_length=1, max_length=3000)
    course_external_id: str | None = Field(default=None, max_length=160)
    course_id: str | None = Field(default=None, max_length=160)
    external_id: str | None = Field(default=None, max_length=160)
    date: DateValue | None = None
    end: DateValue | None = None
    recurrence: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    confirmation: Literal['confirmed', 'tentative', 'inferred'] = 'tentative'
    image_region: list[float] | None = Field(default=None, min_length=4, max_length=4)


class ActionDecision(Contract):
    kind: Literal['action']
    action: BrowserAction


class EvidenceDecision(Contract):
    kind: Literal['evidence']
    facts: list[EvidenceCandidate] = Field(max_length=30)


class FinishDecision(Contract):
    kind: Literal['finish']
    summary: str = Field(max_length=4000)


class ClarifyDecision(Contract):
    kind: Literal['clarify']
    question: str = Field(min_length=1, max_length=500)


Decision = Annotated[ActionDecision | EvidenceDecision | FinishDecision | ClarifyDecision, Field(discriminator='kind')]
decision_adapter = TypeAdapter(Decision)


class RefreshInput(Contract):
    interval_hours: int = Field(ge=1, le=168)
    message: str = Field(default='Check my courses and save updated deadlines and exam dates', max_length=4000)
    active: bool = True


class PushInput(Contract):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str]


class CloudLoginInput(Contract):
    expected_revision: int = Field(ge=1)
