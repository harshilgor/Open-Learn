from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from dateutil.rrule import rrulestr


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Temporal(Contract):
    mode: Literal['timed', 'all_day', 'deadline'] = 'timed'
    timezone: str = 'UTC'
    start: str | None = None
    end: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    dueAt: str | None = None
    dueDate: str | None = None

    @model_validator(mode='after')
    def validate_time(self):
        try: ZoneInfo(self.timezone)
        except (ValueError, KeyError): raise ValueError('Choose an IANA timezone.') from None
        def instant(value):
            if not value: raise ValueError('Provide a date and time with UTC offset.')
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None: raise ValueError('An explicit UTC offset is required.')
            return parsed
        if self.mode == 'timed':
            if any((self.startDate, self.endDate, self.dueAt, self.dueDate)): raise ValueError('Timed events use start and end only.')
            if instant(self.end) <= instant(self.start): raise ValueError('End must be after start.')
        elif self.mode == 'all_day':
            if any((self.start, self.end, self.dueAt, self.dueDate)): raise ValueError('All-day events use dates only.')
            if not self.startDate or not self.endDate or date.fromisoformat(self.endDate) <= date.fromisoformat(self.startDate): raise ValueError('Use an exclusive end date after the start.')
        else:
            if any((self.start, self.end, self.startDate, self.endDate)) or bool(self.dueAt) == bool(self.dueDate): raise ValueError('Provide exactly one due date or due instant.')
            if self.dueAt: instant(self.dueAt)
            else: date.fromisoformat(self.dueDate)
        return self


class EventInput(Contract):
    calendarId: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    type: Literal['class', 'assignment', 'exam', 'study', 'reminder', 'personal'] = 'study'
    temporal: Temporal
    description: str = Field(default='', max_length=10000)
    location: str = Field(default='', max_length=500)
    url: str = Field(default='', max_length=2000)
    courseId: str | None = Field(default=None, max_length=160)
    busy: bool = True
    recurrence: str | None = Field(default=None, max_length=500)
    reminderMinutes: list[int] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def valid_event(self):
        if not self.title.strip(): raise ValueError('A title is required.')
        if self.url and not self.url.startswith(('https://', 'http://')): raise ValueError('Use an HTTP or HTTPS link.')
        if any(value < 0 or value > 10080 for value in self.reminderMinutes): raise ValueError('Reminder offsets must be between 0 and 10080 minutes.')
        if self.recurrence:
            if not self.recurrence.startswith('FREQ=') or any(x in self.recurrence for x in ('\n', '\r', 'DTSTART', 'SECONDLY', 'MINUTELY', 'HOURLY')): raise ValueError('Use a daily, weekly, monthly or yearly RRULE.')
            t = self.temporal
            start = datetime.fromisoformat((t.start or t.dueAt or (t.startDate or t.dueDate) + 'T00:00:00').replace('Z', '+00:00')).astimezone(ZoneInfo(t.timezone)) if t.start or t.dueAt else datetime.fromisoformat((t.startDate or t.dueDate) + 'T00:00:00').replace(tzinfo=ZoneInfo(t.timezone))
            rrulestr(self.recurrence, dtstart=start)
        return self


class EventEdit(Contract):
    expectedRevision: int = Field(ge=1)
    event: EventInput
    scope: Literal['occurrence', 'future', 'series'] = 'series'
    occurrenceKey: str | None = Field(default=None, max_length=100)


class EventAction(Contract):
    expectedRevision: int = Field(ge=1)
    scope: Literal['occurrence', 'future', 'series'] = 'series'
    occurrenceKey: str | None = Field(default=None, max_length=100)


class Permission(Contract):
    expectedRevision: int = Field(ge=1)
    read: Literal['none', 'busy_only', 'details']
    edit: Literal['ask', 'allow'] = 'ask'


class Preferences(Contract):
    timezone: str = 'UTC'
    defaultView: Literal['day', 'week', 'month', 'agenda'] = 'week'
    weekStart: Literal[0, 1] = 1
    startHour: int = Field(default=8, ge=0, le=23)
    endHour: int = Field(default=20, ge=1, le=24)
    duration: int = Field(default=30, ge=5, le=480)

    @model_validator(mode='after')
    def valid_preferences(self):
        try: ZoneInfo(self.timezone)
        except (ValueError, KeyError): raise ValueError('Choose an IANA timezone.') from None
        if self.endHour <= self.startHour: raise ValueError('Working hours must end after they start.')
        return self


class Availability(Contract):
    start: str
    end: str
    timezone: str
    calendarIds: list[str] = Field(min_length=1, max_length=30)
    duration: int = Field(default=30, ge=5, le=480)
    startHour: int = Field(default=8, ge=0, le=23)
    endHour: int = Field(default=20, ge=1, le=24)


class Change(Contract):
    kind: Literal['create', 'update', 'cancel']
    eventId: str | None = None
    event: EventInput | None = None
    expectedRevision: int | None = None
    scope: Literal['occurrence', 'future', 'series'] = 'series'
    occurrenceKey: str | None = None

    @model_validator(mode='after')
    def valid_change(self):
        if self.kind != 'cancel' and not self.event: raise ValueError('Provide the event.')
        if self.kind != 'create' and (not self.eventId or not self.expectedRevision): raise ValueError('Provide the target and revision.')
        if self.kind == 'create' and self.eventId: raise ValueError('Creates cannot select an existing event.')
        return self


class Proposal(Contract):
    changes: list[Change] = Field(min_length=1, max_length=10)
    reason: str = Field(default='', max_length=500)
    sessionId: str | None = Field(default=None, max_length=160)


class Decision(Contract):
    expectedRevision: int = Field(ge=1)
    proposalHash: str
    decision: Literal['allow', 'cancel']
    rememberCalendarIds: list[str] = Field(default_factory=list, max_length=10)
