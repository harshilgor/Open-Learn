"""Checkpointed assistant execution, usable embedded or as a separate worker."""
import argparse
import base64
import json
import logging
import os
import re
import signal
import threading
import time
from datetime import datetime, timezone
from sqlalchemy import text
from fastapi import HTTPException
from .contracts import BrowserAction, EvidenceDecision, ActionDecision, FinishDecision, ClarifyDecision, TaskIntent
from .intent import compile_intent, AssistantModelProvider
from .service import AssistantService
from .store import AssistantStore
from .connections import Connections
from .policy import TERMINAL, WAITING, authorize_action, safe_url
from .evidence import evidence_objects
from ..execution import job_scope, LeaseHeartbeat, failure_policy
from ..identity import assert_owner_active
from ..model_provider import ImageInput, ModelProviderError
from ..workflow_store import WorkflowStore, uid, encoded

KINDS = {'assistant_intent', 'assistant_step', 'assistant_reconcile', 'assistant_summary', 'connection_refresh', 'reminder_dispatch'}
log = logging.getLogger(__name__)


def snapshots_for(repo, run):
    snapshots = []
    for identifier in run.get('snapshots', [])[-5:]:
        try:
            snap = repo.read('browser_snapshots', run['owner_id'], identifier)
            snapshots.append({k:v for k,v in snap.items() if k not in {'owner_id','payload','created_at','expires_at','sha256','connection_id','run_id'}})
        except HTTPException: continue
    return snapshots


def upcoming(store, owner, course_id=None):
    from ..academic_planning import AcademicPlanningService
    svc = AcademicPlanningService(store)
    with store.engine.connect() as conn:
        assert_owner_active(conn, owner)
        if course_id: svc.course(conn, owner, course_id)
        result = []
        for entity in svc.rows(conn, 'academic_entities', owner, course_id):
            fields = entity['facts']
            date = next((fields[key] for key in ('due','date','start') if key in fields), None)
            if not date: continue
            result.append({'entityId': entity['id'], 'courseId': entity['courseId'], 'kind': entity['kind'],
                           'title': fields.get('title', {}).get('value') or 'Academic event', 'date': date.get('value'),
                           'conflict': date.get('conflict', False), 'source': date.get('source'), 'revision': entity['revision']})
        return sorted(result, key=lambda e: (e.get('date') or {}).get('value') or '9999')


