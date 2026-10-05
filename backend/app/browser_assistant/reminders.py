"""Revision-bound reminder scheduling and durable notification delivery."""
import json
import re
import time
from datetime import datetime, timedelta, timezone as utc_timezone
from sqlalchemy import text
from .policy import timezone, checksum
from .store import AssistantStore
from .contracts import ReminderPolicyInput
from ..execution_outbox import ExecutionOutbox
from ..workflow_store import uid, encoded, WorkflowStore
from ..identity import assert_owner_active, fail


def schedule_entity(store, conn, owner, entity):
    ExecutionOutbox(store).append(conn, owner, 'assistant.reminder.rebuild',
        f"{entity['id']}:{entity['revision']}", {'entityId': entity['id'], 'revision': entity['revision']})


def event_instant(entity, policy):
    fact = next((entity.get('facts', {}).get(key) for key in ('due', 'date', 'start') if entity.get('facts', {}).get(key)), None)
    if not fact or fact.get('conflict') or entity.get('facts', {}).get('cancelled', {}).get('value') is True: return None
    if fact.get('source', {}).get('extractionMethod') == 'visual_needs_review': return None
    value = fact.get('value') or {}
    if value.get('kind') == 'instant':
        date = datetime.fromisoformat(value['value'].replace('Z', '+00:00'))
        return date.timestamp() if date.tzinfo else None
    if value.get('kind') == 'date_only' and policy.get('dateOnlyTime'):
        wall = datetime.fromisoformat(value['value'] + 'T' + policy['dateOnlyTime'])
        tz = timezone(policy['timezone']); date = wall.replace(tzinfo=tz)
        # Reject a nonexistent local wall time during the DST spring transition.
        if date.astimezone(utc_timezone.utc).astimezone(tz).replace(tzinfo=None) != wall: return None
        return date.timestamp()
    return None


def rebuild(store, conn, owner, entity):
    assert_owner_active(conn, owner)
    rows = conn.execute(text('SELECT id,revision,payload FROM reminder_policies WHERE owner_id=:owner AND active=true'), {'owner': owner}).mappings().all()
    for row in rows:
        policy = json.loads(row['payload'])
        if policy.get('courseId') and policy['courseId'] != entity['courseId']: continue
        if policy.get('entityId') and policy['entityId'] != entity['id']: continue
        if 'entityIds' in policy and entity['id'] not in policy['entityIds']: continue
        if policy.get('entityKinds') and entity['kind'] not in policy['entityKinds']: continue
        if policy.get('connectionId') and not any(f.get('source',{}).get('connectionId') == policy['connectionId'] for f in entity.get('facts',{}).values()): continue
        conn.execute(text("UPDATE reminders SET status='cancelled' WHERE owner_id=:owner AND entity_id=:entity AND policy_id=:policy AND status IN ('pending','delivering') AND (entity_revision<>:revision OR policy_revision<>:policyRevision)"),
                     {'owner': owner, 'entity': entity['id'], 'policy': row['id'], 'revision': entity['revision'], 'policyRevision': row['revision']})
        instant = event_instant(entity, policy)
        if instant is None: continue
        title = entity['facts'].get('title', {}).get('value') or 'Academic event'
        for offset in policy['offsetsMinutes']:
            if not 0 <= offset <= 60*24*90: continue
            due = instant - offset*60
            local = datetime.fromtimestamp(due, timezone(policy['timezone']))
            start, end = policy['quietStart'], policy['quietEnd']
            quiet = start <= local.hour < end if start < end else local.hour >= start or local.hour < end if start != end else False
            if quiet:
                proposed = local.replace(hour=end, minute=0, second=0, microsecond=0)
                if proposed <= local: proposed += timedelta(days=1)
                if proposed.timestamp() >= instant: continue
                due = proposed.timestamp()
            key = checksum(f"{owner}:{entity['id']}:{entity['revision']}:{row['id']}:{row['revision']}:{offset}")
            identifier=uid('reminder')
            conn.execute(text('''INSERT INTO reminders(id,owner_id,entity_id,entity_revision,policy_id,policy_revision,due_at,status,dedup_key,payload)
                VALUES(:id,:owner,:entity,:revision,:policy,:policyRevision,:due,'pending',:key,:payload) ON CONFLICT(owner_id,dedup_key) DO NOTHING'''),
                {'id': identifier, 'owner': owner, 'entity': entity['id'], 'revision': entity['revision'], 'policy': row['id'],
                 'policyRevision': row['revision'], 'due': due, 'key': key,
                 'payload': encoded({'title': title, 'eventAt': instant, 'channels': policy['channels'], 'catchupMinutes': policy['catchupMinutes'],
                                     'source': next((f.get('source') for f in entity['facts'].values() if f.get('source')), None)})})
            actual=conn.execute(text('SELECT id FROM reminders WHERE owner_id=:owner AND dedup_key=:key'),{'owner':owner,'key':key}).scalar_one()
            from ..buddy_service import BuddyService
            BuddyService(store).responsibility(conn,owner,actual,'reminder',entity['courseId'])


