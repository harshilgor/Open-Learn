"""Bounded steps, tracked output preparation and fenced restart recovery."""
import argparse
import json
import logging
import threading
import time
from sqlalchemy import text
from fastapi import HTTPException
from ..workflow_store import uid, encoded
from ..execution import LeaseHeartbeat
from .repository import Repository, TERMINAL
from .artifacts import Artifacts
from .tools import analyze

log=logging.getLogger(__name__)


class AgentWorker:
    def __init__(self, store, provider_getter=lambda:None, executor=None, after_storage=None, research_factory=None, sandbox_factory=None):
        self.store=store;self.repo=Repository(store);self.artifacts=Artifacts(store)
        self.provider_getter=provider_getter;self.executor=executor;self.after_storage=after_storage
        self.research_factory=research_factory
        self.sandbox_factory=sandbox_factory

    def enqueue(self, conn, owner, obligation, payload):
        run=self.repo.run(conn,owner,payload['runId'])
        if run['revision']!=payload['revision'] or run['status']!='queued': return
        self.repo.jobs.enqueue(owner,run['id'],'agent_step',payload,'agent-outbox:'+obligation,connection=conn,input_revision=payload['inputRevision'],queue='interactive',max_attempts=3)

    def tick(self, limit=10):
        if time.time()-getattr(self,'_flashcard_maintenance_at',0)>60:
            from ..flashcards.maintenance import FlashcardMaintenance
            FlashcardMaintenance(self.store).tick()
            self._flashcard_maintenance_at=time.time()
        from ..in_class_service import InClassService
        InClassService(self.store,self.provider_getter()).tick(min(limit,4))
        from .delegation import Delegation
        from .connected_actions import ConnectedActions
        Delegation(self.store).tick(limit)
        ConnectedActions(self.store).tick(min(limit,5))
        from .responsibilities import Responsibilities
        Responsibilities(self.store).tick(limit)
        self.repo.outbox.drain({'agent.step':self.enqueue},limit)
        self.cleanup()
        ids=self.repo.jobs.ready_ids('interactive',{'agent_step'},limit)
        for identifier in ids: self.execute(identifier)
        from .learning import LearningContinuation
        LearningContinuation(self.store,self.provider_getter()).tick(limit)
        return len(ids)

    def execute(self, identifier):
        job=self.repo.jobs.claim(identifier,lease_seconds=120)
        if not job:return
        heartbeat=LeaseHeartbeat(self.store,job)
        try: self.advance(job)
        except Exception as exc:
            code=exc.detail.get('code') if isinstance(exc,HTTPException) and isinstance(exc.detail,dict) else None
            if code in {'lease_lost','revision_conflict'}:
                self.retire_stale_outputs(job)
                return
            retry=bool(getattr(exc,'retryable',False))
            if retry and job['attempt_count']<job['max_attempts']:
                self.repo.jobs.fail(job,'provider_unavailable',retryable=True)
            else:
                try:
                    with self.repo.transaction() as conn:
                        run=self.repo.run(conn,job['owner_id'],job['target_id'])
                        self.repo.jobs.validate_lease(conn,job)
                        if run['status'] not in TERMINAL and run['desired_input_revision']==job['input_revision']:
                            run=self.repo.update(conn,run,status='failed',error=getattr(exc,'code',code) or 'operation_failed',summary=str(exc) if isinstance(exc,ValueError) else 'Execution failed. Start a linked new task after checking setup.')
                            self.repo.event(conn,run,'task.failed',reasonCode=run['error'])
                            self.repo.activity(conn,run,'final:'+run['id'],'task.failed',text=run['summary'])
                            self.artifacts.cleanup(conn,run['owner_id'],run['id'])
                        self.repo.jobs.finish(conn,job,{'status':run['status']})
                except HTTPException: pass
                log.warning('Agent operation failed: %s',type(exc).__name__)
        finally: heartbeat.close()

    def advance(self, job):
        with self.repo.transaction() as conn:
            dispatch=self.repo.run(conn,job['owner_id'],job['target_id'])
        if dispatch['kind']=='flashcards':
            from ..flashcards.execution import execute_task
            return execute_task(self,job)
        with self.repo.transaction() as conn:
            run=self.repo.run(conn,job['owner_id'],job['target_id'])
            self.repo.jobs.validate_lease(conn,job)
            from .delegation import Delegation
            Delegation(self.store).guard(conn,job['owner_id'],run)
            if run['status'] in TERMINAL|{'paused','waiting'} or run['desired_input_revision']!=job['input_revision']:
                self.repo.jobs.finish(conn,job,{'ignored':True});return
            if run['kind'] in {'lab_analysis','sandbox_lab'} and not run['constraints'].get('distanceUnit'):
                pending=[r for r in run['pendingRequests']]
                if not pending:
                    identifier=uid('input')
                    request={'requestId':identifier,'taskId':run['id'],'revision':1,'question':'The distance column has no units. Were these measurements in centimeters or meters? You can also tell me which trial to exclude.','required':True,'options':['Centimeters; ignore trial 3','Meters; ignore trial 3'],'inputKind':'text','state':'open'}
                    conn.execute(text("INSERT INTO agent_input_requests(id,owner_id,run_id,session_id,revision,status,payload,created_at) VALUES(:id,:owner,:run,:session,1,'open',:payload,:now)"),{'id':identifier,'owner':run['owner_id'],'run':run['id'],'session':run['sessionId'],'payload':encoded(request),'now':time.time()})
                    pending=[request]
                    self.repo.activity(conn,run,'question:'+identifier,'input.requested',request=request,text=request['question'])
                run=self.repo.update(conn,run,status='waiting',phase='clarify',waitReason='user_input',pendingRequests=pending)
                run=self.repo.checkpoint(conn,run);self.repo.event(conn,run,'input.requested',requests=pending)
                self.repo.jobs.finish(conn,job,{'status':'waiting'});return
            run=self.repo.update(conn,run,status='running',phase='analyze' if run['kind']=='lab_analysis' else 'research',waitReason=None)
            operation=conn.execute(text('SELECT * FROM agent_operations WHERE run_id=:run AND input_revision=:revision AND step_key=:step'),{'run':run['id'],'revision':run['desired_input_revision'],'step':run['kind']}).mappings().first()
            if not operation:
                operation={'id':uid('operation'),'input_revision':run['desired_input_revision']}
                conn.execute(text("INSERT INTO agent_operations(id,owner_id,run_id,input_revision,step_key,status,payload,created_at) VALUES(:id,:owner,:run,:revision,:step,'prepared',:payload,:now)"),{'id':operation['id'],'owner':run['owner_id'],'run':run['id'],'revision':run['desired_input_revision'],'step':run['kind'],'payload':encoded({'toolVersion':'lab-analysis-v1' if run['kind']=='lab_analysis' else 'research-v1','inputHash':run['inputHash']}),'now':time.time()})
            run=self.repo.update(conn,run,operationId=operation['id']);run=self.repo.checkpoint(conn,run)
            self.repo.event(conn,run,'task.phase_changed',phase=run['phase'])
            expected=run['revision']
        def still_current():
            with self.store.engine.connect() as conn:
                current=self.repo.run(conn,job['owner_id'],job['target_id'])
                self.repo.jobs.validate_lease(conn,job)
                if current['revision']!=expected or current['desired_input_revision']!=job['input_revision']: raise HTTPException(409,{'code':'revision_conflict','message':'Inputs changed.'})
        if self.executor: result=self.executor(run,still_current)
        elif run['kind']=='sandbox_lab':
            from .sandbox import SandboxService
            service=self.sandbox_factory(self.store) if self.sandbox_factory else SandboxService(self.store)
            result=service.prepare(run,still_current)
        elif run['kind']=='research':
            from .research import ResearchService
            service=self.research_factory(self.store) if self.research_factory else ResearchService(self.store,model_provider=self.provider_getter())
            result=service.prepare(run['owner_id'],run,run['researchSpec'],still_current)
        else: result=analyze(run)
        still_current()
        with self.repo.transaction() as conn:
            fresh=self.repo.run(conn,run['owner_id'],run['id']);self.repo.jobs.validate_lease(conn,job)
            if fresh['revision']!=expected: raise HTTPException(409,{'code':'revision_conflict','message':'Inputs changed.'})
            manifests=self.artifacts.prepare(conn,fresh,operation,result['outputs'])
        self.artifacts.store_outputs(manifests,result['outputs'])
        if self.after_storage:self.after_storage(run,manifests)
        with self.repo.transaction() as conn:
            fresh=self.repo.run(conn,run['owner_id'],run['id']);self.repo.jobs.validate_lease(conn,job)
            if fresh['revision']!=expected: raise HTTPException(409,{'code':'revision_conflict','message':'Inputs changed.'})
            artifacts=self.artifacts.publish(conn,fresh,operation,manifests)
            completion=result['completion'];checks=completion.get('checks',[])
            if any(check.get('status')=='fail' for check in checks): raise ValueError('Completion validation failed.')
            status='completed_partial' if completion.get('partial') or completion.get('status')=='partial' else 'completed'
            fresh=self.repo.update(conn,fresh,status=status,phase='complete',summary=result['summary'],artifacts=artifacts,sources=result.get('sources',[]),completion=completion,pendingRequests=[])
            fresh=self.repo.checkpoint(conn,fresh)
            conn.execute(text("UPDATE agent_operations SET status='succeeded',payload=:payload WHERE id=:id"),{'id':operation['id'],'payload':encoded({'completion':completion,'artifacts':[a['id'] for a in artifacts]})})
            self.repo.event(conn,fresh,'task.completed',artifacts=artifacts,completion=completion)
            self.repo.activity(conn,fresh,'final:'+fresh['id'],'task.completed',text=result['summary'],artifacts=artifacts,completion=completion)
            self.repo.jobs.finish(conn,job,{'status':status,'taskId':fresh['id']})

    def cleanup(self):
        from .sandbox import SandboxService
        service=self.sandbox_factory(self.store) if self.sandbox_factory else SandboxService(self.store)
        service.cleanup()
        from .research_sources import ResearchSources
        ResearchSources(self.store).purge_expired()
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT id,owner_id,object_key FROM agent_artifacts WHERE status='cleanup_pending' LIMIT 20")).mappings().all()
        for row in rows:
            try:
                self.artifacts.objects.delete(row['owner_id'],row['object_key'])
                with self.repo.transaction() as conn:conn.execute(text("UPDATE agent_artifacts SET status='deleted' WHERE id=:id AND status='cleanup_pending'"),{'id':row['id']})
            except OSError:log.warning('Artifact cleanup needs retry.')

    def retire_stale_outputs(self, job):
        # A cancelled writer may finish an object upload after cleanup. Put its
        # tombstones back on the queue; this cannot delete published versions.
        with self.repo.transaction() as conn:
            row=conn.execute(text('SELECT desired_input_revision,status FROM assistant_runs WHERE id=:id AND owner_id=:owner'),{'id':job['target_id'],'owner':job['owner_id']}).first()
            if row and (row[0]!=job['input_revision'] or row[1]=='cancelled'):
                conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','deleted','cleanup_pending') AND operation_id IN (SELECT id FROM agent_operations WHERE run_id=:run AND input_revision=:revision)"),{'owner':job['owner_id'],'run':job['target_id'],'revision':job['input_revision']})
        self.cleanup()

    def run(self, stop):
        while not stop.is_set():
            try:self.tick()
            except Exception:log.exception('Agent worker tick failed')
            stop.wait(.5)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    from ..database import database_url
    from ..storage import Store
    store=Store(database_url())
    try:
        from ..model_provider import configured_lesson_provider
        provider=configured_lesson_provider()
        worker=AgentWorker(store,provider_getter=lambda:provider)
        if args.once:worker.tick()
        else:worker.run(threading.Event())
    finally:store.close()


if __name__=='__main__':main()
