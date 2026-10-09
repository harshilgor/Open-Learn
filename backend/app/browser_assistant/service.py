import json
import re
import secrets
import time
from contextlib import nullcontext
from sqlalchemy import text
from .contracts import TaskCreate, TaskCommand, BrowserResult, ConnectionCreate
from .connections import Connections
from .store import AssistantStore, pending_request, public_run
from .policy import TERMINAL, WAITING, checksum, require_course
from .evidence import retain_snapshot
from ..identity import fail, assert_owner_active, current_principal
from ..workflow_store import uid, encoded


class AssistantService:
    def __init__(self, store):
        self.store = store
        self.repo = AssistantStore(store)
        self.connections = Connections(store)

    def create(self, owner, command: TaskCreate, key=None, connection=None):
        data = command.model_dump(by_alias=True, exclude_none=True)
        key = key or uid('command')
        if len(key) > 200: fail('invalid_input', 'Command key is too long.', 422)
        digest = checksum(encoded(data))
        with (nullcontext(connection) if connection is not None else self.store.transaction()) as conn:
            assert_owner_active(conn, owner)
            if command.session_id:
                if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id': command.session_id, 'owner': owner}).first():
                    fail('not_found', 'Conversation unavailable.', 404)
            if command.course_id:
                require_course(conn, owner, command.course_id)
            previous = None
            if command.previous_task_id:
                previous = self.repo.run(conn, owner, command.previous_task_id)
                if not command.session_id or previous.get('sessionId') != command.session_id:
                    fail('not_found', 'That website task belongs to another conversation.', 404)
            if command.connection_id:
                connection = self.repo.row(conn, 'site_connections', owner, command.connection_id)
                if connection['status'] == 'revoked': fail('connection_revoked', 'Reconnect this website.', 409)
            existing = conn.execute(text('SELECT id,request_hash FROM assistant_runs WHERE owner_id=:owner AND command_key=:key'), {'owner': owner, 'key': key}).mappings().first()
            if existing:
                if existing['request_hash'] != digest: fail('idempotency_conflict', 'That command key has different input.', 409)
                return public_run(self.repo.run(conn, owner, existing['id']))
            outstanding = conn.execute(text("SELECT count(*) FROM assistant_runs WHERE owner_id=:owner AND status IN ('queued','resolving','running')"), {'owner':owner}).scalar()
            if outstanding >= 20: fail('task_limit','Finish or stop existing website tasks before starting more.',429)
            now = time.time()
            run = {**data, 'id': uid('assistant'), 'owner_id': owner, 'revision': 1, 'status': 'queued',
                   'connectionId': command.connection_id, 'courseId': command.course_id, 'sessionId': command.session_id,
                   'intent': None, 'summary': None, 'facts': [], 'coverage': [], 'snapshots': [], 'visited': [],
                   'pendingResources': [], 'frontier': [], 'enrollments': [], 'actionsUsed': 0, 'modelRounds': 0,
                   'extracted': [], 'pendingCommand': None, 'createdAt': now, 'updatedAt': now,
                   'activeSince': now, 'usage': {'totalTokens': 0, 'cost': None}, 'error': None, 'question': None}
            if previous:
                run['previousTask'] = {k:previous.get(k) for k in ('id','message','intent','connectionId','courseId','facts','summary')}
                run['connectionId'] = command.connection_id or previous.get('connectionId')
                run['courseId'] = command.course_id or previous.get('courseId')
            conn.execute(text('''INSERT INTO assistant_runs(id,owner_id,revision,connection_id,session_id,command_key,request_hash,status,payload,created_at,updated_at)
                VALUES(:id,:owner,1,:connection,:session,:key,:hash,'queued',:payload,:now,:now)'''),
                {'id': run['id'], 'owner': owner, 'connection': run['connectionId'], 'session': command.session_id,
                 'key': key, 'hash': digest, 'payload': encoded({k:v for k,v in run.items() if k != 'owner_id'}), 'now': now})
            self.repo.event(conn, run, 'task.created', 'Preparing your website task.')
            self.repo.enqueue(conn, run, 'assistant_intent')
        return public_run(run)

    def command(self, owner, identifier, command: TaskCommand):
        if command.action in {'takeover','return_control'}:
            from .control import BrowserControl
            return BrowserControl(self.store).command(owner, identifier, command)
        with self.store.transaction() as conn:
            run = self.repo.run(conn, owner, identifier)
            if run.get('runtime_owner') == 'agent_v2': fail('invalid_input', 'Use the versioned execution command contract.', 422)
            if run['revision'] != command.expected_revision: fail('revision_conflict', 'The task changed. Refresh before continuing.', 409)
            if run['status'] in TERMINAL: return public_run(run)
            if command.action in {'resume', 'resolve'} and run['status'] in WAITING:
                request = pending_request(run)
                if request and (not command.reply_to_request_id or command.reply_to_request_id != request['requestId']
                                or command.expected_request_revision != request['revision']):
                    fail('revision_conflict', 'This website question changed. Refresh it before continuing.', 409)
            if command.action in {'resume','resolve'} and run.get('browserControl',{}).get('owner','agent') != 'agent':
                fail('control_not_ready','Return browser control before continuing automation.',409)
            if command.action in {'cancel', 'pause'}:
                run = self.repo.update_run(conn, run, status='cancelled' if command.action == 'cancel' else 'paused', pendingCommand=None)
                conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,cancel_requested=true,lease=NULL,expires=NULL WHERE owner_id=:owner AND target_id=:run AND status IN ('queued','retry_wait','running')"), {'owner': owner, 'run': identifier})
                conn.execute(text("UPDATE assistant_steps SET status='cancelled' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','dispatched')"), {'owner': owner, 'run': identifier})
            else:
                changes = {'status': 'queued', 'error': None, 'question': None, 'pendingCommand': None, 'activeSince': time.time()}
                if command.connection_id:
                    connection = self.repo.row(conn, 'site_connections', owner, command.connection_id)
                    if connection['status'] == 'revoked': fail('connection_revoked', 'Reconnect this website.', 409)
                    changes['connectionId'] = command.connection_id
                    if command.connection_id != run.get('connectionId'):
                        changes.update(snapshots=[],lastSnapshot=None,visited=[],pendingResources=[],frontier=[],enrollments=[],extracted=[],coverage=[])
                if command.answer:
                    changes['clarificationAnswer'] = command.answer
                if command.course_id:
                    require_course(conn, owner, command.course_id)
                    changes['courseId'] = command.course_id
                if run.get('error') in {'device_offline','stale_reference','outcome_unknown'} and run.get('snapshots'):
                    changes['reobserve'] = True
                run = self.repo.update_run(conn, run, **changes)
                conn.execute(text("UPDATE assistant_steps SET status='cancelled' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','dispatched')"), {'owner': owner, 'run': identifier})
                self.repo.enqueue(conn, run, 'assistant_step' if run.get('intent') else 'assistant_intent')
            self.repo.event(conn, run, 'task.' + command.action, 'Website task stopped.' if command.action == 'cancel' else 'Website task ' + command.action + 'd.')
        if command.action in {'cancel', 'pause'}:
            from .executors.cloud import CloudExecutor
            CloudExecutor(self.store).close(owner, identifier)
        return public_run(run)

    def resolve_conversation_input(self, conn, owner: str, task_id: str, request_id: str,
                                   expected_task_revision: int, expected_request_revision: int,
                                   answer: str, message_id: str):
        """Answer one open browser clarification inside the shared admission transaction."""
        normalized = re.sub(r'\s+', ' ', str(answer or '')).strip()
        if not normalized:
            fail('invalid_input', 'Enter an answer before continuing.', 422)
        if len(normalized) > 4000:
            fail('invalid_input', 'Keep the answer under 4,000 characters.', 422)
        if not message_id:
            fail('invalid_input', 'A stable message identity is required to answer this question.', 422)

        run = self.repo.run(conn, owner, task_id)
        if run.get('runtime_owner') == 'agent_v2':
            fail('not_found', 'Website task unavailable.', 404)
        answer_digest = checksum(normalized)
        if run.get('lastResolvedInputMessageId') == message_id:
            if run.get('lastResolvedInputDigest') != answer_digest:
                fail('idempotency_conflict', 'That message identity has different answer text.', 409)
            return public_run(run)
        if run.get('revision') != expected_task_revision:
            fail('revision_conflict', 'The website task changed. Refresh the current question before answering.', 409)
        request = pending_request(run)
        if run.get('inputRequestId') != request_id:
            fail('not_found', 'Website question unavailable.', 404)
        if (run.get('status') != 'waiting_for_user' or not request
                or request['revision'] != expected_request_revision):
            fail('revision_conflict', 'This website question is no longer open. Refresh the task before replying.', 409)
        if request['inputKind'] != 'text':
            fail('invalid_state', 'Use the website task controls to complete this step.', 409)

        prior_error = run.get('error')
        changes = {'status': 'queued', 'error': None, 'question': None, 'pendingCommand': None,
                   'activeSince': time.time(), 'clarificationAnswer': normalized,
                   'inputRequestState': 'answered', 'lastResolvedInputMessageId': message_id,
                   'lastResolvedInputDigest': answer_digest}
        if prior_error == 'connection_required':
            # Re-run intent extraction with the learner's destination so a URL
            # supplied in chat is validated and resolved by the ordinary path.
            changes['intent'] = None
            changes['reclassifyWithClarification'] = True
        if prior_error in {'course_required', 'ambiguous_course'}:
            name = re.sub(r'\s+', ' ', normalized).strip().casefold()
            matches = conn.execute(text('SELECT id,name FROM courses WHERE owner_id=:owner AND archived_at IS NULL'),
                                   {'owner': owner}).mappings().all()
            selected = [item for item in matches if re.sub(r'\s+', ' ', item['name']).strip().casefold() == name]
            if len(selected) == 1:
                changes['courseId'] = selected[0]['id']
        run = self.repo.update_run(conn, run, **changes)
        self.repo.event(conn, run, 'task.input_answered', 'Thanks — continuing with your answer.',
                        replyToRequestId=request_id, requestRevision=expected_request_revision,
                        inputRequestState='answered')
        self.repo.enqueue(conn, run, 'assistant_intent' if not run.get('intent') else 'assistant_step')
        return public_run(run)

    def poll(self, principal):
        if principal.kind != 'browser' or not principal.device_id: fail('device_scope_denied', 'Use a paired browser device.', 403)
        with self.store.transaction() as conn:
            rows = conn.execute(text('''SELECT s.* FROM assistant_steps s JOIN assistant_runs r ON r.id=s.run_id AND r.owner_id=s.owner_id
                JOIN site_connections c ON c.id=r.connection_id AND c.owner_id=r.owner_id
                WHERE s.owner_id=:owner AND s.device_id=:device AND s.status IN ('prepared','dispatched')
                AND s.expires_at>:now AND r.status IN ('running','waiting_for_device') AND c.status<>'revoked'
                AND c.revision=s.connection_revision ORDER BY s.created_at LIMIT 4'''),
                {'owner': principal.owner_id, 'device': principal.device_id, 'now': time.time()}).mappings().all()
            result = []
            for row in rows:
                run = self.repo.run(conn, principal.owner_id, row['run_id'])
                if run.get('pendingCommand') != row['id']: continue
                connection = self.repo.row(conn, 'site_connections', principal.owner_id, run['connectionId'])
                conn.execute(text("UPDATE assistant_steps SET status='dispatched' WHERE id=:id AND owner_id=:owner"), {'id': row['id'], 'owner': principal.owner_id})
                result.append({'id': row['id'], 'taskId': run['id'], 'generation': row['generation'],
                               'connectionRevision': row['connection_revision'], 'deadline': row['expires_at'],
                               'origin': connection['origin'], 'approvedOrigins': connection.get('approvedOrigins', []),
                               'accountId': connection.get('accountId'), **json.loads(row['payload'])})
            active = conn.execute(text("SELECT r.id FROM assistant_runs r JOIN site_connections c ON c.id=r.connection_id AND c.owner_id=r.owner_id WHERE r.owner_id=:owner AND c.device_id=:device AND r.status NOT IN ('completed','completed_partial','cancelled','failed')"), {'owner': principal.owner_id, 'device': principal.device_id}).scalars().all()
            handoffs=[]
            for identifier in active:
                run=self.repo.run(conn,principal.owner_id,identifier)
                control=run.get('browserControl',{})
                if control.get('owner')=='requesting':
                    handoffs.append({'taskId':identifier,'generation':control['generation']})
        return {'commands': result, 'activeTaskIds': active, 'handoffs':handoffs}

    def acknowledge(self, principal, identifier, result: BrowserResult):
        with self.store.transaction() as conn:
            step = self.repo.row(conn, 'assistant_steps', principal.owner_id, identifier, lock=True)
            if principal.kind != 'browser' or step['device_id'] != principal.device_id:
                fail('device_scope_denied', 'This command belongs to another browser.', 403)
            digest = checksum(result.model_dump_json(by_alias=True))
            if step['status'] == 'succeeded':
                if json.loads(step['result']).get('hash') != digest: fail('idempotency_conflict', 'The command already has a different result.', 409)
                return {'status': 'accepted', 'duplicate': True}
            run = self.repo.run(conn, principal.owner_id, step['run_id'])
            connection = self.repo.row(conn, 'site_connections', principal.owner_id, run['connectionId'], lock=True)
            if step['status'] not in {'prepared','dispatched'} or run.get('pendingCommand') != identifier or run['status'] not in {'running','waiting_for_device'}:
                fail('stale_command', 'This command is no longer active.', 409)
            if step['expires_at'] <= time.time() or result.generation != step['generation'] or result.connection_revision != connection['revision']:
                fail('stale_command', 'This command expired or lost its connection scope.', 409)
            if connection['status'] == 'revoked': fail('connection_revoked', 'Connection revoked.', 403)
            if result.error:
                waiting = 'waiting_for_login' if result.error == 'login_required' else 'waiting_for_device' if result.error in {'device_offline','tab_closed'} else 'waiting_for_user'
                run = self.repo.update_run(conn, run, status=waiting, error=result.error, pendingCommand=None,
                    question='Sign in to the connected website, then continue.' if waiting == 'waiting_for_login' else 'Review the browser connection and continue when ready.')
            elif result.document:
                from .policy import check_url
                from .adapters.documents import document_observation
                import base64
                check_url(result.document.url, connection)
                try: data = base64.b64decode(result.document.document_bytes, validate=True)
                except ValueError: fail('invalid_input', 'Invalid document encoding.', 422)
                observation = document_observation(result.document.url, data, result.document.content_type)
                run = self.accept_observation(conn, run, connection, observation, step['action'])
            elif result.observation:
                if result.observation.document_text and not result.observation.blocks:
                    from .contracts import TextBlock
                    result.observation.blocks = [TextBlock(ref='b0', text=result.observation.document_text[:20000])]
                run = self.accept_observation(conn, run, connection, result.observation, step['action'])
            else:
                fail('invalid_input', 'A browser result requires an observation or error.', 422)
            conn.execute(text("UPDATE assistant_steps SET status='succeeded',result=:result WHERE id=:id AND owner_id=:owner"),
                         {'result': encoded({'hash': digest}), 'id': identifier, 'owner': principal.owner_id})
            self.repo.event(conn, run, 'browser.observed', 'Read the next website page.' if not result.error else run['question'])
            if run['status'] not in WAITING: self.repo.enqueue(conn, run)
        return {'status': 'accepted'}

    def accept_observation(self, conn, run, connection, observation, action):
        if observation.status in {'login_required', 'account_changed', 'tab_closed'}:
            status = 'waiting_for_login' if observation.status == 'login_required' else 'waiting_for_user'
            return self.repo.update_run(conn, run, status=status, pendingCommand=None, error=observation.status,
                                        question='Sign in or reconnect the correct account, then continue.')
        if observation.account_id:
            if connection.get('accountId') and connection['accountId'] != observation.account_id:
                return self.repo.update_run(conn, run, status='waiting_for_user', pendingCommand=None, error='account_changed', question='The university account changed. Reconnect it before continuing.')
            if not connection.get('accountId'):
                connection['accountId'] = observation.account_id
                conn.execute(text('UPDATE site_connections SET payload=:payload WHERE id=:id AND owner_id=:owner'),
                             {'payload': encoded(Connections.clean(connection)), 'id': connection['id'], 'owner': run['owner_id']})
        snapshot = retain_snapshot(self.store, conn, run, connection, observation)
        snapshots = list(run.get('snapshots', [])) + [snapshot['id']]
        visited = list(dict.fromkeys(run.get('visited', []) + [observation.url]))
        coverage = list(run.get('coverage', []))
        resource_key = (action.get('resource') or action['tool']) + ':' + str(action.get('externalCourseId') or observation.url)
        branch = {'key': resource_key, 'complete': observation.complete and not observation.truncated, 'status': observation.status, 'url': observation.url}
        coverage = [c for c in coverage if c['key'] != resource_key] + [branch]
        conn.execute(text('''INSERT INTO academic_scan_coverage(id,owner_id,run_id,course_id,resource_key,complete,payload)
            VALUES(:id,:owner,:run,:course,:key,:complete,:payload) ON CONFLICT(run_id,resource_key) DO UPDATE SET complete=excluded.complete,payload=excluded.payload'''),
            {'id': uid('coverage'), 'owner': run['owner_id'], 'run': run['id'], 'course': run.get('courseId'),
             'key': resource_key[:240], 'complete': branch['complete'], 'payload': encoded(branch)})
        resources = list(run.get('pendingResources', []))
        enrollments = list(run.get('enrollments', []))
        facts = list(run.get('facts', []))
        frontier = list(run.get('frontier', []))
        if action['tool'] == 'read_platform_resource':
            from .adapters.canvas import discover, platform_candidates
            from .contracts import BrowserAction
            if action.get('resource') == 'courses':
                courses, tasks = discover(conn, run, connection, snapshot)
                enrollments += [c for c in courses if c['externalId'] not in {e['externalId'] for e in enrollments}]
                resources += tasks
            else:
                from .reconciliation import save_candidates
                candidates = platform_candidates(snapshot, BrowserAction.model_validate(action))
                if run['intent'].get('save'):
                    facts += save_candidates(self.store, conn, run, connection, candidates, [snapshot])
                else:
                    from .evidence import validate_candidate, source_record
                    for candidate in candidates:
                        validate_candidate(candidate, [snapshot])
                        facts.append({'title': candidate.title, 'kind': candidate.kind,
                            'date': candidate.date.model_dump(exclude_none=True) if candidate.date else None,
                            'source': source_record(snapshot, connection, candidate.quote, candidate.block_ref), 'saved': False})
            if observation.next_cursor:
                resources.insert(0, {**action, 'cursor': observation.next_cursor})
            # Course materials are useful even when structured endpoints were already read.
            for control in snapshot.get('controls', []):
                if control.get('href') and control['href'] not in visited and control['href'] not in frontier:
                    try:
                        from .policy import check_url
                        check_url(control['href'], connection); frontier.append(control['href'])
                    except Exception: branch['blockedLink'] = True
        return self.repo.update_run(conn, run, status='running', pendingCommand=None, error=None,
            snapshots=snapshots[-100:], lastSnapshot=snapshot['id'], visited=visited, coverage=coverage,
            pendingResources=resources, enrollments=enrollments, facts=facts[-300:], frontier=frontier[-100:], lastAction=action)
