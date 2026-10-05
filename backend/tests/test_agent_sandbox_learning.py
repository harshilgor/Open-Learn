"""Sandbox semantics and failure boundaries; no paid calls or host code exec."""
import json
import io
import zipfile
from types import SimpleNamespace
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from backend.tests.test_agent_execution import env, answer
from backend.app.agent_execution.contracts import Message,Command
from backend.app.agent_execution.worker import AgentWorker
from backend.app.agent_execution.sandbox import SandboxService,OUTPUTS,verify
from backend.app.agent_execution.sandbox_config import SandboxPolicy
from backend.app.agent_execution.daytona_adapter import SandboxError,DaytonaAdapter
from backend.app.agent_execution.artifacts import Artifacts
from backend.app.agent_execution.learning import LearningContinuation,ContinuationRequest
from backend.app.agent_execution.tools import analyze


class FakeSandbox:
    """Test adapter emulates remote results without evaluating uploaded code."""
    is_test_adapter=True
    def __init__(self):
        self.resources={};self.created=0;self.executed=0;self.deleted=0;self.unknown_create=False;self.corrupt=False;self.fail_delete=False
    def create(self,key,policy):
        self.created+=1;identifier='remote-'+str(self.created)
        self.resources[identifier]={'key':key,'files':{}}
        if self.unknown_create:raise SandboxError('sandbox_creation_unknown',True)
        return identifier
    def reconcile(self,key):return next((k for k,v in self.resources.items() if v['key']==key),None)
    def stage(self,identifier,files):self.resources[identifier]['files'].update(files)
    def execute(self,identifier,timeout):
        self.executed+=1
        row=self.resources[identifier];task=json.loads(row['files']['/workspace/uploads/task.json'])
        result=analyze(task)
        for output in result['outputs']:row['files']['/workspace/outputs/'+output['name']]=output['content']
        row['files']['/workspace/outputs/report.json']=json.dumps({'summary':result['summary'],'completion':result['completion']},sort_keys=True).encode()
        if self.corrupt:row['files']['/workspace/outputs/analysis.csv']=b'trial,distance,time,speed\n1,10,2,999\n'
    def download(self,identifier,path,maximum):return self.resources[identifier]['files'][path]
    def release(self,identifier):
        if self.fail_delete:raise SandboxError('sandbox_cleanup_pending',True)
        self.resources.pop(identifier,None);self.deleted+=1


@pytest.fixture
def sandbox(env,monkeypatch):
    monkeypatch.setenv('OPENLEARN_SANDBOX_ENABLED','true');monkeypatch.setenv('OPENLEARN_DAYTONA_SNAPSHOT','test-snapshot');monkeypatch.setenv('DAYTONA_API_KEY','test-key-never-used')
    db,svc,repo=env;adapter=FakeSandbox();policy=SandboxPolicy(enabled=True,snapshot='test-snapshot')
    service=SandboxService(db,adapter,policy)
    worker=AgentWorker(db,sandbox_factory=lambda store:SandboxService(store,adapter,policy))
    return db,svc,repo,adapter,service,worker


def start(sandbox,client='sandbox-one',message='Analyze this CSV'):
    db,svc,repo,*_=sandbox
    response=svc.admit('alice',Message(clientMessageId=client,sessionId='session',text=message,capability='sandbox_lab'),client)
    return repo.read('alice',response['references'][0]['id'])


def complete(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox)
    worker.tick();run=repo.read('alice',run['id'])
    assert run['status']=='waiting' and not adapter.created
    answer(svc,repo,run);worker.tick()
    return repo.read('alice',run['id'])


