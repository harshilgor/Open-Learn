from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.calendar.service import CalendarService
from backend.app.calendar.contracts import EventInput, EventEdit, EventAction, Permission, Proposal, Decision


@pytest.fixture
def env():
    path = Path('work') / ('calendar-' + uuid4().hex + '.sqlite')
    store = Store(path)
    svc = CalendarService(store)
    calendar = svc.calendars('alice')['items'][0]['id']
    yield svc, calendar
    store.close(); path.unlink(missing_ok=True)


def event(calendar, **values):
    return EventInput(calendarId=calendar, title='Physics revision', temporal={'mode': 'timed', 'timezone': 'America/Los_Angeles', 'start': '2026-11-01T10:00:00-08:00', 'end': '2026-11-01T10:30:00-08:00'}, **values)


def test_owned_idempotent_mutations_and_undo(env):
    svc, cal = env
    operation = svc.create('alice', event(cal), 'first')
    assert svc.create('alice', event(cal), 'first')['id'] == operation['id']
    target = operation['results'][0]['after']
    with pytest.raises(HTTPException) as denied: svc.event('bob', target['id'])
    assert denied.value.status_code == 404
    changed = event(cal).model_copy(update={'title': 'Different'})
    with pytest.raises(HTTPException) as conflict: svc.create('alice', changed, 'first')
    assert conflict.value.status_code == 409
    svc.undo('alice', operation['id'], 'undo')
    assert svc.event('alice', target['id'])['status'] == 'cancelled'


def test_recurrence_exception_and_conflict(env):
    svc, cal = env
    saved = svc.create('alice', event(cal, recurrence='FREQ=DAILY;COUNT=3'), 'series')['results'][0]['after']
    feed = svc.occurrences('alice', '2026-11-01T00:00:00Z', '2026-11-05T00:00:00Z')
    assert len(feed['items']) == 3
    first = feed['items'][0]
    svc.cancel('alice', saved['id'], EventAction(expectedRevision=1, scope='occurrence', occurrenceKey=first['occurrenceKey']), 'skip')
    assert len(svc.occurrences('alice', '2026-11-01T00:00:00Z', '2026-11-05T00:00:00Z')['items']) == 2
    with pytest.raises(HTTPException) as conflict: svc.cancel('alice', saved['id'], EventAction(expectedRevision=1), 'stale')
    assert conflict.value.status_code == 409


def test_first_approval_remember_and_revoke(env):
    svc, cal = env
    svc.set_permission('alice', cal, Permission(expectedRevision=1, read='details'))
    proposal = svc.propose('alice', Proposal(changes=[{'kind': 'create', 'event': event(cal).model_dump()}]), 'proposal')
    decision = Decision(expectedRevision=1, proposalHash=proposal['proposalHash'], decision='allow', rememberCalendarIds=[cal])
    applied = svc.decide('alice', proposal['id'], decision, 'allow')
    assert svc.decide('alice', proposal['id'], decision, 'allow')['id'] == applied['id']
    permission = svc.calendars('alice')['items'][0]['permission']
    assert permission['edit'] == 'allow'
    second = svc.propose('alice', Proposal(changes=[{'kind': 'create', 'event': event(cal).model_dump()}]), 'second')
    svc.set_permission('alice', cal, Permission(expectedRevision=permission['revision'], read='none'))
    with pytest.raises(HTTPException): svc.decide('alice', second['id'], Decision(expectedRevision=1, proposalHash=second['proposalHash'], decision='allow'), 'apply', unattended=True)


def test_busy_only_does_not_expose_private_content(env):
    svc, cal = env
    svc.create('alice', event(cal, description='Private medical visit'), 'private')
    svc.set_permission('alice', cal, Permission(expectedRevision=1, read='busy_only'))
    feed = svc.occurrences('alice', '2026-11-01T00:00:00Z', '2026-11-05T00:00:00Z', agent=True)
    assert feed['items'][0]['title'] == 'Busy'
    assert 'description' not in feed['items'][0]
    assert 'Physics' not in str(feed)