class AssistantWorker:
    def __init__(self, store, provider_getter=lambda: None, executor_factory=None):
        self.store = store; self.provider_getter = provider_getter
        self.repo = AssistantStore(store); self.jobs = WorkflowStore(store)
        self.service = AssistantService(store)
        self.executor_factory = executor_factory
        self.object_scan_cursor = None
        self.last_object_scan = 0

    def tick(self, limit=10, kinds=None):
        from .reminders import tick_reminders
        tick_reminders(self.store)
        self.recover()
        ids = self.jobs.ready_ids('interactive', kinds or KINDS, limit)
        for identifier in ids: self.execute(identifier)
        return len(ids)

    def execute(self, identifier):
        job = self.jobs.claim(identifier, lease_seconds=120)
        if not job: return
        heartbeat = LeaseHeartbeat(self.store, job)
        try:
            with job_scope(job):
                if job['kind'] == 'reminder_dispatch':
                    from .reminders import dispatch_push
                    dispatch_push(self.store, job)
                else:
                    self.step(job)
        except Exception as exc:
            code = exc.detail.get('code') if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else None
            if code == 'lease_lost': return
            transport_code, retry = failure_policy(exc)
            if retry and job['attempt_count'] < job['max_attempts']:
                self.jobs.fail(job, transport_code, retryable=True)
            else:
                try:
                    with self.store.transaction() as conn:
                        run = self.repo.run(conn, job['owner_id'], job['target_id'])
                        if run.get('browserControl',{}).get('owner','agent') != 'agent':
                            self.jobs.finish(conn,job,{'status':run['status']}); return
                        if run['status'] not in TERMINAL:
                            status = 'waiting_for_user' if code in {'capability_unavailable', 'course_required', 'ambiguous_course', 'ambiguous_event', 'origin_not_approved', 'action_blocked', 'account_changed', 'stale_reference', 'invalid_evidence'} or isinstance(exc, (ModelProviderError, ValueError)) else 'failed'
                            run = self.repo.update_run(conn, run, status=status, pendingCommand=None, error=code or ('provider_unavailable' if isinstance(exc, ModelProviderError) else 'operation_failed'),
                                                       question=exc.detail.get('message','Review the website connection, then continue.') if isinstance(exc,HTTPException) and isinstance(exc.detail,dict) and status in WAITING else 'Review your browser connection or provider settings, then continue.' if status in WAITING else None)
                            self.repo.event(conn, run, 'task.attention', 'The website task needs attention. Your saved facts are preserved.')
                        self.jobs.finish(conn, job, {'status': run['status']})
                except Exception:
                    self.jobs.fail(job, transport_code, retryable=False)
                if job['kind'] != 'reminder_dispatch': self.close(job['owner_id'], job['target_id'])
        finally:
            heartbeat.close()

    def step(self, job):
        run = self.repo.read('assistant_runs', job['owner_id'], job['target_id'])
        if run.get('runtime_owner') == 'agent_v2':
            return self.finish_job(job)
        if run['status'] in TERMINAL | WAITING:
            return self.finish_job(job)
        if run['pendingCommand']:
            step = self.repo.read('assistant_steps',run['owner_id'],run['pendingCommand'])
            if step['job_id'] != job['id']: return self.finish_job(job)
            # A reclaimed worker lease cannot replay an in-flight interaction.
            with self.store.transaction() as conn:
                fresh = self.repo.run(conn,run['owner_id'],run['id'])
                conn.execute(text("UPDATE assistant_steps SET status='outcome_unknown' WHERE id=:id"), {'id':step['id']})
                run = self.repo.update_run(conn,fresh,pendingCommand=None,reobserve=bool(fresh['snapshots']))
                self.repo.event(conn,run,'browser.recovering','Worker resumed; reading the page before another interaction.')
        provider = self.provider_getter()
        if not run.get('intent'):
            connections = self.repo.list('site_connections', run['owner_id'])
            intent = compile_intent(run['message'], provider, connections, run.get('previousTask'))
            with self.store.transaction() as conn:
                run = self.repo.run(conn, job['owner_id'], run['id'])
                run = self.repo.update_run(conn, run, status='resolving', intent=intent.model_dump(by_alias=True))
                self.repo.event(conn, run, 'task.intent', 'Understood the website task.')
        intent = TaskIntent.model_validate(run['intent'])
        if not intent.handled:
            return self.wait(job, 'waiting_for_user', 'clarification_required', 'Describe the website task you want me to perform, or ask this as a tutoring question.')
        if intent.external_write_requests:
            return self.wait(job, 'waiting_for_user', 'external_write_unsupported', 'This assistant currently reads websites and saves academic information. Use the website directly for submissions, messages, or other external changes.')
        if 'query_saved' in intent.operations:
            facts = upcoming(self.store, run['owner_id'], run.get('courseId'))
            if run.get('previousTask') and re.search(r'\b(those|them|these|remind me)\b',run['message'],re.I):
                entities = {f.get('entityId') for f in run['previousTask'].get('facts',[]) if f.get('entityId')}
                facts = [f for f in facts if f['entityId'] in entities] + [f for f in run['previousTask'].get('facts',[]) if not f.get('entityId')]
            if intent.reminder_requested:
                if any(not f.get('entityId') for f in facts):
                    with self.store.transaction() as conn:
                        fresh = self.repo.run(conn,run['owner_id'],run['id'])
                        self.repo.update_run(conn,fresh,facts=facts)
                    return self.wait(job,'waiting_for_user','save_required','Save these dates before creating reminders. Ask “save those dates,” then enable academic notifications.')
                connection = Connections(self.store).resolve(run['owner_id'],run,intent) or {'id':None,'timezone':'America/Los_Angeles'}
                self.ensure_reminders(run,connection,intent)
            now = datetime.now(timezone.utc).date().isoformat()
            facts = [f for f in facts if not f.get('date',{}).get('value') or f['date']['value'][:10] >= now]
            return self.complete(job, facts=facts, summary='Your saved upcoming academic events are listed below. Dates reflect the last successful source check.')
        connection = Connections(self.store).resolve(run['owner_id'], run, intent)
        if not connection:
            return self.wait(job, 'waiting_for_user', 'connection_required', 'Which website should I use? Connect or select your university portal below.')
        # Hold the connection row only for admission; do not hold DB locks during providers.
        with self.store.transaction() as conn:
            connection = self.repo.row(conn, 'site_connections', run['owner_id'], connection['id'], lock=True)
            run = self.repo.run(conn, run['owner_id'], run['id'])
            others = conn.execute(text("SELECT id FROM assistant_runs WHERE owner_id=:owner AND connection_id=:connection AND id<>:run AND status='running'"),
                                  {'owner': run['owner_id'], 'connection': connection['id'], 'run': run['id']}).first()
            owner_busy = conn.execute(text("SELECT count(*) FROM assistant_runs WHERE owner_id=:owner AND id<>:run AND status='running'"), {'owner':run['owner_id'],'run':run['id']}).scalar()
            if others or owner_busy >= 2:
                run = self.repo.update_run(conn, run, status='waiting_for_device', error='connection_busy', question='Another task is using this browser connection. Continue after it finishes.')
                self.jobs.finish(conn, job, {'status': run['status']}); return
            run = self.repo.update_run(conn, run, connectionId=connection['id'], status='running')
        if run.get('clarificationAnswer'):
            run['message'] += '\nUser clarification: ' + run['clarificationAnswer']
        if run['actionsUsed'] >= run['maxActions'] or len(run['visited']) >= run['maxPages'] or time.time()-run['activeSince'] > 600 or run.get('modelRounds',0) >= 100 or run.get('usage',{}).get('totalTokens',0) >= 100000:
            return self.complete(job, partial=True, summary='Stopped at the task budget. The results below cover only the sources checked so far.')
        if connection['executor'] == 'local' and not connection.get('deviceId'):
            return self.wait(job, 'waiting_for_device', 'device_offline', 'Pair the browser companion for this website, then continue.')
        self.ensure_reminders(run, connection, intent)
        observations = snapshots_for(self.repo, run)
        previous = observations[-1] if observations else None
        action = None
        if run.get('reobserve'):
            action = BrowserAction(tool='observe')
            with self.store.transaction() as conn:
                fresh = self.repo.run(conn, run['owner_id'], run['id'])
                run = self.repo.update_run(conn, fresh, reobserve=False)
        elif not previous:
            action = BrowserAction(tool='read_platform_resource', resource='courses') if connection.get('platform') == 'canvas' else BrowserAction(tool='navigate', url=intent.source_url or connection['origin'])
        else:
            last_action = run.get('lastAction') or {}
            needs_extract = previous['id'] not in run.get('extracted', []) and (last_action.get('resource') in {'syllabus','announcements','modules'} or last_action.get('tool') != 'read_platform_resource')
            if provider and (needs_extract or connection.get('platform') != 'canvas'):
                images = []
                if previous.get('imageObject'):
                    images = [ImageInput(previous.get('imageMime','image/png'), evidence_objects(self.store).read(run['owner_id'], previous['imageObject']), 'Website evidence')]
                decision = AssistantModelProvider(provider).decide({k:run.get(k) for k in ('message','intent','visited','extracted','facts','enrollments','coverage','clarificationAnswer','lastAction','previousTask')}, observations, connection, images)
                with self.store.transaction() as conn:
                    fresh = self.repo.run(conn, run['owner_id'], run['id'])
                    usage = dict(fresh.get('usage', {})); provider_usage = getattr(provider, 'last_usage', None)
                    incomplete_urls = {s['url'] for s in observations[-3:] if sum(len(b['text']) for b in s.get('blocks',[])) > 12000 or any(len(b['text'])>6000 for b in s.get('blocks',[])) or len(s.get('controls',[]))>120}
                    coverage = [{**c,'complete':False,'status':'model_input_truncated'} if c['url'] in incomplete_urls else c for c in fresh['coverage']]
                    if provider_usage:
                        usage['totalTokens'] = usage.get('totalTokens',0) + provider_usage.total_tokens
                        if provider_usage.cost is not None: usage['cost'] = (usage.get('cost') or 0) + provider_usage.cost
                    run = self.repo.update_run(conn, fresh, modelRounds=fresh.get('modelRounds',0)+1, usage=usage, coverage=coverage)
                if isinstance(decision, EvidenceDecision):
                    return self.accept_evidence(job, run, connection, decision.facts, observations)
                if isinstance(decision, ClarifyDecision):
                    return self.wait(job, 'waiting_for_user', 'clarification_required', decision.question)
                if isinstance(decision, ActionDecision): action = decision.action
                elif isinstance(decision, FinishDecision):
                    if connection.get('platform') != 'canvas' or not (run['pendingResources'] or run['frontier']):
                        return self.complete(job, partial=any(not c['complete'] for c in run['coverage']), summary=decision.summary)
                    # A model finish cannot skip unvisited Canvas resources.
                    with self.store.transaction() as conn:
                        fresh = self.repo.run(conn, run['owner_id'], run['id'])
                        run = self.repo.update_run(conn, fresh, extracted=fresh['extracted']+[previous['id']])
            if action is None:
                if run['pendingResources']:
                    action = BrowserAction.model_validate(run['pendingResources'][0])
                    with self.store.transaction() as conn:
                        fresh = self.repo.run(conn, run['owner_id'], run['id'])
                        run = self.repo.update_run(conn, fresh, pendingResources=fresh['pendingResources'][1:])
                elif run['frontier']:
                    target = run['frontier'][0]
                    action = BrowserAction(tool='read_document' if '.pdf' in target.lower() else 'navigate', url=target)
                    with self.store.transaction() as conn:
                        fresh = self.repo.run(conn, run['owner_id'], run['id'])
                        run = self.repo.update_run(conn, fresh, frontier=fresh['frontier'][1:])
                elif not provider:
                    return self.complete(job, partial=True, summary='Read the available structured information. Connect a model provider to interpret unfamiliar pages and syllabus text.')
                else:
                    return self.complete(job, partial=any(not c['complete'] for c in run['coverage']), summary='Finished checking the requested sources. Review the source-backed results below.')
        authorize_action(action, connection, previous)
        return self.dispatch(job, run, connection, action, previous)

    def ensure_reminders(self, run, connection, intent):
        if run.get('reminderPolicyId') or not (run.get('reminderPolicy') or intent.reminder_requested): return
        # A request or explicit structured policy is required; model intent alone cannot expand permission.
        import re
        if not run.get('reminderPolicy') and not re.search(r'\bremind me\b', run['message'], re.I): return
        from .contracts import ReminderPolicyInput
        from .policy import timezone, require_course
        command = ReminderPolicyInput.model_validate(run['reminderPolicy']) if run.get('reminderPolicy') else ReminderPolicyInput(course_id=run.get('courseId'), connection_id=connection['id'], timezone=connection['timezone'])
        if not run.get('reminderPolicy'):
            if run.get('previousTask'):
                command.entity_ids = [f['entityId'] for f in run['previousTask'].get('facts',[]) if f.get('entityId')]
            if 'collect_exam_dates' in intent.operations and 'collect_assignments' not in intent.operations: command.entity_kinds = ['assessment']
            timing = re.search(r'\b(\d{1,3}|one|two|three|four|five|six|seven|an?|a)\s*(minutes?|hours?|days?|weeks?)\s+before\b', run['message'], re.I)
            if timing:
                words = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'a':1,'an':1}
                amount = int(timing[1]) if timing[1].isdigit() else words[timing[1].lower()]
                minutes = amount * (10080 if timing[2].lower().startswith('week') else 1440 if timing[2].lower().startswith('day') else 60 if timing[2].lower().startswith('hour') else 1)
                if minutes > 129600: return self.wait_for_policy(run)
                command.offsets_minutes = [minutes]
        policy_id = 'policy_' + run['id']
        with self.store.transaction() as conn:
            timezone(command.timezone)
            if command.course_id: require_course(conn, run['owner_id'], command.course_id)
            if any(not 0 <= offset <= 129600 for offset in command.offsets_minutes): self.wait_for_policy(run)
            if command.date_only_time and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',command.date_only_time):
                raise HTTPException(422,detail={'code':'action_blocked','message':'Choose a valid 24-hour reminder time.'})
            if command.connection_id: self.repo.row(conn,'site_connections',run['owner_id'],command.connection_id)
            if command.entity_id and not conn.execute(text('SELECT id FROM academic_entities WHERE owner_id=:owner AND id=:id'),{'owner':run['owner_id'],'id':command.entity_id}).first():
                raise HTTPException(404,detail={'code':'not_found','message':'Academic event unavailable.'})
            existing = conn.execute(text('SELECT id FROM reminder_policies WHERE id=:id AND owner_id=:owner'), {'id': policy_id, 'owner': run['owner_id']}).first()
            if not existing:
                conn.execute(text('INSERT INTO reminder_policies(id,owner_id,revision,active,payload) VALUES(:id,:owner,1,true,:payload)'),
                             {'id': policy_id, 'owner': run['owner_id'], 'payload': encoded(command.model_dump(by_alias=True, exclude_none=True))})
                from .reminders import rebuild
                for payload in conn.execute(text('SELECT payload FROM academic_entities WHERE owner_id=:owner'), {'owner':run['owner_id']}).scalars():
                    rebuild(self.store,conn,run['owner_id'],json.loads(payload))
            fresh = self.repo.run(conn, run['owner_id'], run['id'])
            self.repo.update_run(conn, fresh, reminderPolicyId=policy_id)

    def wait_for_policy(self, run):
        raise HTTPException(422, detail={'code':'action_blocked','message':'Choose a reminder offset within 90 days.'})

    def dispatch(self, job, run, connection, action, previous):
        with self.store.transaction() as conn:
            fresh = self.repo.run(conn, run['owner_id'], run['id'])
            if fresh['status'] != 'running': return self.jobs.finish(conn, job, {'status': fresh['status']})
            old = conn.execute(text('SELECT * FROM assistant_steps WHERE run_id=:run AND job_id=:job'), {'run': run['id'], 'job': job['id']}).mappings().first()
            if old and old['status'] not in {'succeeded','failed','cancelled'}:
                # Ambiguous side effects are never blindly replayed after worker loss.
                if action.tool in {'click','fill','press_key'}: action = BrowserAction(tool='observe')
                conn.execute(text("UPDATE assistant_steps SET status='cancelled' WHERE id=:id"), {'id': old['id']})
            identifier = old['id'] if old else uid('browser_command')
            data = {'action': action.model_dump(by_alias=True, exclude_none=True), 'snapshotBasis': previous['documentRevision'] if previous else None}
            conn.execute(text('''INSERT INTO assistant_steps(id,owner_id,run_id,job_id,generation,connection_revision,device_id,status,payload,expires_at,created_at)
                VALUES(:id,:owner,:run,:job,:generation,:revision,:device,'prepared',:payload,:expires,:now)
                ON CONFLICT(run_id,job_id) DO UPDATE SET generation=excluded.generation,connection_revision=excluded.connection_revision,
                    status='prepared',payload=excluded.payload,expires_at=excluded.expires_at,result=NULL'''),
                {'id': identifier, 'owner': run['owner_id'], 'run': run['id'], 'job': job['id'], 'generation': job['lease'],
                 'revision': connection['revision'], 'device': connection.get('deviceId'), 'payload': encoded(data), 'expires': time.time()+120, 'now': time.time()})
            fresh = self.repo.update_run(conn, fresh, actionsUsed=fresh['actionsUsed']+1, pendingCommand=identifier)
            self.repo.event(conn, fresh, 'browser.action', 'Reading ' + safe_url(action.url or (previous or {}).get('url') or connection['origin']) + '.', tool=action.tool)
            if connection['executor'] == 'local':
                self.jobs.finish(conn, job, {'status': 'waiting_for_device', 'commandId': identifier}); return
        if self.executor_factory:
            executor = self.executor_factory(connection)
        elif connection['executor'] == 'public_fetch':
            from .executors.public import PublicExecutor
            executor = PublicExecutor()
        else:
            from .executors.cloud import CloudExecutor
            executor = CloudExecutor(self.store)
        from .control import BrowserControl
        control=BrowserControl(self.store)
        if not control.begin(run['owner_id'],run['id'],identifier):return self.finish_job(job)
        try:
            observation = executor.execute(action, connection, fresh, previous) if connection['executor'] == 'cloud' or self.executor_factory else executor.execute(action, connection, previous)
        finally:
            control.end(run['owner_id'],run['id'],identifier)
        with self.store.transaction() as conn:
            fresh = self.repo.run(conn, run['owner_id'], run['id'])
            if fresh['pendingCommand'] != identifier or fresh['status'] != 'running': return self.jobs.finish(conn, job, {'status': fresh['status']})
            fresh = self.service.accept_observation(conn, fresh, connection, observation, data['action'])
            conn.execute(text("UPDATE assistant_steps SET status='succeeded',result='{}' WHERE id=:id AND generation=:generation"), {'id': identifier, 'generation': job['lease']})
            if fresh['status'] not in WAITING: self.repo.enqueue(conn, fresh)
            self.jobs.finish(conn, job, {'status': fresh['status']})
        if fresh['status'] in WAITING and fresh.get('browserControl',{}).get('owner','agent') == 'agent': self.close(run['owner_id'], run['id'])

    def accept_evidence(self, job, run, connection, candidates, snapshots):
        from .reconciliation import save_candidates
        from .evidence import validate_candidate, source_record
        with self.store.transaction() as conn:
            fresh = self.repo.run(conn, run['owner_id'], run['id'])
            if fresh['intent'].get('save'):
                facts = save_candidates(self.store, conn, fresh, connection, candidates, snapshots)
            else:
                facts = []
                for candidate in candidates:
                    snap = validate_candidate(candidate, snapshots)
                    facts.append({'title': candidate.title, 'kind': candidate.kind, 'date': candidate.date.model_dump(exclude_none=True) if candidate.date else None,
                                  'source': source_record(snap, connection, candidate.quote, candidate.block_ref), 'saved': False})
            existing = {(f.get('entityId'),f['title'],(f.get('date') or {}).get('value')) for f in fresh['facts']}
            facts = fresh['facts'] + [f for f in facts if (f.get('entityId'),f['title'],(f.get('date') or {}).get('value')) not in existing]
            run = self.repo.update_run(conn, fresh, facts=facts, extracted=list(dict.fromkeys(fresh['extracted']+[s['id'] for s in snapshots])))
            self.repo.event(conn, run, 'academic.evidence', 'Saved source-backed academic facts.' if fresh['intent'].get('save') else 'Collected source-backed information.', count=len(candidates))
            self.repo.enqueue(conn, run)
            self.jobs.finish(conn, job, {'status': 'running'})

    def wait(self, job, status, error, question):
        with self.store.transaction() as conn:
            run = self.repo.run(conn, job['owner_id'], job['target_id'])
            run = self.repo.update_run(conn, run, status=status, error=error, question=question)
            self.repo.event(conn, run, 'task.attention', question)
            self.jobs.finish(conn, job, {'status': status})
        self.close(job['owner_id'], job['target_id'])

    def complete(self, job, *, facts=None, summary='', partial=False):
        preliminary = self.repo.read('assistant_runs', job['owner_id'], job['target_id'])
        study_tasks = []
        if 'create_study_tasks' in preliminary.get('intent',{}).get('operations',[]) and re.search(r'\b(create|make|generate|plan)\b.*\b(study tasks?|study plan|study schedule)\b',preliminary['message'],re.I):
            from ..academic_planning import AcademicPlanningService
            svc = AcademicPlanningService(self.store)
            for fact in facts if facts is not None else preliminary['facts']:
                if fact.get('kind') == 'assessment' and fact.get('entityId') and fact.get('courseId'):
                    generated = svc.generate(job['owner_id'],fact['courseId'],fact['entityId'])
                    study_tasks += generated['tasks']
            summary += f' Proposed {len({t["id"] for t in study_tasks})} study activities from existing course evidence.' if study_tasks else ' Add confirmed assessment topics in the course to create targeted study activities.'
        with self.store.transaction() as conn:
            run = self.repo.run(conn, job['owner_id'], job['target_id'])
            # Stored facts and coverage, never model prose, establish the result.
            values = facts if facts is not None else run['facts']
            identifiers = {f['entityId'] for f in values if f.get('entityId')}
            if identifiers:
                entities = {json.loads(row)['id']:json.loads(row) for row in conn.execute(text('SELECT payload FROM academic_entities WHERE owner_id=:owner'), {'owner':run['owner_id']}).scalars()}
                current = []; seen = set()
                for fact in values:
                    identifier = fact.get('entityId')
                    if not identifier: current.append(fact); continue
                    if identifier in seen: continue
                    seen.add(identifier); entity = entities.get(identifier)
                    if not entity: continue
                    date = next((entity['facts'].get(key) for key in ('due','date','start') if entity['facts'].get(key)), {})
                    current.append({**fact,'date':date.get('value'),'source':date.get('source') or fact.get('source'),
                        'revision':entity['revision'],'conflict':date.get('conflict',False)})
                values = current
            if run.get('enrollments'): summary += f" Checked {len(run['enrollments'])} enrolled courses."
            if run.get('intent',{}).get('save'): summary += f" Saved {len(values)} source-backed facts."
            if any(f.get('conflict') for f in values): summary += ' Some sources disagree; review the conflicting dates.'
            if run.get('reminderPolicyId') and any((f.get('date') or {}).get('kind') == 'date_only' for f in values):
                summary += ' Dates without a start time need a reminder time in Settings → Notifications before alerts can be scheduled.'
            run = self.repo.update_run(conn, run, status='completed_partial' if partial else 'completed', facts=values, studyTasks=[{k:t.get(k) for k in ('id','courseId','reason','status','launch')} for t in study_tasks], summary=summary[:5000], pendingCommand=None)
            self.repo.event(conn, run, 'task.completed', 'Website task finished.' if not partial else 'Website task finished with incomplete coverage.')
            if run.get('connectionId'):
                connection = self.repo.row(conn, 'site_connections', run['owner_id'], run['connectionId'])
                connection['lastSuccessfulSync'] = time.time() if not partial else connection.get('lastSuccessfulSync')
                conn.execute(text('UPDATE site_connections SET payload=:payload WHERE id=:id AND owner_id=:owner'), {'payload': encoded(Connections.clean(connection)), 'id': connection['id'], 'owner': run['owner_id']})
            self.jobs.finish(conn, job, {'status': run['status']})
        self.close(job['owner_id'], job['target_id'])

    def finish_job(self, job):
        with self.store.transaction() as conn: self.jobs.finish(conn, job, {'status': 'idle'})

    def close(self, owner, identifier):
        from .executors.cloud import CloudExecutor
        CloudExecutor(self.store).close(owner, identifier)

    def recover(self):
        # Device timeout pauses the logical task without pretending the page was read.
        with self.store.transaction() as conn:
            stranded = conn.execute(text("""SELECT r.id,r.owner_id FROM assistant_runs r WHERE r.runtime_owner='browser_legacy' AND r.status IN ('running','resolving')
                AND NOT EXISTS (SELECT 1 FROM learning_jobs j WHERE j.target_id=r.id AND j.owner_id=r.owner_id AND j.status IN ('queued','running','retry_wait'))
                AND NOT EXISTS (SELECT 1 FROM assistant_steps s WHERE s.run_id=r.id AND s.owner_id=r.owner_id AND s.device_id IS NOT NULL AND s.status IN ('prepared','dispatched'))
                LIMIT 20"""), {'now':time.time()}).mappings().all()
            for item in stranded:
                run = self.repo.run(conn,item['owner_id'],item['id'])
                run = self.repo.update_run(conn,run,status='waiting_for_user',pendingCommand=None,error='outcome_unknown',question='The worker was interrupted. Continue to recheck the website before resuming.')
                self.repo.event(conn,run,'task.attention',run['question'])
            rows = conn.execute(text("SELECT id,owner_id,run_id FROM assistant_steps WHERE status IN ('prepared','dispatched') AND device_id IS NOT NULL AND expires_at<:now LIMIT 20"), {'now': time.time()}).mappings().all()
            for r in rows:
                try: run = self.repo.run(conn, r['owner_id'], r['run_id'])
                except HTTPException: continue
                if run.get('pendingCommand') == r['id'] and run['status'] == 'running':
                    run = self.repo.update_run(conn, run, status='waiting_for_device', pendingCommand=None, error='device_offline', question='The browser companion disconnected. Reopen it and continue.')
                    self.repo.event(conn, run, 'task.attention', run['question'])
                conn.execute(text("UPDATE assistant_steps SET status='outcome_unknown' WHERE id=:id"), {'id': r['id']})
        self.refresh_due()
        self.cleanup()

    def refresh_due(self):
        from .contracts import TaskCreate
        with self.store.transaction() as conn:
            suffix = ' FOR UPDATE SKIP LOCKED' if conn.dialect.name == 'postgresql' else ''
            rows = conn.execute(text('SELECT * FROM connection_refresh_schedules WHERE active=true AND next_due<=:now LIMIT 5' + suffix), {'now': time.time()}).mappings().all()
            schedules = []
            for r in rows:
                payload = json.loads(r['payload'])
                connection = self.repo.row(conn, 'site_connections', r['owner_id'], r['connection_id'])
                if connection['status'] in {'revoked','login_required'}:
                    conn.execute(text('UPDATE connection_refresh_schedules SET active=false WHERE id=:id'), {'id': r['id']}); continue
                self.service.create(r['owner_id'], TaskCreate(message=payload['message'], connection_id=r['connection_id']),
                                    f"refresh:{r['id']}:{int(r['next_due'])}", connection=conn)
                conn.execute(text('UPDATE connection_refresh_schedules SET next_due=:due WHERE id=:id'), {'due': time.time()+payload['intervalHours']*3600, 'id': r['id']})

    def cleanup(self):
        from .executors.cloud import BrowserbaseProvider
        with self.store.engine.connect() as conn:
            sessions = conn.execute(text("SELECT b.id,b.owner_id,b.run_id FROM browser_session_leases b LEFT JOIN assistant_runs r ON r.id=b.run_id WHERE (b.status='login' AND b.expires_at<:now) OR (b.status='active' AND (b.expires_at<:now OR r.id IS NULL OR r.status IN ('completed','completed_partial','cancelled','failed','paused','waiting_for_user','waiting_for_device','waiting_for_login'))) LIMIT 10"), {'now': time.time()}).mappings().all()
            cleanup = conn.execute(text('SELECT * FROM browser_provider_cleanup LIMIT 10')).mappings().all()
            objects = conn.execute(text('SELECT * FROM assistant_objects WHERE expires_at<:now LIMIT 20'), {'now': time.time()}).mappings().all()
        for s in sessions: self.close(s['owner_id'], s['run_id'])
        for item in cleanup:
            try:
                provider = BrowserbaseProvider()
                if item['context_id']: provider.delete_context(item['context_id'])
                if item['session_id']: provider.stop(item['session_id'])
                with self.store.engine.begin() as conn: conn.execute(text('DELETE FROM browser_provider_cleanup WHERE id=:id'), {'id': item['id']})
            except Exception: pass  # Durable cleanup retries without exposing credentials.
        for item in objects:
            evidence_objects(self.store).delete(item['owner_id'], item['object_key'])
            with self.store.engine.begin() as conn: conn.execute(text('DELETE FROM assistant_objects WHERE id=:id'), {'id': item['id']})
        with self.store.engine.begin() as conn:
            conn.execute(text('DELETE FROM browser_snapshots WHERE expires_at<:now'), {'now': time.time()})
        # A rollback after object publication must not strand private image bytes.
        if time.time()-self.last_object_scan >= 300:
            self.last_object_scan = time.time()
            objects = evidence_objects(self.store)
            from ..object_storage import LocalImmutableObjects
            cutoff = time.time()-86400
            if isinstance(objects, LocalImmutableObjects):
                if objects.root.exists():
                    for path in objects.root.glob('*/image_*'):
                        if not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(objects.root) and path.stat().st_mtime < cutoff:
                            path.unlink(missing_ok=True)
            else:
                options = {'Bucket':objects.bucket,'Prefix':objects.prefix+'/','MaxKeys':500}
                if self.object_scan_cursor: options['ContinuationToken']=self.object_scan_cursor
                page = objects.client.list_objects_v2(**options)
                for item in page.get('Contents',[]):
                    if item['LastModified'].timestamp() < cutoff and re.fullmatch(r'assistant/[A-Za-z0-9_.:-]+/image_[A-Za-z0-9_-]+',item['Key']):
                        objects.client.delete_object(Bucket=objects.bucket,Key=item['Key'])
                self.object_scan_cursor = page.get('NextContinuationToken')

    def notifications(self, stop, once=False):
        from .reminders import tick_reminders
        while not stop.is_set():
            try:
                tick_reminders(self.store)
                for identifier in self.jobs.ready_ids('interactive', {'reminder_dispatch'}, 5): self.execute(identifier)
            except Exception as exc: log.warning('Reminder dispatcher iteration failed (%s)',type(exc).__name__)
            if once: return
            stop.wait(2)

    def run(self, stop, once=False, role='all'):
        if role == 'notifications': return self.notifications(stop,once)
        notification_thread = None
        if role == 'all' and not once:
            notification_thread = threading.Thread(target=self.notifications,args=(stop,),daemon=True)
            notification_thread.start()
        while not stop.is_set():
            try: busy = self.tick(3, KINDS - {'reminder_dispatch'} if not once else KINDS)
            except Exception as exc:
                log.warning('Assistant worker iteration failed (%s)', type(exc).__name__); busy = False
            if once: return
            stop.wait(.2 if busy else 2)
        if notification_thread: notification_thread.join(timeout=5)


def main():
    from ..database import database_url
    from ..storage import Store
    from ..model_provider import configured_lesson_provider
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--once', action='store_true')
    parser.add_argument('--role',choices=['all','browser','notifications'],default='all')
    args = parser.parse_args(); stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.set())
    store = Store(database_url())
    try: AssistantWorker(store, configured_lesson_provider).run(stop, args.once, args.role)
    finally: store.close()


if __name__ == '__main__': main()
