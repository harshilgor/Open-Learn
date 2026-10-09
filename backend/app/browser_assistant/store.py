"""Assistant aggregates use the existing database and execution ownership."""
import json
import time
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded, uid, WorkflowStore

TABLES = {'site_connections', 'assistant_runs', 'assistant_steps', 'browser_snapshots',
          'browser_session_leases', 'reminder_policies', 'reminders', 'notification_deliveries',
          'notification_subscriptions', 'connection_refresh_schedules', 'academic_scan_coverage'}


class AssistantStore:
    def __init__(self, store):
        self.store = store
        self.jobs = WorkflowStore(store)

    def row(self, conn, table, owner, identifier, *, lock=False):
        if table not in TABLES: raise ValueError('Invalid table')
        assert_owner_active(conn, owner)
        suffix = ' FOR UPDATE' if lock and conn.dialect.name == 'postgresql' else ''
        row = conn.execute(text(f'SELECT * FROM {table} WHERE id=:id AND owner_id=:owner' + suffix),
                           {'id': identifier, 'owner': owner}).mappings().first()
        if row is None: fail('not_found', 'This assistant resource is unavailable.', 404)
        return {**json.loads(row['payload']), **dict(row)}

    def read(self, table, owner, identifier):
        with self.store.engine.connect() as conn:
            return self.row(conn, table, owner, identifier)

    def list(self, table, owner):
        if table not in TABLES: raise ValueError('Invalid table')
        with self.store.engine.connect() as conn:
            assert_owner_active(conn, owner)
            return [{**json.loads(r['payload']), **dict(r)} for r in conn.execute(
                text(f'SELECT * FROM {table} WHERE owner_id=:owner'), {'owner': owner}).mappings()]

    def run(self, conn, owner, identifier):
        return self.row(conn, 'assistant_runs', owner, identifier, lock=True)

    def update_run(self, conn, run, **changes):
        from ..execution import active_job
        if active_job.get() is not None and run.get('browserControl',{}).get('owner','agent') != 'agent' and 'status' in changes:
            fail('control_not_ready','Browser control is held by the learner.',409)
        next_status = changes.get('status', run['status'])
        next_question = changes.get('question', run.get('question'))
        waiting_for_answer = next_status in {'waiting_for_user', 'waiting_for_login', 'waiting_for_device'}
        if waiting_for_answer and next_question:
            previous_question = run.get('question')
            previous_state = run.get('inputRequestState')
            if run['status'] not in {'waiting_for_user', 'waiting_for_login', 'waiting_for_device'} or previous_question != next_question or previous_state != 'open':
                request_revision = int(run.get('inputRequestRevision') or 0) + 1
                request_id = uid('browser_input')
                error = changes.get('error', run.get('error'))
                answerable_errors = {'clarification_required', 'ambiguous_event', 'course_required', 'ambiguous_course',
                                     'connection_required', 'save_required', 'origin_not_approved', 'action_blocked',
                                     # A cloud action with an unknown outcome can only resume after the learner
                                     # explicitly chooses to continue; the worker will observe before acting again.
                                     'outcome_unknown'}
                input_kind = 'text' if next_status == 'waiting_for_user' and error in answerable_errors else 'action'
                changes.update(inputRequestId=request_id, inputRequestRevision=request_revision,
                               inputRequestState='open', inputRequestKind=input_kind)
        elif next_status not in {'waiting_for_user', 'waiting_for_login', 'waiting_for_device'} and run.get('inputRequestState') == 'open':
            changes.setdefault('inputRequestState', 'closed')
        # Scalar columns win over payload duplicates; expected revision fences concurrent writers.
        updated = {**run, **changes, 'revision': run['revision'] + 1, 'updatedAt': time.time()}
        value = {k: v for k, v in updated.items() if k not in {'payload', 'owner_id', 'created_at', 'updated_at', 'request_hash', 'command_key', 'session_id', 'connection_id'}}
        changed = conn.execute(text('''UPDATE assistant_runs SET payload=:payload, revision=:next,
            status=:status, connection_id=:connection, updated_at=:now WHERE id=:id AND owner_id=:owner AND revision=:expected'''),
            {'payload': encoded(value), 'next': updated['revision'], 'status': updated['status'],
             'connection': updated.get('connectionId'), 'now': time.time(), 'id': run['id'],
             'owner': run['owner_id'], 'expected': run['revision']})
        if changed.rowcount != 1: fail('revision_conflict', 'The browser task changed. Refresh it.', 409)
        return updated

    def event(self, conn, run, kind, message, **data):
        sequence = conn.execute(text('UPDATE assistant_runs SET event_sequence=event_sequence+1 WHERE id=:run RETURNING event_sequence'), {'run': run['id']}).scalar_one()
        payload = {'type': kind, 'message': message, 'status': run['status'], **data}
        if kind in {'task.attention', 'task.needs_input'} and run.get('inputRequestState') == 'open':
            payload['request'] = pending_request(run)
        conn.execute(text('INSERT INTO assistant_events(id,owner_id,run_id,sequence,payload,created_at) VALUES(:id,:owner,:run,:seq,:payload,:now)'),
                     {'id': uid('ae'), 'owner': run['owner_id'], 'run': run['id'], 'seq': sequence, 'payload': encoded(payload), 'now': time.time()})

    def enqueue(self, conn, run, stage='assistant_step'):
        job = self.jobs.enqueue(run['owner_id'], run['id'], stage, {'runId': run['id']},
                                f"assistant:{run['id']}:{run['revision']}:{stage}", connection=conn, queue='interactive', max_attempts=3)
        return job['id']

    def events(self, owner, identifier, after=0):
        self.read('assistant_runs', owner, identifier)
        with self.store.engine.connect() as conn:
            return [{'sequence': r['sequence'], **json.loads(r['payload'])} for r in conn.execute(
                text('SELECT sequence,payload FROM assistant_events WHERE owner_id=:owner AND run_id=:run AND sequence>:after ORDER BY sequence LIMIT 200'),
                {'owner': owner, 'run': identifier, 'after': after}).mappings()]


def public_run(run):
    return {**{k: run.get(k) for k in ('id', 'revision', 'sessionId', 'message', 'status', 'connectionId', 'courseId',
        'intent', 'summary', 'facts', 'studyTasks', 'coverage', 'question', 'error', 'actionsUsed', 'createdAt', 'updatedAt', 'usage', 'browserControl')},
        'pendingRequests': [request] if (request := pending_request(run)) else []}


def pending_request(run):
    if run.get('inputRequestState') != 'open' or not run.get('inputRequestId') or not run.get('question'):
        return None
    return {'requestId': run['inputRequestId'], 'taskId': run['id'], 'revision': int(run.get('inputRequestRevision') or 1),
            'question': run['question'], 'required': True, 'inputKind': run.get('inputRequestKind') or 'action', 'state': 'open'}


def public_connection(connection):
    return {k: connection.get(k) for k in ('id', 'revision', 'label', 'origin', 'aliases', 'category', 'platform',
        'executor', 'timezone', 'term', 'preferred', 'cloudLogin', 'approvedOrigins', 'status', 'lastSuccessfulSync', 'deviceId')}