def test_lazy_complete_remote_outputs_survive_deletion_and_owner(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=complete(sandbox)
    assert run['status']=='completed' and len(run['artifacts'])==4
    assert adapter.created==1 and adapter.executed==1 and adapter.deleted==1 and not adapter.resources
    assert '5 cm/s' in run['summary']
    for artifact in run['artifacts']:
        assert Artifacts(db).download('alice',artifact['id'])[1]
        with pytest.raises(HTTPException) as error:Artifacts(db).download('bob',artifact['id'])
        assert error.value.status_code==404
    worker.cleanup()
    with db.engine.connect() as conn:
        lease=conn.execute(text('SELECT status,payload FROM agent_sandbox_leases')).first()
    assert lease[0]=='deleted' and json.loads(lease[1])['outputsReady'] is False
    assert Artifacts(db).download('alice',run['artifacts'][0]['id'])[1]


def test_ambiguous_creation_reconciles_never_second_vm(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox,message='Use centimeters; ignore trial 3')
    adapter.unknown_create=True
    with pytest.raises(SandboxError,match='sandbox_creation_unknown'):service.prepare(run)
    adapter.unknown_create=False
    result=service.prepare(run)
    assert adapter.created==1 and adapter.executed==1 and result['completion']['status']=='verified'


def test_ambiguous_creation_absent_stays_unknown(sandbox):
    *_,service,worker=sandbox;run=start(sandbox,message='Use meters; ignore trial 3')
    adapter=sandbox[3];adapter.unknown_create=True
    with pytest.raises(SandboxError):service.prepare(run)
    adapter.resources.clear();adapter.unknown_create=False
    with pytest.raises(SandboxError,match='sandbox_creation_unknown'):service.prepare(run)
    assert adapter.created==1


def test_crash_after_storage_reuses_cached_remote_results(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox,message='Use centimeters; ignore trial 3')
    class Crash(BaseException):pass
    def crash(*args):raise Crash()
    crashed=AgentWorker(db,sandbox_factory=lambda s:service,after_storage=crash)
    with pytest.raises(Crash):crashed.tick()
    with db.transaction() as conn:conn.execute(text("UPDATE learning_jobs SET expires=0 WHERE kind='agent_step' AND status='running'"))
    worker.tick();run=repo.read('alice',run['id'])
    assert run['status']=='completed' and adapter.created==1 and adapter.executed==1
    assert len([i for i in svc.snapshot('alice','session')['items'] if i['type']=='task.completed'])==1


def test_corrupt_result_fails_without_publishing(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;adapter.corrupt=True
    run=start(sandbox,message='Use centimeters; ignore trial 3');worker.tick();run=repo.read('alice',run['id'])
    assert run['status']=='failed' and not run['artifacts']
    worker.cleanup();assert not adapter.resources


def test_cancel_mid_execution_cleans_remote_and_no_final(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox,message='Use centimeters; ignore trial 3')
    original=adapter.execute
    def cancel(identifier,timeout):
        original(identifier,timeout);fresh=repo.read('alice',run['id']);svc.command('alice',run['id'],Command(commandId='cancel-now',action='cancel',expectedRevision=fresh['revision']))
    adapter.execute=cancel
    worker.tick();worker.cleanup()
    assert repo.read('alice',run['id'])['status']=='cancelled' and not adapter.resources
    assert not [i for i in svc.snapshot('alice','session')['items'] if i['type']=='task.completed']


def test_paused_compute_confirmed_delete_and_new_generation(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox,message='Use meters; ignore trial 3')
    lease=service.acquire(run)
    svc.command('alice',run['id'],Command(commandId='pause',action='pause',expectedRevision=run['revision']))
    worker.cleanup();assert not adapter.resources
    paused=repo.read('alice',run['id']);svc.command('alice',run['id'],Command(commandId='resume',action='resume',expectedRevision=paused['revision']))
    resumed=repo.read('alice',run['id']);service.prepare(resumed)
    assert adapter.created==2


def test_cleanup_failure_is_durable_retry(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;adapter.fail_delete=True;run=complete(sandbox)
    assert adapter.resources and run['status']=='completed'
    adapter.fail_delete=False;worker.cleanup();assert not adapter.resources


def test_sdk_adapter_constructs_safe_policy_and_remote_only():
    calls=[]
    class Client:
        def create(self,params,timeout):calls.append((params,timeout));return SimpleNamespace(id='remote')
        def list(self,query,request_timeout):return iter([SimpleNamespace(id='remote')])
    adapter=DaytonaAdapter(Client());policy=SandboxPolicy(enabled=True,snapshot='pinned-snapshot')
    assert adapter.create('stable-key',policy)=='remote' and adapter.reconcile('stable-key')=='remote'
    params,timeout=calls[0]
    assert params.network_block_all is True and params.public is False and params.env_vars=={}
    assert params.labels['openlearn_creation']=='stable-key' and params.ttl_minutes==15


def test_quiz_continuation_idempotent_no_attempts_or_mastery(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);learning=LearningContinuation(db)
    body=ContinuationRequest(kind='quiz',expectedRevision=run['revision'])
    first=learning.request('alice',run['id'],body,'quiz-one')
    assert learning.request('alice',run['id'],body,'quiz-retry')==first
    identifiers=learning.repo.jobs.ready_ids('interactive',{'agent_continuation'},10)
    learning.advance(learning.repo.jobs.claim(identifiers[0],lease_seconds=120))
    items=learning.listing('alice',run['id'])['items'];assert items[0]['status']=='completed'
    assert learning.request('alice',run['id'],body,'quiz-again')['quizId']==items[0]['quizId']
    from backend.app.quiz_service import QuizService
    quiz=QuizService(db,None).public('alice',items[0]['quizId']);assert quiz['attempts']==[] and quiz['summary']['score'] is None
    assert quiz['agentResultProvenance']['taskId']==run['id']
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM practice_records WHERE kind='quiz'")).scalar_one()==1
        assert conn.execute(text("SELECT count(*) FROM practice_records WHERE kind='attempt'")).scalar_one()==0
    with pytest.raises(HTTPException):learning.listing('bob',run['id'])


def test_teaching_failure_does_not_fail_files(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);learning=LearningContinuation(db)
    body=ContinuationRequest(kind='teach',expectedRevision=run['revision']);learning.request('alice',run['id'],body,'teach')
    learning.tick()
    assert learning.listing('alice',run['id'])['items'][0]['status']=='failed'
    assert repo.read('alice',run['id'])['status']=='completed' and Artifacts(db).download('alice',run['artifacts'][0]['id'])[1]
    assert learning.request('alice',run['id'],body,'retry')['status']=='pending'


def test_unverified_or_active_assessment_denies_learning(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);learning=LearningContinuation(db)
    with repo.transaction() as conn:run=repo.update(conn,run,status='completed_partial')
    with pytest.raises(HTTPException) as error:learning.request('alice',run['id'],ContinuationRequest(kind='quiz',expectedRevision=run['revision']),'deny')
    assert error.value.status_code==409


class Teacher:
    provider_name='offline-lab-teacher'
    def __init__(self):self.prompts=[]
    def complete_json(self,prompt,max_tokens=4000):
        self.prompts.append(prompt)
        if prompt.startswith('You author'):
            data,_=json.JSONDecoder().raw_decode(prompt[prompt.index('\n{')+1:]);context=data['context']
            return {'concept_id':context['conceptIds'][0],'kind':'single','stem':'If the same distance is covered in half the time, how does the speed change?',
                'reasoning_target':'Predict the inverse relationship of time to speed at fixed distance.','family':'lab_speed_transfer',
                'options':[{'id':'a','label':'Halves'},{'id':'b','label':'Doubles'}],
                'correct_ids':['b'],'solution':'A fixed numerator divided by half the denominator produces twice the original quotient.',
                'criteria':[{'id':'speed','description':'Computes distance divided by time with consistent units','weight':1}],
                'hints':['Use distance divided by time.'],'source_ids':[context['sources'][0]['spanId']]}
        if prompt.startswith('Independently'):return {'unambiguous':True,'concept_test':True,'novel':True,'supported':True,'correct_ids':['b'],'solution':'At fixed distance, reducing time by one half yields twice the speed.'}
        if prompt.startswith('Compare'):return {'agree':True}
        return {'blocks':[{'kind':'explanation','heading':'Lab speed','body':'Divide distance by time: 10 centimeters over 2 seconds equals 5 cm/s. The filtered second trial gives the same speed.'}]}


def test_teaching_real_journey_context_and_no_performance_evidence(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);teacher=Teacher();learning=LearningContinuation(db,teacher)
    learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision']),'explain')
    jobs=learning.repo.jobs.ready_ids('interactive',{'agent_continuation'},10);learning.advance(learning.repo.jobs.claim(jobs[0],lease_seconds=120))
    result=learning.listing('alice',run['id'])['items'][0]
    assert result['status']=='completed' and '5 cm/s' in result['lesson']['blocks'][0]['body']
    assert '5 cm/s' in teacher.prompts[-1] and 'Do not infer mastery' in teacher.prompts[-1]
    from backend.app.state_service import LearnerStateService
    assert not LearnerStateService(db).list_evidence('alice')
    from backend.app.journey_service import JourneyService
    assert len(JourneyService(db,teacher).get('alice','session')['turns'])==1


def test_teaching_crash_reuses_prepared_snapshot_and_one_turn(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);teacher=Teacher()
    class Crash(BaseException):pass
    def crash(*args):raise Crash()
    learning=LearningContinuation(db,teacher,after_prepare=crash)
    learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision']),'explain')
    with pytest.raises(Crash):learning.tick()
    assert len(teacher.prompts)==1
    with db.transaction() as conn:conn.execute(text("UPDATE learning_jobs SET expires=0 WHERE kind='agent_continuation' AND status='running'"))
    LearningContinuation(db,teacher).tick()
    assert len(teacher.prompts)==1 and LearningContinuation(db).listing('alice',run['id'])['items'][0]['status']=='completed'


def test_teaching_learning_watermark_change_fences_delivery(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);teacher=Teacher()
    def change(*args):
        from backend.app.evidence_ledger import EvidenceLedger
        with db.transaction() as conn:EvidenceLedger(db).emit(conn,'alice','new-event','LESSON_VIEWED')
    learning=LearningContinuation(db,teacher,after_prepare=change)
    learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision']),'explain');learning.tick()
    assert learning.listing('alice',run['id'])['items'][0]['status']=='failed'
    from backend.app.journey_service import JourneyService
    assert not JourneyService(db,teacher).get('alice','session')['turns']


def test_quiz_learner_answer_uses_existing_assisted_evaluation(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox);teacher=Teacher();learning=LearningContinuation(db,teacher)
    learning.request('alice',run['id'],ContinuationRequest(kind='quiz',expectedRevision=run['revision']),'quiz');learning.tick()
    from backend.app.quiz_service import QuizService
    from backend.app.assessment_models import AnswerCommand
    quiz_id=learning.listing('alice',run['id'])['items'][0]['quizId'];quiz_service=QuizService(db,teacher)
    prepared=quiz_service.prepare('alice',quiz_id,1)
    with db.transaction() as conn:quiz_service.commit_prepared(conn,'alice',prepared)
    quiz=quiz_service.public('alice',quiz_id)
    assert 'correct_ids' not in json.dumps(quiz)
    from backend.app.state_service import LearnerStateService
    assert not LearnerStateService(db).list_evidence('alice')
    graded=quiz_service.grade('alice',quiz_id,AnswerCommand(presentationId=quiz['current']['id'],expectedRevision=quiz['revision'],selectedIds=['b'],externalHelp=True))
    with db.transaction() as conn:quiz_service.commit_grade(conn,'alice',graded)
    result=quiz_service.public('alice',quiz_id)
    assert result['attempts'][0]['assisted'] is True and result['summary']['score']==100
    evidence=LearnerStateService(db).list_evidence('alice')
    assert len(evidence)==1 and evidence[0].condition.value=='assisted'


def test_account_erasure_preserves_remote_cleanup_obligation(sandbox):
    db,svc,repo,adapter,service,worker=sandbox;run=start(sandbox,message='Use centimeters; ignore trial 3');lease=service.acquire(run)
    from backend.app.identity_data import erase_owner,cleanup_objects,export_owner
    from backend.app.identity_import import OMIT
    exported=export_owner(db,'alice')
    assert 'agent_sandbox_leases' not in exported['tables']
    assert {'agent_sandbox_leases','agent_learning_continuations','agent_sandbox_cleanup'}.issubset(OMIT)
    erase_owner(db,'alice')
    with db.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_sandbox_leases')).scalar_one()==0
        assert conn.execute(text('SELECT count(*) FROM agent_sandbox_cleanup')).scalar_one()==1
    service.cleanup();cleanup_objects(db)
    assert not adapter.resources
    with db.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM agent_sandbox_cleanup')).scalar_one()==0


def test_daily_creation_budget_reservation_is_enforced(sandbox):
    db,svc,repo,adapter,service,worker=sandbox
    limited=SandboxService(db,adapter,SandboxPolicy(enabled=True,snapshot='test',max_owner_creations_day=1))
    first=start(sandbox,message='Use centimeters; ignore trial 3');limited.prepare(first)
    second=start(sandbox,client='second',message='Use meters; ignore trial 3')
    with pytest.raises(SandboxError,match='sandbox_daily_budget_exhausted'):limited.acquire(second)
    assert adapter.created==1


def test_http_sandbox_and_teaching_continuation_flow(sandbox,monkeypatch):
    db,svc,repo,adapter,service,worker=sandbox
    monkeypatch.setenv('AI_TUTOR_ENV','development');monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY','true')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.agent_execution.routes import build_agent_router
    from backend.app.browser_assistant.routes import build_assistant_router
    app=FastAPI();app.add_middleware(IdentityMiddleware,store_provider=lambda:db)
    app.include_router(build_agent_router(lambda:db));app.include_router(build_assistant_router(lambda:db,lambda:None))
    client=TestClient(app);headers={'X-Dev-Learner-Id':'alice'}
    body={'clientMessageId':'http','sessionId':'session','text':'Analyze CSV','capability':'sandbox_lab'}
    response=client.post('/v1/assistant/messages',json=body,headers={**headers,'Idempotency-Key':'http'})
    assert response.status_code==202,response.text
    task_id=response.json()['references'][0]['id'];worker.tick()
    task=client.get('/v1/assistant/tasks/'+task_id,headers=headers).json();question=task['pendingRequests'][0]
    response=client.post('/v1/assistant/messages',json={'clientMessageId':'http-answer','sessionId':'session','text':'Centimeters; ignore trial 3','targetTaskId':task_id,'replyToRequestId':question['requestId'],'expectedRevision':task['revision'],'expectedRequestRevision':question['revision']},headers={**headers,'Idempotency-Key':'http-answer'})
    assert response.status_code==202,response.text
    worker.tick();task=client.get('/v1/assistant/tasks/'+task_id,headers=headers).json();assert task['status']=='completed'
    path=f'/v1/assistant/tasks/{task_id}/continuations'
    request={'kind':'teach','expectedRevision':task['revision']}
    response=client.post(path,json=request,headers={**headers,'Idempotency-Key':'explain'})
    assert response.status_code==202,response.text
    LearningContinuation(db,Teacher()).tick()
    result=client.get(path,headers=headers).json()['items'][0]
    assert result['status']=='completed' and result['lesson']['blocks']
    assert client.get(path,headers={'X-Dev-Learner-Id':'bob'}).status_code==404
    assert client.post(path,json=request,headers={**headers,'Idempotency-Key':'explain'}).json()['id']==result['id']
    for artifact in task['artifacts']:
        response=client.get(f'/v1/assistant/artifacts/{artifact["id"]}/download',headers=headers)
        assert response.status_code==200 and response.content


def test_source_artifact_revocation_between_learning_prepare_and_commit(sandbox):
    db,svc,repo,*_=sandbox;run=complete(sandbox)
    def delete(*args):
        with db.transaction() as conn:conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE run_id=:run"),{'run':run['id']})
    learning=LearningContinuation(db,Teacher(),after_prepare=delete)
    learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision']),'explain');learning.tick()
    assert learning.listing('alice',run['id'])['items'][0]['status']=='failed'
    from backend.app.journey_service import JourneyService
    assert not JourneyService(db,Teacher()).get('alice','session')['turns']


def test_owned_material_csv_lineage_and_source_deletion(sandbox,monkeypatch):
    db,svc,repo,adapter,service,worker=sandbox
    from pathlib import Path
    from uuid import uuid4
    monkeypatch.setenv('AI_TUTOR_MATERIAL_DIR',str(Path('work')/('sandbox-materials-'+uuid4().hex)))
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    from backend.app.agent_execution.tools import FIXTURE
    materials=MaterialService(db);content=FIXTURE.encode()
    item=materials.create('alice',UploadRequest(title='Owned lab.csv',mediaType='text/plain',byteCount=len(content)))
    materials.upload('alice',item['materialId'],item['versionId'],content)
    response=svc.admit('alice',Message(clientMessageId='owned-csv',sessionId='session',text='Use centimeters; ignore trial 3',capability='sandbox_lab',materialVersionId=item['versionId']),'owned-csv')
    worker.tick();run=repo.read('alice',response['references'][0]['id']);assert run['status']=='completed'
    assert run['artifacts'][0]['lineage']['inputMaterial']['versionId']==item['versionId']
    materials.delete('alice',item['materialId'])
    assert repo.read('alice',run['id'])['csvText'] is None
    with pytest.raises(HTTPException):Artifacts(db).download('alice',run['artifacts'][0]['id'])
    worker.cleanup()
    with db.engine.connect() as conn:assert conn.execute(text("SELECT count(*) FROM agent_artifacts WHERE status='published'")).scalar_one()==0


def test_assessment_source_cannot_enter_sandbox(sandbox,monkeypatch):
    db,svc,repo,adapter,service,worker=sandbox
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    from backend.app.agent_execution.tools import FIXTURE
    materials=MaterialService(db);content=FIXTURE.encode()
    item=materials.create('alice',UploadRequest(title='Private answer.csv',mediaType='text/plain',byteCount=len(content),role='answer_key'))
    materials.upload('alice',item['materialId'],item['versionId'],content)
    with pytest.raises(HTTPException) as error:svc.admit('alice',Message(clientMessageId='private-csv',sessionId='session',text='Analyze',capability='sandbox_lab',materialVersionId=item['versionId']),'private-csv')
    assert error.value.status_code==403 and adapter.created==0


@pytest.mark.parametrize('erase_account',[False,True])
def test_late_cache_upload_after_cleanup_is_reaped(sandbox,erase_account):
    db,svc,repo,adapter,service,worker=sandbox
    run=start(sandbox,message='Use centimeters; ignore trial 3')
    original=service.objects.put;keys=[]
    def late(owner,key,content):
        if not keys:
            if erase_account:
                from backend.app.identity_data import erase_owner,cleanup_objects
                erase_owner(db,owner);service.cleanup();cleanup_objects(db)
            else:
                fresh=repo.read(owner,run['id'])
                svc.command(owner,run['id'],Command(commandId='late-cancel',action='cancel',expectedRevision=fresh['revision']))
                service.cleanup()
        keys.append(key);return original(owner,key,content)
    service.objects.put=late
    with pytest.raises((HTTPException,SandboxError)):service.prepare(run)
    service.cleanup()
    from backend.app.identity_data import cleanup_objects
    cleanup_objects(db)
    assert not adapter.resources
    for key in keys:
        with pytest.raises(Exception):service.objects.read('alice',key)