def create_policy(store, owner, command, identifier=None):
    timezone(command.timezone)
    if any(not 0 <= n <= 129600 for n in command.offsets_minutes): fail('invalid_input', 'Reminder offsets must be within 90 days.', 422)
    if command.date_only_time and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', command.date_only_time): fail('invalid_input', 'Use a 24-hour reminder time.', 422)
    data = command.model_dump(by_alias=True, exclude_none=True)
    data.pop('expectedRevision', None)
    with store.transaction() as conn:
        assert_owner_active(conn, owner)
        from ..academic_planning import AcademicPlanningService
        svc = AcademicPlanningService(store)
        if command.course_id:
            from .policy import require_course
            require_course(conn, owner, command.course_id)
        if command.connection_id: AssistantStore(store).row(conn, 'site_connections', owner, command.connection_id)
        if command.entity_id and not conn.execute(text('SELECT 1 FROM academic_entities WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': command.entity_id}).first():
            fail('not_found', 'Academic event unavailable.', 404)
        revision = 1
        if identifier:
            old = conn.execute(text('SELECT revision FROM reminder_policies WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': identifier}).scalar_one_or_none()
            if old is None: fail('not_found', 'Reminder policy unavailable.', 404)
            if command.expected_revision != old: fail('revision_conflict', 'Refresh this reminder policy.', 409)
            revision = old+1
            conn.execute(text('UPDATE reminder_policies SET revision=:revision,active=:active,payload=:payload WHERE id=:id AND owner_id=:owner AND revision=:expected'),
                         {'revision': revision, 'active': command.active, 'payload': encoded(data), 'id': identifier, 'owner': owner, 'expected': old})
            conn.execute(text("UPDATE reminders SET status='cancelled' WHERE policy_id=:id AND owner_id=:owner AND status IN ('pending','delivering')"), {'id': identifier, 'owner': owner})
        else:
            identifier = uid('policy')
            conn.execute(text('INSERT INTO reminder_policies(id,owner_id,revision,active,payload) VALUES(:id,:owner,1,:active,:payload)'),
                         {'id': identifier, 'owner': owner, 'active': command.active, 'payload': encoded(data)})
        if command.active:
            for r in conn.execute(text('SELECT payload FROM academic_entities WHERE owner_id=:owner'), {'owner': owner}).scalars(): rebuild(store, conn, owner, json.loads(r))
    return {'id': identifier, 'revision': revision, **data}


def valid_reminder(conn, row):
    assert_owner_active(conn, row['owner_id'])
    entity = conn.execute(text('SELECT revision FROM academic_entities WHERE owner_id=:owner AND id=:id'), {'owner': row['owner_id'], 'id': row['entity_id']}).scalar_one_or_none()
    policy = conn.execute(text('SELECT revision FROM reminder_policies WHERE owner_id=:owner AND id=:id AND active=true'), {'owner': row['owner_id'], 'id': row['policy_id']}).scalar_one_or_none()
    return entity == row['entity_revision'] and policy == row['policy_revision']


