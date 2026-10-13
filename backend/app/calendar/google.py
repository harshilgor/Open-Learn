"""Google calendar discovery and leased incremental mirror synchronization."""
import json
import time
from urllib.parse import quote
from sqlalchemy import text
from ..agent_execution.google_connector import GoogleConnections, GoogleAdapter
from ..agent_execution.connected_contracts import ConnectorError
from ..identity import fail
from .service import CalendarService, digest


class GoogleCalendar:
    def __init__(self, store, adapter=None):
        self.store = store; self.svc = CalendarService(store)
        self.connections = GoogleConnections(store)
        self.adapter = adapter or GoogleAdapter(self.connections)

    def discover(self, owner, connection):
        items, page = [], None
        for _ in range(20):
            params = {'maxResults': 250}
            if page: params['pageToken'] = page
            result = self.adapter.request(owner, connection, 'calendar_list', 'GET', 'calendar/v3/users/me/calendarList', params=params).json()
            items.extend({'providerCalendarId': c['id'], 'title': c.get('summary', 'Google Calendar'), 'timezone': c.get('timeZone', 'UTC'), 'role': c.get('accessRole', 'reader'), 'color': c.get('backgroundColor', '#9bb5a0')} for c in result.get('items', []) if not c.get('deleted'))
            page = result.get('nextPageToken')
            if not page: return {'items': items}
        fail('provider_limit', 'Too many calendars. Narrow the connected account.', 422)

    def select(self, owner, connection, provider_id):
        found = next((c for c in self.discover(owner, connection)['items'] if c['providerCalendarId'] == provider_id), None)
        if not found: fail('not_found', 'Google calendar unavailable.', 404)
        identifier = 'google_calendar_' + digest([owner, connection, provider_id])[:32]
        with self.svc.transaction(owner) as conn:
            exists = conn.execute(text('SELECT revision FROM calendar_calendars WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).scalar_one_or_none()
            calendar = self.svc.write(conn, owner, 'calendars', {'id': identifier, 'source': 'google', 'connectionId': connection, **found}, exists, connection)
        return calendar

    def mirror(self, conn, owner, calendar, remote):
        identifier = 'google_event_' + digest([calendar['id'], remote['id']])[:32]
        existing = conn.execute(text('SELECT id FROM calendar_events WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
        old = self.svc.read(conn, owner, 'events', identifier) if existing else None
        if remote.get('recurringEventId') and remote.get('originalStartTime'):
            from datetime import datetime
            from zoneinfo import ZoneInfo
            parent = 'google_event_' + digest([calendar['id'], remote['recurringEventId']])[:32]
            original = remote['originalStartTime']
            zone = calendar.get('timezone', 'UTC')
            master_row = conn.execute(text('SELECT id FROM calendar_events WHERE id=:id AND owner_id=:owner'), {'id': parent, 'owner': owner}).first()
            if master_row: zone = self.svc.read(conn, owner, 'events', parent)['temporal']['timezone']
            key = datetime.fromisoformat(original['dateTime'].replace('Z', '+00:00')).astimezone(ZoneInfo(zone)).isoformat() if original.get('dateTime') else datetime.fromisoformat(original['date'] + 'T00:00:00').replace(tzinfo=ZoneInfo(zone)).isoformat()
            override_id = 'override_' + digest([parent, key])[:32]
            previous = conn.execute(text('SELECT revision FROM calendar_overrides WHERE id=:id AND owner_id=:owner'), {'id': override_id, 'owner': owner}).scalar_one_or_none()
            value = {'id': override_id, 'eventId': parent, 'occurrenceKey': key, 'cancelled': remote.get('status') == 'cancelled'}
            if not value['cancelled']:
                begin, finish = remote['start'], remote['end']
                temporal = {'mode': 'all_day', 'timezone': zone, 'startDate': begin['date'], 'endDate': finish['date']} if begin.get('date') else {'mode': 'timed', 'timezone': zone, 'start': begin['dateTime'], 'end': finish['dateTime']}
                value['event'] = {'title': remote.get('summary', 'Busy'), 'description': remote.get('description', ''), 'temporal': temporal, 'providerEventId': remote['id'], 'etag': remote.get('etag'), 'recurrence': None, 'busy': remote.get('transparency') != 'transparent'}
            self.svc.write(conn, owner, 'overrides', value, previous, parent)
            return
        if remote.get('status') == 'cancelled':
            if old: self.svc.write(conn, owner, 'events', {**old, 'status': 'cancelled', 'etag': remote.get('etag')}, old['revision'])
            return
        start, end = remote.get('start', {}), remote.get('end', {})
        zone = start.get('timeZone') or calendar.get('timezone', 'UTC')
        temporal = {'mode': 'all_day', 'timezone': zone, 'startDate': start['date'], 'endDate': end['date']} if start.get('date') else {'mode': 'timed', 'timezone': zone, 'start': start.get('dateTime'), 'end': end.get('dateTime')}
        if not temporal.get('startDate') and not temporal.get('start'): return
        recurrence = next((r[6:] for r in remote.get('recurrence', []) if r.startswith('RRULE:')), None)
        data = {'id': identifier, 'calendarId': calendar['id'], 'sourceType': 'google', 'providerEventId': remote['id'], 'etag': remote.get('etag'), 'title': remote.get('summary', 'Busy'), 'description': remote.get('description', ''), 'location': remote.get('location', ''), 'url': remote.get('htmlLink', ''), 'type': 'personal', 'busy': remote.get('transparency') != 'transparent', 'temporal': temporal, 'recurrence': recurrence, 'attendees': remote.get('attendees', []), 'status': 'active', 'recurringEventId': remote.get('recurringEventId'), 'originalStartTime': remote.get('originalStartTime'), 'lastSyncedAt': time.time(), 'recurrenceRules': remote.get('recurrence', [])}
        if old and old.get('etag') == data['etag']: return
        self.svc.write(conn, owner, 'events', data, old['revision'] if old else None, calendar['id'])


def tick_google_calendars(store, limit=5):
    import os
    if os.getenv('OPENLEARN_CALENDAR_GOOGLE_SYNC', 'false').lower() != 'true': return 0
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT c.owner_id,c.id,c.payload FROM calendar_calendars c LEFT JOIN calendar_sync s ON s.parent_id=c.id AND s.owner_id=c.owner_id WHERE c.status='active' AND c.parent_id IS NOT NULL AND (s.updated_at IS NULL OR s.updated_at<:recent OR s.status='pending') ORDER BY c.updated_at LIMIT :limit"), {'recent': time.time() - 300, 'limit': limit}).mappings().all()
    count = 0
    for row in rows:
        if json.loads(row['payload']).get('source') != 'google': continue
        try: GoogleCalendar(store).sync(row['owner_id'], row['id']); count += 1
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Calendar sync failed for calendar %s', row['id'])
    return count

    def sync(self, owner, calendar_id):
        identifier = 'sync_' + digest([owner, calendar_id])[:32]
        with self.svc.transaction(owner) as conn:
            calendar = self.svc.read(conn, owner, 'calendars', calendar_id)
            if calendar.get('source') != 'google': fail('invalid_source', 'Choose a Google calendar.', 422)
            connection = self.connections.row(conn, owner, calendar['connectionId'])
            if connection['status'] != 'connected': fail('connection_revoked', 'Reconnect this Google account.', 409)
            exists = conn.execute(text('SELECT id FROM calendar_sync WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            state = self.svc.read(conn, owner, 'sync', identifier) if exists else {'id': identifier}
            if state.get('leaseUntil', 0) > time.time(): return {'status': 'syncing'}
            lease = self.svc.write(conn, owner, 'sync', {**state, 'status': 'syncing', 'leaseUntil': time.time() + 90}, state.get('revision'), calendar_id)
        params = {'maxResults': 250, 'showDeleted': 'true', 'singleEvents': 'false'}
        if lease.get('syncToken'): params['syncToken'] = lease['syncToken']
        if lease.get('pageToken'): params['pageToken'] = lease['pageToken']
        try:
            # Handle invalid sync cursors explicitly; adapter normally maps errors.
            token = self.connections.token(owner, calendar['connectionId'], 'calendar_read')
            response = self.connections._request('GET', 'https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar['providerCalendarId'], safe='') + '/events', headers={'Authorization': 'Bearer ' + token}, params=params)
            if response.status_code == 410:
                with self.svc.transaction(owner) as conn:
                    current = self.svc.read(conn, owner, 'sync', identifier)
                    if current['revision'] != lease['revision']: fail('sync_changed', 'Sync lease changed.', 409)
                    self.svc.write(conn, owner, 'sync', {'id': identifier, 'status': 'pending', 'leaseUntil': 0}, current['revision'], calendar_id)
                    # Invalidate old mirrors before a full rebuild; do not show false freshness.
                    for item in self.svc.list_rows(conn, owner, 'events', calendar_id): self.svc.write(conn, owner, 'events', {**item, 'status': 'cancelled'}, item['revision'])
                return {'status': 'pending', 'reasonCode': 'full_sync_required'}
            if response.status_code != 200: raise ConnectorError('google_sync_unavailable')
            result = response.json()
            with self.svc.transaction(owner) as conn:
                current = self.svc.read(conn, owner, 'sync', identifier)
                fresh = self.connections.row(conn, owner, calendar['connectionId'])
                if fresh['status'] != 'connected' or current['revision'] != lease['revision']: fail('sync_revoked', 'Sync permission changed.', 409)
                for remote in result.get('items', []): self.mirror(conn, owner, calendar, remote)
                page = result.get('nextPageToken')
                saved = self.svc.write(conn, owner, 'sync', {**current, 'status': 'pending' if page else 'current', 'leaseUntil': 0, 'pageToken': page, 'syncToken': result.get('nextSyncToken', lease.get('syncToken')), 'lastSuccess': time.time() if not page else lease.get('lastSuccess'), 'nextAttempt': time.time() if page else time.time() + 300}, current['revision'], calendar_id)
            return {'status': saved['status'], 'lastSuccess': saved.get('lastSuccess')}
        except Exception:
            with self.svc.transaction(owner) as conn:
                current = self.svc.read(conn, owner, 'sync', identifier)
                if current['revision'] == lease['revision']: self.svc.write(conn, owner, 'sync', {**current, 'status': 'failed', 'leaseUntil': 0, 'nextAttempt': time.time() + 60, 'reasonCode': 'sync_unavailable'}, current['revision'], calendar_id)
            raise
