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
from .tools import analyze, analyze_general
from .kernel import AgentKernel, CallToolDecision, CompletionEvaluator, DecisionLimits, DecisionState, KernelError, ToolRegistry, ToolResult, ToolSpec
from pydantic import BaseModel, ConfigDict, Field

log=logging.getLogger(__name__)


class TaskToolInput(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    task_id: str = Field(alias='taskId', min_length=1, max_length=160)
    input_revision: int = Field(alias='inputRevision', ge=1)
    operation_id: str = Field(alias='operationId', min_length=1, max_length=160)


class AgentWorker:
    def __init__(self, store, provider_getter=lambda:None, executor=None, after_storage=None, research_factory=None, sandbox_factory=None):
        self.store=store;self.repo=Repository(store);self.artifacts=Artifacts(store)
        self.provider_getter=provider_getter;self.executor=executor;self.after_storage=after_storage
        self.research_factory=research_factory
        self.sandbox_factory=sandbox_factory
        self.decision_limits=DecisionLimits(
            max_decisions=int(__import__('os').getenv('OPENLEARN_AGENT_MAX_DECISIONS','16')),
            max_tool_calls=int(__import__('os').getenv('OPENLEARN_AGENT_MAX_TOOL_CALLS','8')),
            max_repeated_no_progress=int(__import__('os').getenv('OPENLEARN_AGENT_MAX_NO_PROGRESS','2')),
        )

    def enqueue(self, conn, owner, obligation, payload):
        run=self.repo.run(conn,owner,payload['runId'])
        if run['revision']!=payload['revision'] or run['status']!='queued': return
        self.repo.jobs.enqueue(owner,run['id'],'agent_step',payload,'agent-outbox:'+obligation,connection=conn,input_revision=payload['inputRevision'],queue='interactive',max_attempts=3)

    def tick(self, limit=10):
        if time.time()-getattr(self,'_flashcard_maintenance_at',0)>60:
            from ..flashcards.maintenance import FlashcardMaintenance
            FlashcardMaintenance(self.store).tick()
            self._flashcard_maintenance_at=time.time()
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
        from ..usage.context import usage_scope
        try:
            with self.repo.transaction() as conn:run=self.repo.run(conn,job['owner_id'],job['target_id'])
            with usage_scope(self.store,job['owner_id'],run.get('usageRootId') or job['target_id']):
                self.advance(job)
        except Exception as exc:
            code=exc.detail.get('code') if isinstance(exc,HTTPException) and isinstance(exc.detail,dict) else None
            if code in {'lease_lost','revision_conflict'}:
                self.retire_stale_outputs(job)
                return
            if code in {'usage_task_cap_exhausted','usage_task_window_changed','usage_window_exhausted'}:
                try:
                    with self.repo.transaction() as conn:
                        run=self.repo.run(conn,job['owner_id'],job['target_id'])
                        self.repo.jobs.validate_lease(conn,job)
                        if run['status'] not in TERMINAL and run['desired_input_revision']==job['input_revision']:
                            message=('This task reached its accepted usage maximum.' if code=='usage_task_cap_exhausted' else 'This task stopped at the allowance limit or refresh.')+' Your saved work is available; continue in a linked task with a new maximum.'
                            run=self.repo.update(conn,run,status='completed_partial',error=code,summary=message)
                            self.repo.event(conn,run,'task.completed_partial',reasonCode=code)
                            self.repo.activity(conn,run,'final:'+run['id'],'task.completed_partial',text=message)
                        self.repo.jobs.finish(conn,job,{'status':run['status'],'reasonCode':code})
                except HTTPException:pass
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
        if dispatch['kind']=='calendar_read':
            from .calendar_tasks import resolve_calendar_task_inputs
            from .google_connector import GoogleConnections
            connections=GoogleConnections(self.store).list(job['owner_id'])
            with self.repo.transaction() as conn:
                current=self.repo.run(conn,job['owner_id'],job['target_id'])
                self.repo.jobs.validate_lease(conn,job)
                from .delegation import Delegation
                Delegation(self.store).guard(conn,job['owner_id'],current)
                if current['status'] in TERMINAL|{'paused','waiting'} or current['desired_input_revision']!=job['input_revision']:
                    self.repo.jobs.finish(conn,job,{'ignored':True});return
                spec,question=resolve_calendar_task_inputs(self.store,current,connections)
                if question:
                    if spec is not None and spec!=current.get('calendarRead'):
                        from .repository import digest
                        current=self.repo.update(conn,current,calendarRead=spec,
                            inputHash=digest({'message':current['message'],'calendarRead':spec}))
                        current=self.repo.checkpoint(conn,current)
                    self.repo.request_input(conn,current,question,phase='clarify')
                    self.repo.jobs.finish(conn,job,{'status':'waiting'});return
                from .repository import digest
                current=self.repo.update(conn,current,calendarRead=spec,
                    inputHash=digest({'message':current['message'],'calendarRead':spec}))
                current=self.repo.checkpoint(conn,current)
                dispatch=current
        with self.repo.transaction() as conn:
            run=self.repo.run(conn,job['owner_id'],job['target_id'])
            self.repo.jobs.validate_lease(conn,job)
            from .delegation import Delegation
            Delegation(self.store).guard(conn,job['owner_id'],run)
            if run['status'] in TERMINAL|{'paused','waiting'} or run['desired_input_revision']!=job['input_revision']:
                self.repo.jobs.finish(conn,job,{'ignored':True});return
            if run['kind'] in {'lab_analysis','sandbox_lab'} and run.get('analysisMode')!='general' and not run['constraints'].get('distanceUnit'):
                decision={'kind':'ask_user','question':'The distance column has no units. Were these measurements in centimeters or meters? You can also tell me which trial to exclude.','required':True,'options':['Centimeters; ignore trial 3','Meters; ignore trial 3']}
                self.repo.request_input(conn,run,decision,phase='clarify')
                self.repo.jobs.finish(conn,job,{'status':'waiting'});return
            phase={'lab_analysis':'analyze','research':'research','calendar_read':'read_calendar'}.get(run['kind'],'research')
            run=self.repo.update(conn,run,status='running',phase=phase,waitReason=None)
            operation=conn.execute(text('SELECT * FROM agent_operations WHERE run_id=:run AND input_revision=:revision AND step_key=:step'),{'run':run['id'],'revision':run['desired_input_revision'],'step':run['kind']}).mappings().first()
            if not operation:
                operation={'id':uid('operation'),'input_revision':run['desired_input_revision']}
                tool_version={'lab_analysis':'lab-analysis-general-v1' if run.get('analysisMode')=='general' else 'lab-analysis-v1',
                              'sandbox_lab':'daytona-lab-v1','research':'research-v1',
                              'calendar_read':'google-calendar-read-v1'}.get(run['kind'],'agent-tool-v1')
                conn.execute(text("INSERT INTO agent_operations(id,owner_id,run_id,input_revision,step_key,status,payload,created_at) VALUES(:id,:owner,:run,:revision,:step,'prepared',:payload,:now)"),{'id':operation['id'],'owner':run['owner_id'],'run':run['id'],'revision':run['desired_input_revision'],'step':run['kind'],'payload':encoded({'toolVersion':tool_version,'inputHash':run['inputHash']}),'now':time.time()})
            run=self.repo.update(conn,run,operationId=operation['id']);run=self.repo.checkpoint(conn,run)
            self.repo.event(conn,run,'task.phase_changed',phase=run['phase'])
            expected=run['revision']
        execution_context = None
        if run['kind'] == 'research':
            from .execution_context import ExecutionContextService
            context_service = ExecutionContextService(self.store)
            execution_context = context_service.compile_or_load(run)
            if run.get('executionContext') != execution_context['descriptor']:
                with self.repo.transaction() as conn:
                    fresh = self.repo.run(conn, run['owner_id'], run['id'])
                    self.repo.jobs.validate_lease(conn, job)
                    if fresh['revision'] != expected or fresh['desired_input_revision'] != job['input_revision']:
                        raise HTTPException(409, {'code':'revision_conflict','message':'Inputs changed while compiling context.'})
                    fresh = self.repo.update(conn, fresh, executionContext=execution_context['descriptor'])
                    fresh = self.repo.checkpoint(conn, fresh)
                    self.repo.event(conn, fresh, 'task.context_compacted', manifestId=execution_context['descriptor']['manifestId'],
                                    inputRevision=fresh['desired_input_revision'], omissionCount=len(execution_context['descriptor']['omissions']))
                    run = fresh
                    expected = fresh['revision']
            # The research adapter consumes only this bounded packet. Exact
            # task anchors and the manifest pointer are persisted separately.
            run = {**run, 'operationalNotes':[execution_context['text']]}
        def still_current():
            with self.store.engine.connect() as conn:
                current=self.repo.run(conn,job['owner_id'],job['target_id'])
                self.repo.jobs.validate_lease(conn,job)
                if current['revision']!=expected or current['desired_input_revision']!=job['input_revision']: raise HTTPException(409,{'code':'revision_conflict','message':'Inputs changed.'})
        kernel_state=DecisionState.model_validate(run.get('kernelState') or {})
        if self.executor:
            result=self.executor(run,still_current)
        else:
            registry=ToolRegistry()
            def execute_scoped(args):
                if args.task_id!=run['id'] or args.input_revision!=run['desired_input_revision'] or args.operation_id!=operation['id']:
                    raise KernelError('tool_scope_mismatch')
                still_current()
                if run['kind']=='sandbox_lab':
                    from .sandbox import SandboxService
                    service=self.sandbox_factory(self.store) if self.sandbox_factory else SandboxService(self.store)
                    value=service.prepare(run,still_current)
                elif run['kind']=='research':
                    from .research import ResearchService
                    service=self.research_factory(self.store) if self.research_factory else ResearchService(self.store,model_provider=self.provider_getter())
                    value=service.prepare(run['owner_id'],run,run['researchSpec'],still_current)
                elif run['kind']=='calendar_read':
                    from .calendar_tasks import execute_calendar_read
                    value=execute_calendar_read(self.store,run['owner_id'],run,still_current)
                elif run['kind']=='lab_analysis':
                    value=analyze_general(run) if run.get('analysisMode')=='general' else analyze(run)
                else:
                    raise KernelError('tool_capability_denied')
                return ToolResult(status='partial' if value.get('completion',{}).get('partial') or value.get('completion',{}).get('status')=='partial' else 'completed',
                                  value=value,progressKey=operation['id'])
            tool_name={'lab_analysis':'lab_analysis.execute','sandbox_lab':'sandbox_lab.execute','research':'research.execute','calendar_read':'google_calendar.read'}.get(run['kind'])
            if not tool_name:raise KernelError('tool_unavailable')
            registry.register(ToolSpec(tool_name,TaskToolInput,{run['kind']},execute_scoped))
            kernel=AgentKernel(registry,self.decision_limits)
            decision,tool_result,kernel_state=kernel.step(
                {'kind':'call_tool','tool':tool_name,'arguments':{'taskId':run['id'],'inputRevision':run['desired_input_revision'],'operationId':operation['id']}},
                state=kernel_state,capabilities={run['kind']})
            if not isinstance(decision,CallToolDecision) or not tool_result or tool_result.status not in {'completed','partial'}:
                raise KernelError('tool_result_unavailable')
            result=tool_result.value
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
            if fresh['kind']=='research' and fresh.get('executionContext'):
                from .execution_context import ExecutionContextService
                ExecutionContextService(self.store).validate_commit(conn, fresh['owner_id'], fresh, fresh['executionContext'])
            artifacts=self.artifacts.publish(conn,fresh,operation,manifests)
            requirements=fresh.get('requirements') or {'requestedOutputs':[]}
            completion=CompletionEvaluator.evaluate(requirements,result['outputs'],result.get('sources',[]),result.get('completion',{}))
            if completion.get('status')=='failed': raise ValueError('Required output or completion check failed.')
            status='completed_partial' if completion.get('status')=='partial' else 'completed'
            fresh=self.repo.update(conn,fresh,status=status,phase='complete',summary=result['summary'],artifacts=artifacts,sources=result.get('sources',[]),completion=completion,pendingRequests=[],kernelState=kernel_state.model_dump(by_alias=True))
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
        if time.monotonic()-getattr(self,'_retention_checked_at',0)>=60:
            self._retention_checked_at=time.monotonic()
            try:
                from .retention import AgentRetention
                policy=AgentRetention(self.store).policy
                if any((policy.terminal_activity_seconds,policy.terminal_checkpoint_seconds,policy.terminal_artifact_seconds)):
                    AgentRetention(self.store,policy).prune(limit=500)
            except Exception as exc:
                log.warning('Agent retention iteration failed (%s)',type(exc).__name__)

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
