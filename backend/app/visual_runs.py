"""Owned visual child jobs on the existing fenced, durable execution queue."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from sqlalchemy import text

from .identity import fail
from .material_service import MaterialService
from .workflow_store import WorkflowStore, uid
from .openintelligentui import GeneratedVisual, generate


class VisualRuns:
    def __init__(self, store):
        self.store, self.records = store, WorkflowStore(store)

    def admit(self, conn, owner, session_id, lesson_id, prepared, question, key):
        """Called in the same transaction that commits the tutor lesson."""
        existing = conn.execute(text("SELECT target_id FROM learning_jobs WHERE owner_id=:owner AND command_key=:key"),
                                {"owner": owner, "key": key}).scalar_one_or_none()
        if existing:
            return self.records.read(owner, existing, 'visual_run', conn)
        run_id = uid('visualrun')
        brief = {'title': str(prepared.get('title', 'Interactive explanation'))[:160],
                 'sources': prepared.get('sources', [])[:4], 'visualType': prepared.get('visualType', 'auto')}
        # Do not persist a full generation context, provider payload, or credentials.
        brief['sources'] = [{'spanId': s.get('spanId'), 'title': str(s.get('title', ''))[:160],
                            'text': str(s.get('text', ''))[:1600]} for s in brief['sources']]
        from .visual_context import visual_grounding
        brief.update(visual_grounding(conn,self.records,owner,session_id,lesson_id))
        data = {'id': run_id, 'sessionId': session_id, 'lessonId': lesson_id, 'phase': 'queued',
                'question': question[:4000], 'brief': brief, 'snapshots': [], 'artifactRefs': [],
                'createdAt': time.time()}
        job = self.records.enqueue(owner, run_id, 'visual_generate', {}, key,
                                   connection=conn, max_attempts=2)
        data['jobId'] = job['id']
        self.records.put(conn, owner, 'visual_run', data, lesson_id)
        return data

    def read(self, owner, run_id, conn=None):
        value = self.records.read(owner, run_id, 'visual_run', conn)
        MaterialService(self.store).session(owner, value['sessionId'])
        return value

    def listing(self, owner, lesson_id):
        artifact = self.store.get_artifact(lesson_id)
        if artifact is None:
            fail('not_found', 'This lesson is unavailable.', 404)
        MaterialService(self.store).session(owner, artifact.session_id)
        result = []
        for value in self.records.listing_by_parent(owner, 'visual_run', lesson_id):
            job = self.records.job(owner, value['jobId'])
            phase = value['phase']
            if job['status'] == 'failed' and phase not in {'completed', 'skipped', 'cancelled', 'superseded'}:
                phase = 'interrupted' if job['safe_error_code'] == 'attempts_exhausted' else 'failed'
            if job['status'] in {'cancelled', 'cancel_requested'}:
                phase = 'cancelled'
            result.append({k: v for k, v in value.items() if k not in {'brief', 'question'}} | {'phase': phase})
        return sorted(result, key=lambda value: value['createdAt'])

    def update(self, job, **changes):
        with self.store.transaction() as conn:
            self.records.validate_lease(conn, job)
            value = self.records.read(job['owner_id'], job['target_id'], 'visual_run', conn)
            self.records.put(conn, job['owner_id'], 'visual_run', value | changes, value['lessonId'], expected=value['revision'])

    def commit(self, conn, job, values):
        from .session_models import LessonArtifact, LessonPart
        owner = job['owner_id']
        run = self.records.read(owner, job['target_id'], 'visual_run', conn)
        row = conn.execute(text('SELECT payload FROM lesson_artifacts WHERE id=:id'), {'id': run['lessonId']}).first()
        if not row:
            fail('not_found', 'The target lesson is unavailable.', 404)
        artifact = LessonArtifact.model_validate_json(row[0])
        MaterialService(self.store).session(owner, artifact.session_id)
        references = []
        for index, value in enumerate(values):
            visual = GeneratedVisual.model_validate(value)
            visual.id = 'visual_' + hashlib.sha256(f"{run['id']}:{index}".encode()).hexdigest()[:24]
            visual.source_lesson_id = artifact.id
            spec = visual.model_dump(mode='json', by_alias=True)
            record = {'id': visual.id, 'lessonId': artifact.id, 'sessionId': artifact.session_id, 'spec': spec, 'runId': run['id']}
            self.records.put(conn, owner, 'generated_visual', record, artifact.id)
            revision_id = f'{visual.id}_revision_1'
            self.records.put(conn, owner, 'visual_revision', record | {'id': revision_id}, visual.id)
            ref = {'version': 2, 'type': 'generated_ui_ref', 'id': visual.id, 'revision': 1,
                   'title': visual.title, 'sourceLessonId': artifact.id, 'runId': run['id'],
                   'blockIndex': visual.block_index, 'afterParagraph': visual.after_paragraph}
            references.append(ref)
            block = artifact.blocks[min(visual.block_index, len(artifact.blocks) - 1)]
            if len(block.visualizations) >= 4:
                fail('visual_limit', 'This lesson already has enough visuals.', 422)
            block.visualizations.append(ref)
            # Existing explicit text/visual parts must include the late artifact.
            if block.parts:
                block.parts = [*block.parts, LessonPart(kind='visualization', visualization_id=visual.id)]
        conn.execute(text('UPDATE lesson_artifacts SET payload=:payload WHERE id=:id'),
                     {'payload': artifact.model_dump_json(), 'id': artifact.id})
        # Read the latest journey inside the commit; never overwrite newer turns.
        journey_id = 'journey_' + artifact.session_id
        exists = conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner'),
                              {'id': journey_id, 'owner': owner}).first()
        if exists:
            journey = self.records.read(owner, journey_id, 'journey', conn)
            for turn in journey.get('turns', []):
                if (turn.get('lesson') or {}).get('id') == artifact.id:
                    turn['lesson'] = artifact.model_dump(mode='json', by_alias=True)
            self.records.put(conn, owner, 'journey', journey, artifact.session_id, expected=journey['revision'])
        self.records.put(conn, owner, 'visual_run', run | {'phase': 'completed' if references else 'skipped',
            'snapshots': [], 'candidates': [], 'artifactRefs': references}, artifact.id, expected=run['revision'])
        return {'visualRunId': run['id'], 'lessonId': artifact.id, 'artifactRefs': references}

    def change(self, owner, lesson_id, visual_id, change):
        """Persist a typed control revision, never arbitrary replacement code."""
        from .session_models import LessonArtifact
        with self.store.transaction() as conn:
            record = self.records.read(owner, visual_id, 'generated_visual', conn)
            MaterialService(self.store).session(owner, record['sessionId'])
            if record['lessonId'] != lesson_id:
                fail('not_found', 'This visual is unavailable.', 404)
            spec = GeneratedVisual.model_validate(record['spec'])
            if spec.revision != change.expected_revision:
                fail('revision_conflict', 'The visual changed. Reload before editing.', 409)
            if spec.revision >= 500:
                fail('visual_revision_limit', 'Start a new visual to continue exploring.', 422)
            control = next((value for value in spec.controls if value.id == change.parameter_id), None)
            if change.operation != 'change_parameter' or not control:
                fail('unsupported_visual_operation', 'This visual does not expose that numeric control.', 422)
            if not control.minimum <= change.value <= control.maximum:
                fail('parameter_out_of_range', 'That value is outside the visual range.', 422)
            spec.revision += 1
            spec.control_values = {**spec.control_values, control.id: change.value}
            record['spec'] = spec.model_dump(mode='json', by_alias=True)
            self.records.put(conn, owner, 'generated_visual', record, lesson_id, expected=record['revision'])
            self.records.put(conn, owner, 'visual_revision', {'id': f'{visual_id}_revision_{spec.revision}',
                'visualId':visual_id,'sessionId':record['sessionId'],'lessonId':lesson_id,
                'spec':{'revision':spec.revision,'title':spec.title,'controlValues':spec.control_values},'baseRevision':1}, visual_id)
            row = conn.execute(text('SELECT payload FROM lesson_artifacts WHERE id=:id'), {'id':lesson_id}).first()
            artifact = LessonArtifact.model_validate_json(row[0])
            for block in artifact.blocks:
                for value in block.visualizations:
                    if value.get('id') == visual_id:
                        value['revision'] = spec.revision
            conn.execute(text('UPDATE lesson_artifacts SET payload=:payload WHERE id=:id'), {'id':lesson_id,'payload':artifact.model_dump_json()})
            journey_id = 'journey_' + artifact.session_id
            if conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner'), {'id':journey_id,'owner':owner}).first():
                journey = self.records.read(owner, journey_id, 'journey', conn)
                for turn in journey.get('turns', []):
                    if (turn.get('lesson') or {}).get('id') == lesson_id:
                        turn['lesson'] = artifact.model_dump(mode='json', by_alias=True)
                self.records.put(conn, owner, 'journey', journey, artifact.session_id, expected=journey['revision'])
            return spec

    def retry(self, owner, run_id, key):
        run = self.read(owner, run_id)
        job = self.records.job(owner, run['jobId'])
        if job['status'] != 'failed':
            fail('visual_retry_unavailable', 'Only failed visual runs can be retried.', 409)
        with self.store.transaction() as conn:
            retried = self.admit(conn, owner, run['sessionId'], run['lessonId'], run['brief'], run['question'], key)
            latest = self.records.read(owner, run_id, 'visual_run', conn)
            if latest['phase'] != 'superseded':
                self.records.put(conn, owner, 'visual_run', latest | {'phase': 'superseded'}, run['lessonId'], expected=latest['revision'])
            return retried

    def cancel(self, owner, run_id):
        run = self.read(owner, run_id)
        self.records.cancel(owner, run['jobId'])
        return {'id': run_id, 'phase': 'cancelled'}


from .usage.context import usage_job

@usage_job
def run_visual_job(store, provider, job_id):
    from .execution import LeaseHeartbeat, job_scope
    records, service = WorkflowStore(store), VisualRuns(store)
    job = records.claim(job_id, lease_seconds=240)
    if not job:
        return
    heartbeat = LeaseHeartbeat(store, job)
    try:
        with job_scope(job):
            run = service.read(job['owner_id'], job['target_id'])
            # Crash after the provider result: finish the saved candidate without billing again.
            if run['phase'] == 'generated':
                values = run.get('candidates', [])
            elif job['attempt_count'] > 1:
                fail('visual_interrupted', 'The visual was interrupted. Retry to start a new accounted attempt.', 409)
            else:
                service.update(job, phase='running', snapshots=[])
                async def collect():
                    async def emit(value):
                        service.update(job, snapshots=[value.model_dump(mode='json', by_alias=True)])
                    async def emit_plan(value):
                        service.update(job,plan=value)
                    return await generate(job['owner_id'], job_id, run['brief'] | {'_visualLease': job['lease']}, run['question'], emit,emit_plan)
                values = [value.model_dump(mode='json', by_alias=True) for value in asyncio.run(collect())]
                service.update(job, phase='generated', candidates=values, snapshots=[])
            with store.transaction() as conn:
                records.validate_lease(conn, job)
                result = service.commit(conn, job, values)
                records.finish(conn, job, result)
    except Exception as exc:
        import logging
        safe_code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('visual_') and len(str(exc)) < 80 else type(exc).__name__
        logging.getLogger(__name__).warning('Visual child job failed (%s)', safe_code)
        try:
            service.update(job, phase='failed', snapshots=[],errorCode=safe_code.split(':',1)[0])
            records.fail(job, 'visual_interrupted' if job['attempt_count'] > 1 else 'visual_unavailable', retryable=False)
        except Exception:
            pass  # Lost/cancelled leases cannot publish artifacts or another outcome.
    finally:
        heartbeat.close()
