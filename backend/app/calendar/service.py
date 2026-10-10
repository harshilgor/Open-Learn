"""Owned, revision-fenced calendar operations and shared occurrence feed."""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded, uid
from .contracts import EventInput, EventEdit, EventAction, Preferences, Permission, Proposal
from .occurrences import bounds, expand, parse


def digest(value): return hashlib.sha256(encoded(value).encode()).hexdigest()


class CalendarService:
    def __init__(self, store): self.store = store

    @contextmanager
    def transaction(self, owner):
        with self.store.transaction() as conn:
            assert_owner_active(conn, owner)
            identifier = 'cal_' + digest(owner)[:32]
            now = time.time()
            conn.execute(text("INSERT INTO calendar_calendars(id,owner_id,revision,status,created_at,updated_at,payload) VALUES(:id,:owner,1,'active',:now,:now,:payload) ON CONFLICT(id) DO NOTHING"), {'id': identifier, 'owner': owner, 'now': now, 'payload': encoded({'title': 'Open Learn', 'source': 'local', 'color': '#9bb5a0', 'timezone': 'UTC', 'role': 'owner'})})
            # Per-owner writer fence serializes quota/CAS/idempotency decisions.
            conn.execute(text('UPDATE calendar_calendars SET updated_at=updated_at WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner})
            yield conn

    def read(self, conn, owner, kind, identifier):
        row = conn.execute(text(f'SELECT * FROM calendar_{kind} WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).mappings().first()
        if not row: fail('not_found', 'Calendar item unavailable.', 404)
        return {**json.loads(row['payload']), 'id': row['id'], 'revision': row['revision'], 'status': row['status'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}

    def write(self, conn, owner, kind, data, expected=None, parent=None):
        args = {'id': data['id'], 'owner': owner, 'parent': parent, 'status': data.get('status', 'active'), 'payload': encoded(data), 'now': time.time(), 'expected': expected}
        if expected is None:
            conn.execute(text(f'INSERT INTO calendar_{kind}(id,owner_id,parent_id,revision,status,created_at,updated_at,payload) VALUES(:id,:owner,:parent,1,:status,:now,:now,:payload)'), args)
        else:
            result = conn.execute(text(f'UPDATE calendar_{kind} SET payload=:payload,status=:status,revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner AND revision=:expected'), args)
            if result.rowcount != 1: fail('revision_conflict', 'This calendar item changed. Refresh before saving.', 409)
        return self.read(conn, owner, kind, data['id'])

    def list_rows(self, conn, owner, kind, parent=None):
        query = f'SELECT id FROM calendar_{kind} WHERE owner_id=:owner'
        if parent: query += ' AND parent_id=:parent'
        return [self.read(conn, owner, kind, r[0]) for r in conn.execute(text(query), {'owner': owner, 'parent': parent})]

    def permission(self, conn, owner, calendar):
        self.read(conn, owner, 'calendars', calendar)
        identifier = 'permission_' + digest([owner, calendar])[:32]
        row = conn.execute(text('SELECT id FROM calendar_permissions WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
        if not row: self.write(conn, owner, 'permissions', {'id': identifier, 'read': 'none', 'edit': 'ask', 'calendarId': calendar}, parent=calendar)
        return self.read(conn, owner, 'permissions', identifier)

    def calendars(self, owner):
        with self.transaction(owner) as conn:
            return {'items': [{**row, 'permission': self.permission(conn, owner, row['id']), 'canEdit': row['source'] == 'local' or row.get('role') in {'owner', 'writer'}} for row in self.list_rows(conn, owner, 'calendars') if row['status'] == 'active']}

    def get_preferences(self, owner):
        with self.transaction(owner) as conn:
            identifier = 'preferences_' + digest(owner)[:32]
            row = conn.execute(text('SELECT id FROM calendar_preferences WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            return self.read(conn, owner, 'preferences', identifier) if row else Preferences().model_dump()

    def save_preferences(self, owner, body):
        with self.transaction(owner) as conn:
            identifier = 'preferences_' + digest(owner)[:32]
            row = conn.execute(text('SELECT revision FROM calendar_preferences WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            return self.write(conn, owner, 'preferences', {'id': identifier, **body.model_dump()}, row[0] if row else None)

    def set_permission(self, owner, calendar, body):
        with self.transaction(owner) as conn:
            old = self.permission(conn, owner, calendar)
            if old['revision'] != body.expectedRevision: fail('revision_conflict', 'Reload this permission.', 409)
            if body.read == 'none' and body.edit == 'allow': fail('invalid_permission', 'Allow reading before allowing edits.', 422)
            exists = conn.execute(text('SELECT id FROM calendar_permissions WHERE id=:id'), {'id': old['id']}).first()
            return self.write(conn, owner, 'permissions', {**old, **body.model_dump(exclude={'expectedRevision'}), 'grantedAt': time.time()}, old['revision'] if exists else None, calendar)

    def event(self, owner, identifier):
        with self.transaction(owner) as conn: return self.read(conn, owner, 'events', identifier)

    def validate_target(self, conn, owner, event):
        calendar = self.read(conn, owner, 'calendars', event['calendarId'])
        if calendar['source'] != 'local': fail('external_write_required', 'Use the connected calendar operation path.', 409)
        if event.get('courseId') and not conn.execute(text('SELECT 1 FROM courses WHERE id=:id AND owner_id=:owner AND archived_at IS NULL'), {'id': event['courseId'], 'owner': owner}).first(): fail('not_found', 'Course unavailable.', 404)
        if event.get('recurrence'):
            lo = datetime.now(timezone.utc)
            expand(event, lo, lo + timedelta(days=93), ZoneInfo('UTC'))

    def mutate(self, conn, owner, change):
        kind = change['kind']; before = None
        if kind == 'create':
            event = EventInput.model_validate(change['event']).model_dump()
            event.update(id=uid('event'), sourceType='local', status='active')
            self.validate_target(conn, owner, event)
            return {'before': None, 'after': self.write(conn, owner, 'events', event, parent=event['calendarId'])}
        before = self.read(conn, owner, 'events', change['eventId'])
        if before['revision'] != change['expectedRevision'] or before['status'] == 'cancelled': fail('revision_conflict', 'This event changed. Refresh it.', 409)
        self.validate_target(conn, owner, before)
        conn.execute(text("UPDATE reminders SET status='cancelled' WHERE owner_id=:owner AND entity_id=:id AND kind='chat' AND status IN ('pending','delivering')"), {'owner': owner, 'id': before['id']})
        scope, key = change.get('scope', 'series'), change.get('occurrenceKey')
        if before.get('recurrence') and scope != 'series':
            if not key: fail('occurrence_required', 'Choose the recurring occurrence.', 422)
            point = parse(key)
            hits = expand(before, point - timedelta(seconds=1), point + timedelta(seconds=1), ZoneInfo(before['temporal']['timezone']))
            if not any(item['occurrenceKey'] == key for item in hits): fail('invalid_occurrence', 'That occurrence does not belong to this event.', 422)
            if scope == 'occurrence':
                identifier = 'override_' + digest([before['id'], key])[:32]
                overrides = self.list_rows(conn, owner, 'overrides', before['id'])
                old = next((r for r in overrides if r['id'] == identifier), None)
                data = {'id': identifier, 'eventId': before['id'], 'occurrenceKey': key, 'cancelled': kind == 'cancel'}
                if kind != 'cancel':
                    replacement = EventInput.model_validate(change['event']).model_dump()
                    if replacement['calendarId'] != before['calendarId']: fail('invalid_scope', 'Move the series to change calendar.', 422)
                    replacement['recurrence'] = None
                    self.validate_target(conn, owner, replacement); data['event'] = replacement
                self.write(conn, owner, 'overrides', data, old['revision'] if old else None, before['id'])
                after = self.write(conn, owner, 'events', before, before['revision'])
                return {'before': before, 'after': after, 'overrideBefore': old, 'overrideAfter': data}
            # Future scope truncates the original series and creates a successor.
            rule = ';'.join(part for part in before['recurrence'].split(';') if not part.startswith(('UNTIL=', 'COUNT=')))
            cut = (point.astimezone(timezone.utc) - timedelta(seconds=1)).strftime('%Y%m%dT%H%M%SZ')
            after = self.write(conn, owner, 'events', {**before, 'recurrence': rule + ';UNTIL=' + cut}, before['revision'])
            created = None
            if kind != 'cancel':
                successor = EventInput.model_validate(change['event']).model_dump()
                successor.update(id=uid('event'), sourceType='local', splitFrom=before['id'])
                self.validate_target(conn, owner, successor)
                created = self.write(conn, owner, 'events', successor, parent=successor['calendarId'])
            return {'before': before, 'after': after, 'successor': created}
        event = {**before, 'status': 'cancelled'} if kind == 'cancel' else {**before, **EventInput.model_validate(change['event']).model_dump()}
        self.validate_target(conn, owner, event)
        after = self.write(conn, owner, 'events', event, before['revision'])
        return {'before': before, 'after': after}

    def operation(self, owner, key, changes, actor='human'):
        if not key or len(key) > 160: fail('invalid_key', 'Provide a stable operation key.', 422)
        if os.getenv('OPENLEARN_CALENDAR_WRITES', 'true').lower() != 'true': fail('calendar_writes_disabled', 'Calendar editing is temporarily unavailable.', 503)
        identifier = 'operation_' + digest([owner, key])[:32]; request_hash = digest(changes)
        with self.transaction(owner) as conn:
            existing = conn.execute(text('SELECT id FROM calendar_operations WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            if existing:
                saved = self.read(conn, owner, 'operations', identifier)
                if saved['requestHash'] != request_hash: fail('idempotency_conflict', 'This key has different changes.', 409)
                return saved
            targets = [c['event'] if c['kind'] == 'create' else self.read(conn, owner, 'events', c['eventId']) for c in changes]
            if any(self.read(conn, owner, 'calendars', t['calendarId'])['source'] == 'google' for t in targets):
                from .google_writes import GoogleWrites
                return GoogleWrites(self.store).queue(conn, owner, identifier, changes, actor)
            results = [self.mutate(conn, owner, change) for change in changes]
            return self.write(conn, owner, 'operations', {'id': identifier, 'status': 'applied', 'requestHash': request_hash, 'actor': actor, 'results': results, 'undoUntil': time.time() + 600})

    def create(self, owner, body, key): return self.operation(owner, key, [{'kind': 'create', 'event': body.model_dump()}])
    def edit(self, owner, identifier, body, key): return self.operation(owner, key, [{'kind': 'update', 'eventId': identifier, **body.model_dump()}])
    def cancel(self, owner, identifier, body, key): return self.operation(owner, key, [{'kind': 'cancel', 'eventId': identifier, **body.model_dump()}])

    def occurrences(self, owner, start, end, zone='UTC', calendar_ids=None, course_ids=None, agent=False, cursor=0):
        lo, hi = bounds(start, end)
        try: display_zone = ZoneInfo(zone)
        except (ValueError, KeyError): fail('invalid_timezone', 'Choose an IANA timezone.', 422)
        with self.transaction(owner) as conn:
            calendars = [r for r in self.list_rows(conn, owner, 'calendars') if r['status'] == 'active']; by_id = {r['id']: r for r in calendars}
            sync_states = self.list_rows(conn, owner, 'sync')
            selected = calendar_ids or list(by_id)
            if any(identifier not in by_id for identifier in selected): fail('not_found', 'Calendar unavailable.', 404)
            permissions = {identifier: self.permission(conn, owner, identifier) for identifier in selected}
            events = self.list_rows(conn, owner, 'events'); all_overrides = self.list_rows(conn, owner, 'overrides')
            academic_rows = conn.execute(text('SELECT e.id,e.course_id,e.payload FROM academic_entities e JOIN courses c ON c.id=e.course_id AND c.owner_id=e.owner_id WHERE e.owner_id=:owner AND c.archived_at IS NULL'), {'owner': owner}).mappings().all()
            policies = conn.execute(text("SELECT id,revision,payload,active FROM reminder_policies WHERE owner_id=:owner AND kind='routine'"), {'owner': owner}).mappings().all()
            reminders = conn.execute(text("SELECT id,due_at,payload,status FROM reminders WHERE owner_id=:owner AND kind='chat' AND entity_id IS NULL AND status NOT IN ('cancelled','expired') AND due_at>=:lo AND due_at<:hi"), {'owner': owner, 'lo': lo.timestamp(), 'hi': hi.timestamp()}).mappings().all()
            revision = digest([(r['id'], r['revision']) for r in events + all_overrides] + [(k, v['revision']) for k, v in permissions.items()])
        items = []
        for event in events:
            if event['status'] == 'cancelled' or event['calendarId'] not in selected or (course_ids and event.get('courseId') not in course_ids): continue
            permission = permissions[event['calendarId']]
            if agent and permission['read'] == 'none': continue
            expanded = expand(event, lo, hi, display_zone)
            overrides = {row['occurrenceKey']: row for row in all_overrides if row['eventId'] == event['id']}
            for item in expanded:
                override = overrides.get(item['occurrenceKey'])
                if override: continue  # Overrides are separately range-filtered, including moved-in instances.
                items.append(item)
            for key, override in overrides.items():
                if override.get('cancelled') or not override.get('event'): continue
                replacements = expand({**event, **override['event'], 'recurrence': None}, lo, hi, display_zone)
                for item in replacements: items.append({**item, 'occurrenceKey': key, 'id': event['id'] + '@' + key})
        # Project academic source facts once, read-only; use existing source IDs.
        local_id = next((r['id'] for r in calendars if r['source'] == 'local'), None)
        from ..reminder_schedule import next_fire
        for policy in policies:
            routine = json.loads(policy['payload']); calendar = routine.get('calendarId') or local_id
            if not policy['active'] or routine.get('calendarPresentation') != 'study_session' or calendar not in selected: continue
            if agent and permissions[calendar]['read'] == 'none': continue
            if course_ids and routine.get('courseId') not in course_ids: continue
            instant = next_fire(routine['schedule'], routine['timezone'], lo.timestamp() - routine.get('durationMinutes', 30) * 60)
            for _ in range(1500):
                if instant is None or instant >= hi.timestamp(): break
                start_at = datetime.fromtimestamp(instant, ZoneInfo(routine['timezone']))
                finish = start_at + timedelta(minutes=routine.get('durationMinutes', 30))
                item = {'id': 'routine_' + policy['id'] + '@' + start_at.isoformat(), 'eventId': 'routine_' + policy['id'], 'routineId': policy['id'], 'occurrenceKey': start_at.isoformat(), 'calendarId': calendar, 'title': routine['message'], 'type': 'study', 'courseId': routine.get('courseId'), 'sourceType': 'routine', 'revision': policy['revision'], 'busy': True, 'sortAt': instant, 'temporal': {'mode': 'timed', 'timezone': routine['timezone'], 'start': start_at.isoformat(), 'end': finish.isoformat()}}
                items.append(item)
                instant = next_fire(routine['schedule'], routine['timezone'], instant)
        if local_id in selected and (not agent or permissions[local_id]['read'] != 'none'):
            for row in reminders:
                reminder = json.loads(row['payload'])
                if course_ids and reminder.get('courseId') not in course_ids: continue
                items.append({'id': 'reminder_' + row['id'], 'eventId': row['id'], 'calendarId': local_id, 'title': reminder.get('message') or reminder.get('title') or 'Reminder', 'type': 'reminder', 'courseId': reminder.get('courseId'), 'sourceType': 'reminder', 'revision': 1, 'busy': False, 'sortAt': row['due_at'], 'temporal': {'mode': 'deadline', 'timezone': reminder.get('timezone', zone), 'dueAt': datetime.fromtimestamp(row['due_at'], timezone.utc).isoformat()}})
        if local_id in selected and (not agent or permissions[local_id]['read'] != 'none'):
            for row in academic_rows:
                if course_ids and row['course_id'] not in course_ids: continue
                source = json.loads(row['payload']); facts = source.get('facts', {})
                if any(facts.get(k, {}).get('value') for k in ('cancelled', 'completed')): continue
                fact = next((facts[k] for k in ('start', 'due', 'date') if facts.get(k)), None)
                if not fact or fact.get('conflict'): continue
                when = fact.get('value') or {}; value = when.get('value')
                if when.get('kind') not in {'instant', 'date_only'} or not value: continue
                temporal = {'mode': 'deadline', 'timezone': zone, 'dueAt': value} if when['kind'] == 'instant' else {'mode': 'deadline', 'timezone': zone, 'dueDate': value}
                projection = {'id': 'academic_' + row['id'], 'calendarId': local_id, 'title': str(facts.get('title', {}).get('value') or 'Academic event'), 'type': source.get('kind', 'assignment'), 'temporal': temporal, 'courseId': row['course_id'], 'sourceType': 'academic', 'revision': 1, 'canEdit': False, 'busy': False}
                items.extend(expand(projection, lo, hi, display_zone))
        result = []
        for item in items:
            permission = permissions[item['calendarId']]
            if agent and permission['read'] == 'busy_only':
                item = {k: v for k, v in item.items() if k in {'id', 'eventId', 'calendarId', 'temporal', 'busy', 'occurrenceKey', 'sortAt', 'revision'}}
                item['title'] = 'Busy'
            result.append({**item, 'canEdit': item.get('sourceType') == 'local' or item.get('sourceType') == 'google' and by_id[item['calendarId']].get('role') in {'writer', 'owner'}, 'syncStatus': 'saved'})
        result.sort(key=lambda r: (r['sortAt'], r['id']))
        offset = int(cursor)
        if offset < 0: fail('invalid_cursor', 'Invalid calendar cursor.', 422)
        states = []
        for calendar in selected:
            state = next((s for s in sync_states if s['id'] == 'sync_' + digest([owner, calendar])[:32]), {})
            current = by_id[calendar]['source'] == 'local' or state.get('status') == 'current' and state.get('lastSuccess', 0) > time.time() - 600
            states.append({'calendarId': calendar, 'status': 'current' if current else 'stale', 'lastSuccess': state.get('lastSuccess')})
        return {'items': result[offset:offset + 500], 'nextCursor': str(offset + 500) if len(result) > offset + 500 else None, 'snapshotRevision': revision, 'generatedAt': time.time(), 'sourceStates': states, 'partial': any(s['status'] != 'current' for s in states)}

    def propose(self, owner, body, key):
        identifier = 'proposal_' + digest([owner, key])[:32]
        with self.transaction(owner) as conn:
            if body.sessionId and not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id': body.sessionId, 'owner': owner}).first(): fail('not_found', 'Conversation unavailable.', 404)
            changes = body.model_dump()['changes']; calendar_ids = set()
            for change in changes:
                target = change['event'] if change['kind'] == 'create' else self.read(conn, owner, 'events', change['eventId'])
                calendar = target['calendarId']; calendar_ids.add(calendar)
                permission = self.permission(conn, owner, calendar)
                if permission['read'] == 'none': fail('calendar_read_required', 'Allow Buddy to read this calendar first.', 403)
                if change['kind'] != 'create' and permission['read'] != 'details': fail('calendar_details_required', 'Allow Buddy to read event details before changing existing events.', 403)
                if change['kind'] != 'create' and target['revision'] != change['expectedRevision']: fail('revision_conflict', 'Reload the event.', 409)
            before_events = [None if c['kind'] == 'create' else self.read(conn, owner, 'events', c['eventId']) for c in changes]
            payload = {'id': identifier, **body.model_dump(), 'beforeEvents': before_events, 'calendarIds': sorted(calendar_ids), 'permissionRevisions': {c: self.permission(conn, owner, c)['revision'] for c in calendar_ids}, 'expiresAt': time.time() + 900, 'proposalHash': digest(body.model_dump()), 'status': 'awaiting_confirmation'}
            existing = conn.execute(text('SELECT id FROM calendar_proposals WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            if existing:
                old = self.read(conn, owner, 'proposals', identifier)
                if old['proposalHash'] != payload['proposalHash']: fail('idempotency_conflict', 'Proposal key has different content.', 409)
                return old
            return self.write(conn, owner, 'proposals', payload)

    def decide(self, owner, identifier, body, key, unattended=False):
        if os.getenv('OPENLEARN_CALENDAR_BUDDY_WRITES', 'true').lower() != 'true': fail('buddy_writes_disabled', 'Buddy calendar editing is unavailable.', 503)
        with self.transaction(owner) as conn:
            if unattended and body.rememberCalendarIds: fail('human_consent_required', 'Only a human can grant persistent access.', 403)
            proposal = self.read(conn, owner, 'proposals', identifier)
            if proposal['proposalHash'] != body.proposalHash: fail('proposal_changed', 'Review the current proposal.', 409)
            if proposal['status'] in {'applied', 'executing'}: return self.read(conn, owner, 'operations', proposal['operationId'])
            if proposal['revision'] != body.expectedRevision or proposal['status'] != 'awaiting_confirmation' or proposal['expiresAt'] <= time.time(): fail('proposal_expired', 'Prepare a fresh calendar proposal.', 409)
            if not set(body.rememberCalendarIds) <= set(proposal['calendarIds']): fail('invalid_scope', 'Only grant access to calendars in this proposal.', 422)
            if body.decision == 'cancel': return self.write(conn, owner, 'proposals', {**proposal, 'status': 'cancelled'}, proposal['revision'])
            for calendar in proposal['calendarIds']:
                permission = self.permission(conn, owner, calendar)
                if permission['read'] == 'none' or permission['revision'] != proposal['permissionRevisions'][calendar]: fail('permission_changed', 'Calendar permissions changed. Prepare a fresh proposal.', 409)
                if unattended and permission['edit'] != 'allow': fail('approval_required', 'Approve this calendar change.', 403)
            if unattended and any(c['kind'] == 'cancel' and c.get('scope') == 'series' and self.read(conn, owner, 'events', c['eventId']).get('recurrence') for c in proposal['changes']): fail('approval_required', 'Deleting a recurring series requires confirmation.', 403)
            external = any(self.read(conn, owner, 'calendars', c)['source'] == 'google' for c in proposal['calendarIds'])
            results = [] if external else [self.mutate(conn, owner, c) for c in proposal['changes']]
            for calendar in body.rememberCalendarIds:
                permission = self.permission(conn, owner, calendar)
                exists = conn.execute(text('SELECT id FROM calendar_permissions WHERE id=:id'), {'id': permission['id']}).first()
                self.write(conn, owner, 'permissions', {**permission, 'edit': 'allow', 'grantedAt': time.time()}, permission['revision'] if exists else None, calendar)
            operation_id = 'operation_' + digest([owner, identifier])[:32]
            if external:
                from .google_writes import GoogleWrites
                changes = [{**c, 'humanConfirmed': not unattended} for c in proposal['changes']]
                grants = {c: self.permission(conn, owner, c)['revision'] for c in proposal['calendarIds']} if unattended else None
                operation = GoogleWrites(self.store).queue(conn, owner, operation_id, changes, 'buddy', grants)
                operation = self.write(conn, owner, 'operations', {**operation, 'proposalId': identifier}, operation['revision'])
            else: operation = self.write(conn, owner, 'operations', {'id': operation_id, 'status': 'applied', 'actor': 'buddy', 'proposalId': identifier, 'requestHash': proposal['proposalHash'], 'results': results, 'undoUntil': time.time() + 600})
            self.write(conn, owner, 'proposals', {**proposal, 'status': 'applied' if not external else 'executing', 'operationId': operation_id}, proposal['revision'])
            return operation

    def get_operation(self, owner, identifier):
        with self.transaction(owner) as conn: return self.read(conn, owner, 'operations', identifier)

    def undo(self, owner, identifier, key):
        with self.transaction(owner) as conn:
            operation = self.read(conn, owner, 'operations', identifier)
            if operation['status'] == 'undone': return self.read(conn, owner, 'operations', operation['undoOperationId'])
            if operation.get('undoUntil', 0) < time.time(): fail('undo_expired', 'The undo window has ended.', 409)
            restored = []
            for result in reversed(operation['results']):
                after, before = result['after'], result['before']
                current = self.read(conn, owner, 'events', after['id'])
                if current['revision'] != after['revision']: fail('revision_conflict', 'The event changed after this operation.', 409)
                successor = result.get('successor')
                if successor:
                    next_event = self.read(conn, owner, 'events', successor['id'])
                    if next_event['revision'] != successor['revision']: fail('revision_conflict', 'The successor event changed.', 409)
                    self.write(conn, owner, 'events', {**next_event, 'status': 'cancelled'}, next_event['revision'])
                if result.get('overrideAfter'):
                    override = self.read(conn, owner, 'overrides', result['overrideAfter']['id'])
                    if result.get('overrideBefore'): self.write(conn, owner, 'overrides', result['overrideBefore'], override['revision'])
                    else: conn.execute(text('DELETE FROM calendar_overrides WHERE id=:id AND owner_id=:owner'), {'id': override['id'], 'owner': owner})
                restored.append(self.write(conn, owner, 'events', before or {**current, 'status': 'cancelled'}, current['revision']))
            receipt = self.write(conn, owner, 'operations', {'id': uid('undo'), 'status': 'applied', 'actor': 'human', 'undoes': identifier, 'results': restored})
            self.write(conn, owner, 'operations', {**operation, 'status': 'undone', 'undoOperationId': receipt['id']}, operation['revision'])
            return receipt

    def availability(self, owner, body, agent=False):
        lo, hi = bounds(body.start, body.end)
        if body.endHour <= body.startHour: fail('invalid_hours', 'End hour must follow start hour.', 422)
        feed = self.occurrences(owner, body.start, body.end, body.timezone, body.calendarIds, agent=agent)
        if feed['partial'] or feed['nextCursor']: return {'slots': [], 'complete': False, 'reasonCode': 'incomplete_schedule'}
        if agent:
            with self.transaction(owner) as conn:
                if any(self.permission(conn, owner, c)['read'] == 'none' for c in body.calendarIds): return {'slots': [], 'complete': False, 'reasonCode': 'calendar_read_required'}
        zone = ZoneInfo(body.timezone); busy = []
        for item in feed['items']:
            temporal = item['temporal']
            if not item.get('busy', False) or temporal['mode'] == 'deadline': continue
            if temporal['mode'] == 'timed': busy.append((parse(temporal['start']), parse(temporal['end'])))
            else: busy.append((datetime.fromisoformat(temporal['startDate']).replace(tzinfo=zone), datetime.fromisoformat(temporal['endDate']).replace(tzinfo=zone)))
        candidate = lo.astimezone(zone).replace(second=0, microsecond=0); slots = []
        duration = timedelta(minutes=body.duration)
        for _ in range(9000):
            if candidate + duration > hi or len(slots) >= 50: break
            finish = candidate + duration
            if body.startHour <= candidate.hour and (finish.date() == candidate.date() and finish.hour + finish.minute / 60 <= body.endHour) and not any(candidate < end and finish > start for start, end in busy): slots.append({'start': candidate.isoformat(), 'end': finish.isoformat()})
            candidate += timedelta(minutes=15)
        return {'slots': slots, 'complete': True, 'generatedAt': feed['generatedAt']}