def tick_reminders(store):
    def deliver(conn, owner, _, data):
        row = conn.execute(text('SELECT payload FROM academic_entities WHERE owner_id=:owner AND id=:id AND revision=:revision'),
                           {'owner': owner, 'id': data['entityId'], 'revision': data['revision']}).scalar_one_or_none()
        if row: rebuild(store, conn, owner, json.loads(row))
    ExecutionOutbox(store).drain({'assistant.reminder.rebuild': deliver}, 50)
    with store.transaction() as conn:
        suffix = ' FOR UPDATE SKIP LOCKED' if conn.dialect.name == 'postgresql' else ''
        rows = conn.execute(text("SELECT * FROM reminders WHERE status='pending' AND due_at<=:now ORDER BY due_at LIMIT 30" + suffix), {'now': time.time()}).mappings().all()
        for r in rows:
            row = dict(r); payload = json.loads(row['payload'])
            if not valid_reminder(conn, row): status = 'cancelled'
            elif time.time() > min(payload['eventAt'], row['due_at'] + payload['catchupMinutes']*60): status = 'expired'
            else: status = 'delivered'
            claimed = conn.execute(text("UPDATE reminders SET status=:status WHERE id=:id AND status='pending'"), {'id': row['id'], 'status': status}).rowcount
            if not claimed or status != 'delivered': continue
            payload['url']=reminder_target(conn,row)
            conn.execute(text('''INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at)
                VALUES(:id,:owner,:reminder,'inbox','available',:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING'''),
                {'id': uid('notification'), 'owner': row['owner_id'], 'reminder': row['id'], 'payload': encoded(payload), 'now': time.time()})
            if 'push' in payload['channels']:
                WorkflowStore(store).enqueue(row['owner_id'], row['id'], 'reminder_dispatch', {'reminderId': row['id']}, 'push:'+row['id'], connection=conn, max_attempts=1)
    return len(rows)


def dispatch_push(store, job):
    import os
    jobs = WorkflowStore(store)
    with store.transaction() as conn:
        row = conn.execute(text('SELECT * FROM reminders WHERE owner_id=:owner AND id=:id'), {'owner': job['owner_id'], 'id': job['target_id']}).mappings().first()
        if not row or not valid_reminder(conn, row): return jobs.finish(conn, job, {'status': 'cancelled'})
        payload = json.loads(row['payload'])
        if time.time() > min(payload['eventAt'], row['due_at'] + payload['catchupMinutes']*60):
            return jobs.finish(conn, job, {'status':'expired'})
        subscriptions = conn.execute(text('SELECT id,payload FROM notification_subscriptions WHERE owner_id=:owner AND active=true'), {'owner': job['owner_id']}).mappings().all()
        subscriptions = [s for s in subscriptions if json.loads(s['payload']).get('kind') != 'expo']
        claimed = conn.execute(text('''INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at)
            VALUES(:id,:owner,:reminder,'push','outcome_unknown','{}',:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING'''),
            {'id': uid('push'), 'owner': job['owner_id'], 'reminder': row['id'], 'now': time.time()}).rowcount
        if not claimed: return jobs.finish(conn, job, {'status':'already_attempted'})
    status = 'unconfigured'
    if os.getenv('OPENLEARN_VAPID_PRIVATE_KEY'):
        from pywebpush import webpush, WebPushException
        status = 'sent_unconfirmed'
        for subscription in subscriptions:
            # Recheck immediately before each external delivery.
            with store.transaction() as conn:
                fresh = conn.execute(text('SELECT * FROM reminders WHERE id=:id AND owner_id=:owner'), {'id': row['id'], 'owner': job['owner_id']}).mappings().one()
                if not valid_reminder(conn, fresh): status = 'cancelled'; break
                if time.time() > min(payload['eventAt'], row['due_at'] + payload['catchupMinutes']*60): status = 'expired'; break
                target_url=reminder_target(conn,row)
            try:
                webpush(json.loads(subscription['payload']), json.dumps({'id': row['id'], 'title': payload['title'], 'body': 'An academic deadline is approaching.', 'url': target_url}),
                        vapid_private_key=os.environ['OPENLEARN_VAPID_PRIVATE_KEY'],
                        vapid_claims={'sub': os.environ.get('OPENLEARN_VAPID_SUBJECT', 'mailto:notifications@example.invalid')}, ttl=300, timeout=10)
            except WebPushException as exc:
                status = 'outcome_unknown'
                if exc.response is not None and exc.response.status_code in {404, 410}:
                    with store.transaction() as conn: conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE id=:id AND owner_id=:owner'), {'id': subscription['id'], 'owner': job['owner_id']})
    with store.transaction() as conn:
        conn.execute(text("UPDATE notification_deliveries SET status=:status WHERE reminder_id=:id AND owner_id=:owner AND channel='push'"), {'status': status, 'id': row['id'], 'owner': job['owner_id']})
        jobs.finish(conn, job, {'status': status})

def reminder_target(conn,row):
    from urllib.parse import urlencode
    assignment=conn.execute(text('SELECT buddy_id,course_id FROM buddy_responsibilities WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':row['owner_id']}).mappings().first()
    query={'view':'reminders','reminder':row['id']}
    if assignment:
        query['buddy']=assignment['buddy_id']
        if assignment['course_id']:query['course']=assignment['course_id']
    return '/chat?'+urlencode(query)
