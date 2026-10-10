"""Durable Google effects: dispatch once, reconcile uncertain outcomes."""
import json
import time
from urllib.parse import quote
from fastapi import HTTPException
from sqlalchemy import text
from ..agent_execution.google_connector import GoogleConnections, GoogleAdapter
from ..agent_execution.connected_contracts import ConnectorError
from ..identity import fail
from .contracts import EventInput
from .google import GoogleCalendar
from .service import CalendarService, digest


class GoogleWrites:
    def __init__(self, store, adapter=None):
        self.store = store; self.svc = CalendarService(store)
        self.connections = GoogleConnections(store)
        self.adapter = adapter or GoogleAdapter(self.connections)

    def queue(self, conn, owner, identifier, changes, actor, grant_revisions=None):
        items = []
        for index, change in enumerate(changes):
            if change['kind'] != 'cancel': EventInput.model_validate(change['event'])
            before = None if change['kind'] == 'create' else self.svc.read(conn, owner, 'events', change['eventId'])
            target = change['event'] if change['kind'] == 'create' else before
            calendar = self.svc.read(conn, owner, 'calendars', target['calendarId'])
            if calendar['source'] != 'google': fail('mixed_batch', 'Apply local and Google changes in separate plans.', 422)
            if calendar.get('role') not in {'writer', 'owner'}: fail('read_only_calendar', 'This Google calendar is read only.', 403)
            connection = self.connections.row(conn, owner, calendar['connectionId'])
            if connection['status'] != 'connected' or 'calendar_write' not in json.loads(connection['payload'])['capabilities']: fail('calendar_write_required', 'Reconnect Google with edit access.', 403)
            if before and before['revision'] != change['expectedRevision']: fail('revision_conflict', 'The Google event changed.', 409)
            if before and before.get('recurrence') and change.get('scope', 'series') != 'series': fail('provider_scope_unavailable', 'Google occurrence and future-series edits are not enabled yet.', 422)
            if before and actor == 'buddy' and before.get('attendees') and not change.get('humanConfirmed'): fail('approval_required', 'Changes affecting attendees need confirmation.', 403)
            items.append({'change': change, 'calendar': calendar, 'connectionRevision': connection['revision'], 'before': before, 'providerId': before.get('providerEventId') if before else digest([identifier, index]), 'status': 'queued', 'marker': digest([identifier, index, change])})
        return self.svc.write(conn, owner, 'operations', {'id': identifier, 'status': 'queued', 'requestHash': digest(changes), 'actor': actor, 'items': items, 'results': [], 'grantRevisions': grant_revisions, 'nextAttempt': time.time()})

    def body(self, item):
        event = item['change']['event']; t = event['temporal']
        if t['mode'] == 'deadline': fail('provider_timing_unavailable', 'Save date-only deadlines to Open Learn.', 422)
        start = {'date': t['startDate']} if t['mode'] == 'all_day' else {'dateTime': t['start'], 'timeZone': t['timezone']}
        end = {'date': t['endDate']} if t['mode'] == 'all_day' else {'dateTime': t['end'], 'timeZone': t['timezone']}
        result = {'summary': event['title'], 'description': event.get('description', ''), 'location': event.get('location', ''), 'start': start, 'end': end, 'transparency': 'opaque' if event.get('busy', True) else 'transparent', 'extendedProperties': {'private': {'openlearnCalendarOperation': item['marker']}}, 'recurrence': ['RRULE:' + event['recurrence']] if event.get('recurrence') else []}
        return result

    def validate(self, conn, owner, operation, item):
        connection = self.connections.row(conn, owner, item['calendar']['connectionId'])
        if connection['status'] != 'connected' or connection['revision'] != item['connectionRevision']: fail('connection_changed', 'Google connection changed.', 409)
        if operation.get('grantRevisions'):
            cal = item['calendar']['id']; permission = self.svc.permission(conn, owner, cal)
            if permission['edit'] != 'allow' or permission['read'] == 'none' or permission['revision'] != operation['grantRevisions'][cal]: fail('permission_changed', 'Buddy calendar permission was revoked or changed.', 403)
        if item['before']:
            current = self.svc.read(conn, owner, 'events', item['before']['id'])
            if current['revision'] != item['before']['revision']: fail('revision_conflict', 'Refresh the changed Google event.', 409)

    def execute(self, owner, identifier):
        with self.svc.transaction(owner) as conn:
            operation = self.svc.read(conn, owner, 'operations', identifier)
            if operation['status'] not in {'queued', 'dispatching', 'outcome_unknown'}: return operation
            if operation['status'] == 'dispatching' and operation['updatedAt'] > time.time() - 90: return operation
            item = next((i for i in operation['items'] if i['status'] != 'applied'), None)
            if not item: return operation
            try: self.validate(conn, owner, operation, item)
            except HTTPException:
                return self.svc.write(conn, owner, 'operations', {**operation, 'status': 'failed', 'reasonCode': 'authorization_or_event_changed'}, operation['revision'])
            fresh_dispatch = item['status'] == 'queued'
            if fresh_dispatch:
                item['status'] = 'dispatching'
                operation = self.svc.write(conn, owner, 'operations', {**operation, 'status': 'dispatching'}, operation['revision'])
                item = next(i for i in operation['items'] if i['marker'] == item['marker'])
        calendar = item['calendar']; path = 'calendar/v3/calendars/' + quote(calendar['providerCalendarId'], safe='') + '/events'
        target = path + '/' + quote(item['providerId'], safe='')
        try:
            if not fresh_dispatch:
                try: remote = self.adapter.request(owner, calendar['connectionId'], 'calendar_read', 'GET', target).json()
                except ConnectorError as exc:
                    if exc.code == 'provider_not_found' and item['change']['kind'] == 'cancel': remote = {'id': item['providerId'], 'status': 'cancelled'}
                    else: raise
                if item['change']['kind'] != 'cancel' and remote.get('extendedProperties', {}).get('private', {}).get('openlearnCalendarOperation') != item['marker']: raise ConnectorError('provider_outcome_unconfirmed', True)
            else:
                with self.svc.transaction(owner) as conn: self.validate(conn, owner, operation, item)
                params = {'sendUpdates': 'none'}
                kind = item['change']['kind']
                if kind == 'create': remote = self.adapter.request(owner, calendar['connectionId'], 'calendar_write', 'POST', path, json={'id': item['providerId'], **self.body(item)}, params=params).json()
                elif kind == 'update': remote = self.adapter.request(owner, calendar['connectionId'], 'calendar_write', 'PATCH', target, json=self.body(item), headers={'If-Match': item['before']['etag']}, params=params).json()
                else:
                    self.adapter.request(owner, calendar['connectionId'], 'calendar_write', 'DELETE', target, headers={'If-Match': item['before']['etag']}, params=params)
                    remote = {'id': item['providerId'], 'status': 'cancelled'}
            with self.svc.transaction(owner) as conn:
                current = self.svc.read(conn, owner, 'operations', identifier)
                if current['revision'] != operation['revision']: return current
                connection = self.connections.row(conn, owner, calendar['connectionId'])
                if connection['status'] == 'connected' and connection['revision'] == item['connectionRevision']:
                    GoogleCalendar(self.store, self.adapter).mirror(conn, owner, calendar, remote)
                item['status'] = 'applied'; item['receipt'] = {'providerId': remote['id'], 'etag': remote.get('etag')}
                status = 'applied' if all(i['status'] == 'applied' for i in operation['items']) else 'queued'
                saved = self.svc.write(conn, owner, 'operations', {**current, 'status': status, 'items': operation['items'], 'providerReceipt': item['receipt'], 'nextAttempt': time.time()}, current['revision'])
                if current.get('proposalId') and status == 'applied':
                    proposal = self.svc.read(conn, owner, 'proposals', current['proposalId'])
                    self.svc.write(conn, owner, 'proposals', {**proposal, 'status':'applied'}, proposal['revision'])
                return saved
        except (ConnectorError, HTTPException) as exc:
            unknown = isinstance(exc, ConnectorError) and exc.uncertain or not fresh_dispatch
            with self.svc.transaction(owner) as conn:
                current = self.svc.read(conn, owner, 'operations', identifier)
                if current['revision'] != operation['revision']: return current
                item['status'] = 'outcome_unknown' if unknown else 'failed'
                return self.svc.write(conn, owner, 'operations', {**current, 'status': item['status'], 'items': operation['items'], 'reasonCode': getattr(exc, 'code', 'calendar_operation_failed'), 'automaticResend': False}, current['revision'])


def tick_google_writes(store, limit=5):
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT id,owner_id FROM calendar_operations WHERE status='queued' OR (status='dispatching' AND updated_at<:stale) ORDER BY updated_at LIMIT :limit"), {'stale': time.time() - 90, 'limit': limit}).mappings().all()
    for row in rows:
        try: GoogleWrites(store).execute(row['owner_id'], row['id'])
        except Exception:
            # Dispatch markers survive exceptions; next tick reconciles instead of resending.
            import logging
            logging.getLogger(__name__).exception('Calendar operation failed: %s', row['id'])
    return len(rows)
