"""Academic facts, evidence reports and explainable feasible planning.

Academic observations are immutable; user overrides win until explicitly
withdrawn. Task completion is administrative and never manufactures mastery.
"""
from __future__ import annotations
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import text
from .identity import assert_owner_active
from .unified_learner_state import UnifiedLearnerState

TABLES = {'academic_entities', 'academic_observations', 'readiness_snapshots', 'study_tasks', 'study_plan_revisions', 'canvas_connections', 'canvas_sync_runs'}


class AcademicError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.status = code, status


def moment(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise AcademicError('timezone_required', 'Use an explicit timezone for scheduling instants.')
    return parsed.astimezone(timezone.utc).timestamp()


class AcademicPlanningService:
    def __init__(self, store):
        self.store = store

    def rows(self, conn, table, owner, course=None):
        assert table in TABLES
        assert_owner_active(conn, owner)
        query = f'SELECT payload FROM {table} WHERE owner_id=:owner'
        if course is not None:
            query += ' AND course_id=:course'
        return [json.loads(p) for p in conn.execute(text(query + ' ORDER BY created_at,id'), {'owner': owner, 'course': course}).scalars()]

    def put(self, conn, table, owner, payload, *, expected=None):
        assert table in TABLES
        assert_owner_active(conn, owner)
        old = conn.execute(text(f'SELECT revision,payload FROM {table} WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': payload['id']}).first()
        if expected is not None and (old[0] if old else 0) != expected:
            raise AcademicError('revision_conflict', 'This item changed. Refresh before saving.', 409)
        payload = dict(payload, revision=(old[0] + 1 if old else 1))
        values = {'owner': owner, 'id': payload['id'], 'course': payload.get('courseId'), 'revision': payload['revision'], 'payload': json.dumps(payload), 'now': time.time()}
        if old:
            conn.execute(text(f'UPDATE {table} SET payload=:payload,revision=:revision WHERE owner_id=:owner AND id=:id'), values)
        else:
            conn.execute(text(f'INSERT INTO {table}(owner_id,id,course_id,revision,payload,created_at) VALUES(:owner,:id,:course,:revision,:payload,:now)'), values)
        return payload

    def course(self, conn, owner, course):
        if not conn.execute(text('SELECT id FROM courses WHERE id=:id AND owner_id=:owner AND archived_at IS NULL'), {'id': course, 'owner': owner}).first():
            raise AcademicError('course_not_found', 'Course unavailable.', 404)

    def ingest(self, owner, course, command):
        with self.store.transaction() as conn:
            self.course(conn, owner, course)
            kind = command['kind']
            if kind not in {'assignment', 'assessment', 'term', 'coverage'}:
                raise AcademicError('invalid_entity_kind', 'Unsupported academic entity.')
            external = command.get('externalId')
            identity = external or command.get('entityId')
            if not identity:
                identity = uuid4().hex
            entity_id = command.get('entityId') or hashlib.sha256(f'{course}:{command.get("origin", "manual")}:{kind}:{identity}'.encode()).hexdigest()[:32]
            entities = self.rows(conn, 'academic_entities', owner, course)
            if command.get('entityId') and not any(e['id'] == entity_id and e['kind'] == kind for e in entities):
                raise AcademicError('entity_not_found', 'Academic entity unavailable.', 404)
            entity = next((e for e in entities if e['id'] == entity_id), {'id': entity_id, 'courseId': course, 'kind': kind, 'externalId': external, 'facts': {}})
            observations = self.rows(conn, 'academic_observations', owner, course)
            for field, value in command.get('fields', {}).items():
                if field not in {'title', 'instructions', 'due', 'availability', 'scope', 'weight', 'format', 'completed', 'covered', 'date'}:
                    raise AcademicError('invalid_fact', 'Unsupported academic field.')
                if field in {'due', 'date'} and value is not None:
                    if not isinstance(value, dict) or value.get('kind') not in {'instant', 'date_only', 'timezone_unknown', 'unknown'}:
                        raise AcademicError('invalid_date', 'Dates must preserve their precision and timezone.')
                    if value['kind'] == 'instant': moment(value['value'])
                    if value['kind'] == 'date_only': datetime.strptime(value['value'], '%Y-%m-%d')
                source = command.get('source', {})
                if not source.get('locator') or not source.get('revision'):
                    raise AcademicError('source_required', 'A source locator and revision are required.')
                origin_key = command.get('idempotencyKey', uuid4().hex)
                oid = hashlib.sha256(f'{entity_id}:{field}:{origin_key}'.encode()).hexdigest()
                duplicate = next((o for o in observations if o['id'] == oid), None)
                obs = {'id': oid, 'courseId': course, 'entityId': entity_id, 'field': field, 'value': value, 'source': source, 'observedAt': command.get('observedAt', datetime.now(timezone.utc).isoformat()), 'confirmation': command.get('confirmation', 'confirmed'), 'origin': command.get('origin', 'manual'), 'override': bool(command.get('override')), 'reason': command.get('reason'), 'negated': bool(command.get('negated'))}
                if duplicate:
                    if duplicate['value'] != value: raise AcademicError('idempotency_conflict', 'The import key already contains another value.', 409)
                else:
                    observations.append(self.put(conn, 'academic_observations', owner, obs))
                candidates = [o for o in observations if o['entityId'] == entity_id and o['field'] == field and not o['negated']]
                overrides = [o for o in candidates if o['override']]
                student_dates = [o for o in candidates if o['origin'] == 'canvas' and o['source'].get('studentSpecific') and field == 'due']
                selected = sorted(overrides or student_dates or candidates, key=lambda o: (o['observedAt'], o['id']))[-1] if candidates else None
                distinct = {json.dumps(o['value'], sort_keys=True) for o in candidates}
                entity['facts'][field] = {'value': selected['value'] if selected else None, 'observationId': selected['id'] if selected else None, 'source': selected['source'] if selected else None, 'conflict': len(distinct) > 1 and not (overrides or student_dates), 'alternatives': [o['id'] for o in candidates], 'rationale': 'deliberate_user_override' if overrides else 'authenticated_student_date' if student_dates else 'provisional_latest_observation' if len(distinct) > 1 else 'consistent_observations'}
            return self.put(conn, 'academic_entities', owner, entity)

    def view(self, owner, course):
        with self.store.engine.connect() as conn:
            self.course(conn, owner, course)
            return {name: self.rows(conn, table, owner, course) for name, table in [('entities', 'academic_entities'), ('observations', 'academic_observations'), ('tasks', 'study_tasks'), ('plans', 'study_plan_revisions')]}

    def readiness(self, owner, course, assessment_id):
        from .context_compiler import ContextCompiler
        compiler=ContextCompiler(self.store)
        context=compiler.compile(owner,None,'readiness','Evidence for assessment '+assessment_id,course_id=course)
        with self.store.transaction() as conn:
            compiler.validate_commit(conn,owner,context)
            self.course(conn, owner, course)
            assessment = next((e for e in self.rows(conn, 'academic_entities', owner, course) if e['id'] == assessment_id and e['kind'] == 'assessment'), None)
            if not assessment: raise AcademicError('assessment_not_found', 'Assessment unavailable.', 404)
            scope_fact = assessment['facts'].get('scope', {})
            scope = scope_fact.get('value') or {'confirmed': [], 'probable': [], 'unknown': True}
            if not isinstance(scope, dict): raise AcademicError('invalid_scope', 'Assessment scope must distinguish confirmed and probable concepts.')
            projections = UnifiedLearnerState(self.store).read(conn, owner)['states']
            by_key = {(p['conceptId'], p['capability']): p for p in projections}
            report = []
            for certainty in ('confirmed', 'probable'):
                for item in scope.get(certainty, []):
                    concept = item['conceptId']
                    capability = item.get('capability', 'recall')
                    state = by_key.get((concept, capability), {})
                    category = 'untested'
                    if state:
                        category = 'strong' if state.get('state') == 'demonstrated' else 'developing' if state.get('independentSuccessIds') or state.get('independentFailureIds') else 'assisted_only' if state.get('assistedEventIds') else 'untested'
                        if state.get('evidenceStrength') == 'conflicting': category = 'conflicting'
                        if state.get('retention') in {'review_due', 'stale'} and category != 'untested': category = 'stale'
                    report.append({'conceptId': concept, 'capability': capability, 'scopeCertainty': certainty, 'category': category, 'evidence': state, 'diagnostic': category in {'untested', 'stale', 'conflicting', 'assisted_only'}})
            payload = {'id': uuid4().hex, 'courseId': course, 'assessmentId': assessment_id, 'assessmentRevision': assessment['revision'], 'eventWatermark': max((p.get('eventWatermark', 0) for p in projections), default=0), 'scopeBasis': scope_fact, 'unknownScope': scope.get('unknown', True) or scope_fact.get('conflict', False), 'capabilities': report, 'createdAt': datetime.now(timezone.utc).isoformat(), 'meaning': 'Evidence for supplied topics; no grade prediction.'}
            payload.update(contextId=context['id'],contextManifest=context['manifest'],contextDependencies=context['dependencies'],contextWarnings=context['warnings'])
            return self.put(conn, 'readiness_snapshots', owner, payload)

    def generate(self, owner, course, assessment_id):
        snapshot = self.readiness(owner, course, assessment_id)
        created = []
        strong = {(t['conceptId'], t['capability']) for t in snapshot['capabilities'] if t['category'] == 'strong'}
        with self.store.transaction() as conn:
            for task in self.rows(conn, 'study_tasks', owner, course):
                if task.get('assessmentId') == assessment_id and task['action'] != 'assignment' and task['status'] in {'proposed', 'accepted', 'scheduled'} and not task.get('pinned') and all((c, task.get('capability', 'recall')) in strong for c in task.get('conceptIds', [])):
                    task.update(status='cancelled', cancellationReason='Updated independent evidence makes this practice redundant.', invalidatingSnapshot=snapshot['id'])
                    self.put(conn, 'study_tasks', owner, task)
        for target in snapshot['capabilities']:
            if target['category'] == 'strong': continue
            action = 'retrieval' if target['category'] == 'stale' else 'repair' if target['category'] == 'developing' and target['evidence'].get('independentFailureIds') else 'diagnostic'
            key = hashlib.sha256(f'{assessment_id}:{snapshot["assessmentRevision"]}:{target["conceptId"]}:{target["capability"]}:{action}'.encode()).hexdigest()[:32]
            created.append(self.create_task(owner, course, {'id': key, 'action': action, 'conceptIds': [target['conceptId']], 'capability': target['capability'], 'reason': f'{target["category"].replace("_", " ")} evidence for {target["capability"]}; {target["scopeCertainty"]} assessment scope.', 'sourceBasis': [snapshot['scopeBasis']], 'duration': [8, 12], 'assessmentId': assessment_id, 'credibleGap': bool(target['evidence'].get('independentFailureIds'))}))
        with self.store.engine.connect() as conn:
            assignments=[e for e in self.rows(conn,'academic_entities',owner,course) if e['kind']=='assignment' and not e['facts'].get('completed',{}).get('value')]
        for entity in assignments:
            created.append(self.create_task(owner,course,{'id':'assignment_'+entity['id'],'action':'assignment','entityId':entity['id'],'reason':'Work toward '+str(entity['facts'].get('title',{}).get('value','the assignment')),'duration':[20,45],'due':entity['facts'].get('due',{}).get('value'),'sourceBasis':[entity['facts'].get('due',{})],'durationBasis':'initial_estimate_needs_student_confirmation'}))
        return {'snapshot': snapshot, 'tasks': created}

    def create_task(self, owner, course, command):
        actions = {'diagnostic': 'quiz', 'retrieval': 'quiz', 'repair': 'learn', 'transfer': 'quiz', 'assignment': 'assignment'}
        action = command['action']
        if action not in actions: raise AcademicError('invalid_action', 'Unsupported study activity.')
        duration = command.get('duration', [8, 15])
        if len(duration) != 2 or not 1 <= duration[0] <= duration[1] <= 480: raise AcademicError('invalid_duration', 'Specify a duration range of 1–480 minutes.')
        if not command.get('conceptIds') and action != 'assignment': raise AcademicError('scope_required', 'A learning activity needs target concepts.')
        if action == 'assignment' and not command.get('entityId'): raise AcademicError('assignment_required', 'Select the assignment.')
        with self.store.transaction() as conn:
            self.course(conn, owner, course)
            entities = self.rows(conn, 'academic_entities', owner, course)
            if action == 'assignment' and not any(e['id'] == command.get('entityId') and e['kind'] == 'assignment' for e in entities):
                raise AcademicError('assignment_not_found', 'Select an assignment from this course.', 404)
            known_tasks = {t['id'] for t in self.rows(conn, 'study_tasks', owner, course)}
            if set(command.get('prerequisites', [])) - known_tasks: raise AcademicError('prerequisite_not_found', 'Prerequisite activities must belong to this course.')
            task = dict(command, id=command.get('id') or uuid4().hex, courseId=course, status='proposed', duration=duration, launch={'workflow': actions[action], 'courseId': course, 'conceptIds': command.get('conceptIds', []), 'capability': command.get('capability', 'recall'), 'entityId': command.get('entityId')}, completionCriterion='explicit_assignment_completion' if action == 'assignment' else 'workflow_finished_with_followup_evidence', policyRevision='task-v1', pinned=False)
            existing = next((t for t in self.rows(conn, 'study_tasks', owner, course) if t['id'] == task['id']), None)
            if existing: return existing
            return self.put(conn, 'study_tasks', owner, task)

    def task_action(self, owner, course, task_id, command):
        with self.store.transaction() as conn:
            self.course(conn, owner, course)
            task = next((t for t in self.rows(conn, 'study_tasks', owner, course) if t['id'] == task_id), None)
            if not task: raise AcademicError('task_not_found', 'Task unavailable.', 404)
            status = command.get('status', task['status'])
            allowed = {'proposed': {'accepted', 'skipped', 'cancelled'}, 'accepted': {'scheduled', 'active', 'skipped', 'cancelled'}, 'scheduled': {'active', 'skipped', 'cancelled'}, 'active': {'completed', 'skipped'}, 'blocked': {'accepted', 'cancelled'}}
            if status != task['status'] and status not in allowed.get(task['status'], set()): raise AcademicError('invalid_transition', 'This task cannot enter that state.', 409)
            if status == 'completed' and task['action'] != 'assignment' and not command.get('workflowId'): raise AcademicError('outcome_required', 'Provide the completed workflow reference.')
            if status == 'completed' and task['action'] != 'assignment':
                workflow = conn.execute(text('SELECT kind,payload FROM practice_records WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': command['workflowId']}).first()
                if not workflow: raise AcademicError('workflow_not_found', 'Completed workflow unavailable.', 404)
                result = json.loads(workflow[1])
                if workflow[0] == 'quiz':
                    if result.get('status') != 'completed' or not set(task.get('conceptIds', [])) <= set(result.get('conceptIds', [])):
                        raise AcademicError('workflow_incomplete', 'Finish a quiz covering this activity scope.', 409)
                elif workflow[0] == 'journey':
                    if not result.get('turns') or any(t.get('status') != 'completed' for t in result['turns']):
                        raise AcademicError('workflow_incomplete', 'Finish this learning journey.', 409)
                else: raise AcademicError('workflow_incomplete', 'Unsupported activity outcome.', 409)
                for identifier in command.get('evidenceIds', []):
                    if not conn.execute(text('SELECT 1 FROM learning_event_ledger WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': identifier}).first():
                        raise AcademicError('evidence_not_found', 'Activity evidence unavailable.', 404)
            task.update(status=status, pinned=command.get('pinned', task.get('pinned', False)), cooldownUntil=time.time() + 86400 if status == 'skipped' else task.get('cooldownUntil',0))
            if status=='completed': task['outcome']={'workflowId':command.get('workflowId'),'evidenceIds':command.get('evidenceIds',[]),'administrativeOnly':task['action']=='assignment'}
            return self.put(conn, 'study_tasks', owner, task, expected=command.get('revision'))

    def advice(self, owner, course, available_minutes=60, for_planning=False):
        with self.store.engine.connect() as conn:
            self.course(conn, owner, course)
            tasks = self.rows(conn, 'study_tasks', owner, course)
        eligible, blocked = [], []
        completed = {t['id'] for t in tasks if t['status'] == 'completed'}
        for task in tasks:
            if task['status'] not in {'proposed', 'accepted', 'scheduled'} or task.get('cooldownUntil', 0) > time.time(): continue
            failures = []
            if task['duration'][0] > available_minutes: failures.append('insufficient_time')
            unfinished = set(task.get('prerequisites', [])) - completed
            if unfinished and not (for_planning and unfinished <= {t['id'] for t in tasks if t['status'] in {'proposed','accepted','scheduled','active'}}): failures.append('prerequisite_task')
            if task.get('sourceUnavailable'): failures.append('restore_source')
            due = task.get('due')
            urgency = 0
            if due and due.get('kind') == 'instant':
                hours = (moment(due['value']) - time.time()) / 3600
                if hours < 0: failures.append('deadline_passed')
                urgency = max(0, min(5, 5 - hours / 24))
            if failures:
                blocked.append(dict(task, blockedReasons=failures)); continue
            terms = {'urgency': urgency, 'importance': min(3, max(0, task.get('importance', 1))), 'diagnostic': 2 if task['action'] == 'diagnostic' else 0, 'retention': 2 if task['action'] == 'retrieval' else 0, 'supportedGap': 2 if task.get('credibleGap') else 0, 'effort': -min(2, task['duration'][1] / 120)}
            eligible.append(dict(task, priority=sum(terms.values()), contributions=terms, unknownImportance='importance' not in task))
        return {'eligible': sorted(eligible, key=lambda t: (-t['priority'], t['id'])), 'blocked': blocked, 'policyRevision': 'advice-v1'}

    def plan(self, owner, course, command):
        from .context_compiler import ContextCompiler
        compiler=ContextCompiler(self.store)
        context=compiler.compile(owner,None,'planning','Feasible course study plan',course_id=course)
        ZoneInfo(command['timezone'])
        windows = sorted([(moment(w['start']), moment(w['end'])) for w in command['windows']])
        if any(end <= start for start, end in windows): raise AcademicError('invalid_window', 'Study windows must have positive duration.')
        if any(windows[i][1] > windows[i+1][0] for i in range(len(windows)-1)): raise AcademicError('overlapping_windows', 'Study windows must not overlap.')
        protected = [(moment(w['start']), moment(w['end'])) for w in command.get('protected', [])]
        for ps, pe in protected:
            next_windows = []
            for start, end in windows:
                if pe <= start or ps >= end: next_windows.append((start, end)); continue
                if start < ps: next_windows.append((start, ps))
                if pe < end: next_windows.append((pe, end))
            windows = next_windows
        advice = self.advice(owner, course, 480, for_planning=True)
        with self.store.transaction() as conn:
            compiler.validate_commit(conn,owner,context)
            previous = self.rows(conn, 'study_plan_revisions', owner, course)
            tasks = self.rows(conn, 'study_tasks', owner, course)
            applied = [p for p in previous if p.get('status') == 'applied']
            old = applied[-1] if applied else {'blocks': []}
            locked = {t['id'] for t in tasks if t.get('pinned') or t['status'] == 'active'}
            blocks = [b for b in old['blocks'] if b['taskId'] in locked]
            occupied = [(b['start'], b['end']) for b in blocks]
            failures = []
            pending = list(advice['eligible'])
            queue = []
            resolved = {t['id'] for t in tasks if t['status'] == 'completed'} | {b['taskId'] for b in blocks}
            while pending:
                ready = [t for t in pending if set(t.get('prerequisites', [])) <= resolved]
                if not ready:
                    failures.extend({'taskId':t['id'],'minutes':t['duration'][1],'reason':'prerequisite_cycle_or_unavailable'} for t in pending)
                    break
                for task in ready:
                    queue.append(task); pending.remove(task); resolved.add(task['id'])
            finishes = {t['id']: 0 for t in tasks if t['status'] == 'completed'}
            finishes.update({b['taskId']: b['end'] for b in blocks})
            for task in queue:
                if task['id'] in locked: continue
                if set(task.get('prerequisites', [])) - finishes.keys():
                    failures.append({'taskId':task['id'],'minutes':task['duration'][1],'reason':'prerequisite_could_not_fit'}); continue
                length = task['duration'][1] * 60
                placed = False
                for start, end in windows:
                    cursor = max(start, max((finishes[p] for p in task.get('prerequisites', [])), default=0))
                    for os, oe in sorted(occupied):
                        if oe <= cursor: continue
                        if cursor + length <= os: break
                        if os < cursor + length: cursor = max(cursor, oe + 300)
                    due = task.get('due')
                    limit = min(end, moment(due['value'])) if due and due.get('kind') == 'instant' else end
                    if due and due.get('kind')=='date_only':
                        # Unknown due time never becomes an invented late-night
                        # deadline. Fit before that date, and explain uncertainty.
                        conservative = datetime.fromisoformat(due['value']).replace(tzinfo=ZoneInfo(command['timezone'])).timestamp()
                        limit=min(limit,conservative)
                    if cursor + length + 300 <= limit:
                        blocks.append({'taskId': task['id'], 'start': cursor, 'end': cursor+length, 'reason': task.get('reason', task['action'])})
                        occupied.append((cursor, cursor+length+300)); placed = True; break
                if placed: finishes[task['id']] = cursor+length
                elif task['action']=='assignment':
                    remaining=length
                    for start,end in windows:
                        cursor=max(start,max((finishes[p] for p in task.get('prerequisites',[])),default=0))
                        limit=end
                        due=task.get('due')
                        if due and due.get('kind')=='instant':limit=min(limit,moment(due['value']))
                        if due and due.get('kind')=='date_only':limit=min(limit,datetime.fromisoformat(due['value']).replace(tzinfo=ZoneInfo(command['timezone'])).timestamp())
                        free=[]
                        for os,oe in sorted(occupied):
                            if oe<=cursor:continue
                            if os>cursor:free.append((cursor,min(os,limit)))
                            cursor=max(cursor,oe+300)
                            if cursor>=limit:break
                        if cursor<limit:free.append((cursor,limit))
                        for left,right in free:
                            duration=min(remaining,1800,int(right-left-300))
                            if duration<min(remaining,task['duration'][0]*60):continue
                            blocks.append({'taskId':task['id'],'start':left,'end':left+duration,'reason':task['reason'],'deliverable':task.get('entityId'),'partialAssignmentBlock':True})
                            occupied.append((left,left+duration+300));remaining-=duration
                            if not remaining:finishes[task['id']]=left+duration;placed=True;break
                        if placed:break
                    if remaining:failures.append({'taskId':task['id'],'minutes':remaining/60,'reason':'assignment_capacity_gap','alternatives':['Add availability','Move unpinned work','Confirm the due time']})
                    continue
                if not placed: failures.append({'taskId': task['id'], 'minutes': task['duration'][1], 'reason': 'capacity_gap', 'alternatives': ['Add a study window', 'Shorten optional practice', 'Move unpinned work']})
            payload = {'id': uuid4().hex, 'courseId': course, 'timezone': command['timezone'], 'blocks': blocks, 'capacityGaps': failures, 'blockedTasks': advice['blocked'], 'basedOn': old.get('id'), 'status': 'applied' if command.get('autoAdjust', False) else 'proposed', 'difference': {'preserved': list(locked), 'added': [b['taskId'] for b in blocks if b not in old['blocks']], 'removed': [b['taskId'] for b in old['blocks'] if b not in blocks]}, 'reason': command.get('reason', 'Availability or study evidence changed.'), 'createdAt': datetime.now(timezone.utc).isoformat()}
            payload.update(contextId=context['id'],contextManifest=context['manifest'],contextDependencies=context['dependencies'],contextWarnings=context['warnings'])
            return self.put(conn, 'study_plan_revisions', owner, payload)

    def accept_plan(self, owner, course, plan_id, revision):
        with self.store.transaction() as conn:
            self.course(conn, owner, course)
            plans = self.rows(conn, 'study_plan_revisions', owner, course)
            plan = next((p for p in plans if p['id'] == plan_id), None)
            if not plan: raise AcademicError('plan_not_found', 'Plan unavailable.', 404)
            applied = [p for p in plans if p['status'] == 'applied' and p['id'] != plan_id]
            if (applied[-1]['id'] if applied else None) != plan.get('basedOn'):
                raise AcademicError('plan_stale', 'Your accepted schedule changed. Create a fresh proposal.', 409)
            tasks = {t['id']: t for t in self.rows(conn, 'study_tasks', owner, course)}
            for block in plan['blocks']:
                task = tasks.get(block['taskId'])
                if not task or task['status'] in {'completed', 'skipped', 'cancelled'}: raise AcademicError('plan_stale', 'An activity changed. Create a fresh proposal.', 409)
                if task['status'] in {'proposed', 'accepted'}:
                    task['status'] = 'scheduled'; self.put(conn, 'study_tasks', owner, task)
            return self.put(conn, 'study_plan_revisions', owner, dict(plan, status='applied'), expected=revision)
