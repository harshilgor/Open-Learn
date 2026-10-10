"""Calendar notification projection into the existing durable reminder scheduler."""
import json
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from ..reminder_service import ReminderService, ReminderCreate
from ..identity import assert_owner_active
from .service import CalendarService, digest


def prepare_calendar_reminders(store, now=None):
    now = time.time() if now is None else now
    with store.engine.connect() as conn:
        owners = conn.execute(text("SELECT DISTINCT owner_id FROM calendar_events WHERE status='active' LIMIT 500")).scalars().all()
    count = 0
    for owner in owners:
        svc = CalendarService(store)
        feed = svc.occurrences(owner, datetime.fromtimestamp(now - 120 * 60, timezone.utc).isoformat(), datetime.fromtimestamp(now + 8 * 86400, timezone.utc).isoformat())
        if feed['nextCursor']: continue  # Do not silently prepare only a partial range.
        with svc.transaction(owner) as conn:
            for event in feed['items']:
                if event.get('sourceType') != 'local': continue
                current = svc.read(conn, owner, 'events', event['eventId'])
                if current['revision'] != event['revision'] or current['status'] != 'active': continue
                for offset in event.get('reminderMinutes', []):
                    due = event['sortAt'] - offset * 60
                    if due < now - 120 * 60: continue
                    identifier = 'calendar_fire_' + digest([owner, event['eventId'], event['revision'], event['occurrenceKey'], offset])[:32]
                    payload = ReminderCreate(when=datetime.fromtimestamp(due, timezone.utc).isoformat(), message=event['title'], timezone=event['temporal']['timezone'], courseId=event.get('courseId')).model_dump()
                    payload.update(title=event['title'], body=event['title'], calendarEventId=event['eventId'], calendarEventRevision=event['revision'], url='/calendar?date=' + datetime.fromtimestamp(event['sortAt'], timezone.utc).date().isoformat())
                    ReminderService(store).insert_fire(conn, owner, identifier, 'chat', due, payload)
                    conn.execute(text('UPDATE reminders SET entity_id=:event,entity_revision=:revision WHERE id=:id AND owner_id=:owner'), {'event': event['eventId'], 'revision': event['revision'], 'id': identifier, 'owner': owner})
                    count += 1
    return count


def calendar_fire_current(conn, row):
    payload = json.loads(row['payload'])
    if not payload.get('calendarEventId'): return True
    event = conn.execute(text('SELECT revision,status FROM calendar_events WHERE id=:id AND owner_id=:owner'), {'id': payload['calendarEventId'], 'owner': row['owner_id']}).mappings().first()
    return bool(event and event['status'] == 'active' and event['revision'] == payload['calendarEventRevision'])
