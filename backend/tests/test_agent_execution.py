"""Meaningful offline vertical flow, output semantics and crash/owner fencing."""
import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.agent_execution.contracts import Message, Command
from backend.app.agent_execution.coordinator import Coordinator
from backend.app.agent_execution.repository import Repository
from backend.app.agent_execution.worker import AgentWorker
from backend.app.agent_execution.artifacts import Artifacts


@pytest.fixture
def env(monkeypatch):
    tmp_path=Path('work')/('agent-tests-'+uuid4().hex)
    tmp_path.mkdir(parents=True)
    monkeypatch.setenv('OPENLEARN_AGENT_ADMISSION_ENABLED','true')
    monkeypatch.setenv('OPENLEARN_ASSISTANT_OBJECTS_DIR',str(tmp_path/'objects'))
    db=Store(tmp_path/'agent.sqlite')
    from backend.app.models import TopicScope, utc_now
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    scope=TopicScope(id='scope',topic='physics',resolved_meaning='physics',objective='lab',depth='introductory',created_at=utc_now())
    db.save_scope(scope);graph=GraphGenerator().generate(scope);db.save_graph(graph)
    db.save_session(LearningSession(id='session',learner_id='alice',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    yield db,Coordinator(db),Repository(db)
    db.close()


def start(env,client='one',**kwargs):
    db,svc,repo=env
    response=svc.admit('alice',Message(clientMessageId=client,sessionId='session',text='Analyze the lab CSV',capability='lab_analysis',**kwargs),client)
    return response,repo.read('alice',response['references'][0]['id'])


def answer(svc,repo,run,client='answer',message='Centimeters; ignore trial 3'):
    request=run['pendingRequests'][0]
    return svc.admit('alice',Message(clientMessageId=client,sessionId='session',text=message,targetTaskId=run['id'],replyToRequestId=request['requestId'],expectedRevision=run['revision'],expectedRequestRevision=request['revision']),client)


def test_complete_flow_semantics_duplicate_and_correction(env):
    db,svc,repo=env;response,run=start(env)
    assert start(env)[0]==response
    worker=AgentWorker(db);worker.tick();run=repo.read('alice',run['id'])
    assert run['status']=='waiting' and run['checkpointVersion']>0
    reply=answer(svc,repo,run);assert answer(svc,repo,run)==reply
    worker.tick();complete=repo.read('alice',run['id'])
    assert complete['status']=='completed'
    assert '5 cm/s' in complete['summary'] and '999' not in complete['summary']
    book=next(a for a in complete['artifacts'] if a['name'].endswith('xlsx'))
    _,data=Artifacts(db).download('alice',book['id'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        assert len(root.findall('s:sheetData/s:row',ns))==3
        assert [float(c.text) for c in root.findall('s:sheetData/s:row/s:c[@r="D2"]/s:v',ns)]==[5]
        assert b'cm_per_s' in archive.read('xl/worksheets/sheet1.xml')
    activity=svc.snapshot('alice','session')
    assert len([i for i in activity['items'] if i['type']=='input.requested'])==1
    assert len([i for i in activity['items'] if i['type']=='task.completed'])==1
    corrected=svc.admit('alice',Message(clientMessageId='correct',sessionId='session',text='Use meters instead',targetTaskId=run['id'],expectedRevision=complete['revision']),'correct')
    worker.tick();new=repo.read('alice',corrected['references'][0]['id'])
    assert new['parentTaskId']==run['id'] and '5 m/s' in new['summary']
    assert Artifacts(db).download('alice',book['id'])[1]==data


def test_cross_owner_stale_answer_and_pause(env):
    db,svc,repo=env;_,run=start(env);worker=AgentWorker(db);worker.tick();run=repo.read('alice',run['id'])
    with pytest.raises(HTTPException) as denied:repo.read('bob',run['id'])
    assert denied.value.status_code==404
    with pytest.raises(HTTPException):svc.snapshot('bob','session')
    pause=Command(commandId='pause',action='pause',expectedRevision=run['revision'])
    ack=svc.command('alice',run['id'],pause);assert svc.command('alice',run['id'],pause)==ack
    with pytest.raises(HTTPException) as stale:answer(svc,repo,run)
    assert stale.value.status_code==409
    run=repo.read('alice',run['id']);svc.command('alice',run['id'],Command(commandId='resume',action='resume',expectedRevision=run['revision']))
    assert repo.read('alice',run['id'])['status']=='waiting'
    answer(svc,repo,repo.read('alice',run['id']));worker.tick()
    with pytest.raises(HTTPException):Artifacts(db).download('bob',repo.read('alice',run['id'])['artifacts'][0]['id'])


def test_crash_after_storage_reclaims_one_operation_and_final(env):
    db,svc,repo=env;_,run=start(env);AgentWorker(db).tick();answer(svc,repo,repo.read('alice',run['id']))
    worker=AgentWorker(db);worker.repo.outbox.drain({'agent.step':worker.enqueue})
    identifier=worker.repo.jobs.ready_ids('interactive',{'agent_step'})[0];old=worker.repo.jobs.claim(identifier,lease_seconds=120)
    class Crash(BaseException):pass
    worker.after_storage=lambda *args:(_ for _ in ()).throw(Crash())
    with pytest.raises(Crash):worker.advance(old)
    with db.transaction() as conn:conn.execute(text('UPDATE learning_jobs SET expires=0 WHERE id=:id'),{'id':identifier})
    replacement=AgentWorker(db);replacement.tick()
    with pytest.raises(HTTPException):worker.advance(old)
    complete=repo.read('alice',run['id']);assert complete['status']=='completed'
    with db.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_operations')).scalar_one()==1
        assert conn.execute(text("SELECT count(*) FROM agent_artifacts WHERE status='published'")).scalar_one()==3
    assert len([i for i in svc.snapshot('alice','session')['items'] if i['type']=='task.completed'])==1


def test_cancel_during_execution_fences_publication_and_cleans(env):
    db,svc,repo=env;_,run=start(env);AgentWorker(db).tick();answer(svc,repo,repo.read('alice',run['id']))
    def stop(task,manifests):
        current=repo.read('alice',task['id']);svc.command('alice',task['id'],Command(commandId='cancel',action='cancel',expectedRevision=current['revision']))
    worker=AgentWorker(db,after_storage=stop);worker.tick();worker.cleanup()
    assert repo.read('alice',run['id'])['status']=='cancelled'
    with db.engine.connect() as conn:assert conn.execute(text("SELECT count(*) FROM agent_artifacts WHERE status='published'")).scalar_one()==0


def test_duplicate_concurrent_admission_and_direct_routing(env):
    db,svc,repo=env
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:start(env)[0],range(2)))
    assert responses[0]==responses[1]
    ordinary=svc.admit('alice',Message(clientMessageId='tutor',sessionId='session',text='Explain fractions'),'tutor')
    assert ordinary['handled'] is False and ordinary['status']=='direct'
    with pytest.raises(HTTPException):svc.admit('alice',Message(clientMessageId='tutor',sessionId='session',text='Different'),'tutor')


def test_authenticated_http_text_reply_reconnect_and_old_browser_contract(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.agent_execution.routes import build_agent_router
    from backend.app.browser_assistant.routes import build_assistant_router
    monkeypatch.setenv('AI_TUTOR_ENV','development');monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY','true')
    db,svc,repo=env;app=FastAPI();app.add_middleware(IdentityMiddleware,store_provider=lambda:db)
    app.include_router(build_assistant_router(lambda:db));app.include_router(build_agent_router(lambda:db))
    client=TestClient(app);headers={'X-Dev-Learner-Id':'alice','Idempotency-Key':'http-one'}
    body={'schemaVersion':2,'clientMessageId':'http-one','sessionId':'session','text':'Analyze my lab','capability':'lab_analysis'}
    created=client.post('/v1/assistant/messages',headers=headers,json=body);assert created.status_code==202,created.text
    task_id=created.json()['references'][0]['id'];AgentWorker(db).tick()
    run=client.get('/v1/assistant/tasks/'+task_id,headers=headers).json();request=run['pendingRequests'][0]
    answer_body={'schemaVersion':2,'clientMessageId':'http-answer','sessionId':'session','text':'centimeters; ignore trial 3','targetTaskId':task_id,'replyToRequestId':request['requestId'],'expectedRevision':run['revision'],'expectedRequestRevision':request['revision']}
    answered=client.post('/v1/assistant/messages',headers={**headers,'Idempotency-Key':'http-answer'},json=answer_body);assert answered.status_code==202,answered.text
    assert client.post('/v1/assistant/messages',headers={**headers,'Idempotency-Key':'http-answer'},json=answer_body).json()==answered.json()
    command=next(ref['id'] for ref in answered.json()['references'] if ref['kind']=='command')
    assert client.get(f'/v1/assistant/tasks/{task_id}/commands/{command}',headers=headers).json()['applicationState']=='applied'
    AgentWorker(db).tick();state=client.get('/v1/assistant/tasks/'+task_id,headers=headers).json()
    assert state['status']=='completed'
    snapshot=client.get('/v1/assistant/sessions/session/activity',headers=headers).json()
    assert client.get('/v1/assistant/sessions/session/events?after='+str(snapshot['cursor']),headers=headers).json()['items']==[]
    assert client.get('/v1/assistant/tasks/'+task_id,headers={'X-Dev-Learner-Id':'bob'}).status_code==404
    for resource in [f'/v1/assistant/tasks/{task_id}/events',f'/v1/assistant/artifacts/{state["artifacts"][0]["id"]}/download']:
        assert client.get(resource,headers={'X-Dev-Learner-Id':'bob'}).status_code==404
    legacy=client.post('/v1/assistant/tasks',headers={**headers,'Idempotency-Key':'old'},json={'message':'Open https://example.org','sessionId':'session'})
    assert legacy.status_code==202,legacy.text
    assert 'schemaVersion' not in legacy.json()
    paused=client.post('/v1/assistant/tasks/'+legacy.json()['id']+'/commands',headers=headers,json={'action':'pause','expectedRevision':legacy.json()['revision']})
    assert paused.status_code==200 and paused.json()['status']=='paused'
    assert task_id not in {t['id'] for t in client.get('/v1/assistant/tasks?sessionId=session',headers=headers).json()['tasks']}


def test_legacy_recovery_does_not_claim_agent_runs(env):
    from backend.app.browser_assistant.workers import AssistantWorker
    db,svc,repo=env;_,run=start(env)
    with repo.transaction() as conn:run=repo.update(conn,repo.run(conn,'alice',run['id']),status='running')
    AssistantWorker(db).recover()
    assert repo.read('alice',run['id'])['status']=='running'


def test_two_workers_only_one_claim_and_revision_fences_stored_results(env):
    db,svc,repo=env;_,run=start(env);AgentWorker(db).tick();answer(svc,repo,repo.read('alice',run['id']))
    worker=AgentWorker(db);worker.repo.outbox.drain({'agent.step':worker.enqueue})
    identifier=worker.repo.jobs.ready_ids('interactive',{'agent_step'})[0]
    with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:worker.repo.jobs.claim(identifier),range(2)))
    assert len([claim for claim in claims if claim])==1
    def steer(task,manifests):
        current=repo.read('alice',task['id']);svc.command('alice',task['id'],Command(commandId='change-units',action='steer',expectedRevision=current['revision'],text='Use meters'))
    worker.after_storage=steer
    with pytest.raises(HTTPException) as stale:worker.advance(next(claim for claim in claims if claim))
    assert stale.value.detail['code']=='lease_lost'
    worker.retire_stale_outputs(next(claim for claim in claims if claim));AgentWorker(db).tick()
    assert '5 m/s' in repo.read('alice',run['id'])['summary']


def test_migration_backfills_legacy_event_counter_and_roundtrips():
    from alembic.config import Config
    from alembic import command
    from backend.app.database import BACKEND_ROOT
    from sqlalchemy import create_engine
    directory=Path('work')/('agent-migration-'+uuid4().hex);directory.mkdir(parents=True)
    url='sqlite+pysqlite:///'+str((directory/'db.sqlite').resolve()).replace('\\','/')
    config=Config(str(BACKEND_ROOT/'alembic.ini'));config.set_main_option('script_location',str(BACKEND_ROOT/'migrations'));config.set_main_option('sqlalchemy.url',url)
    command.upgrade(config,'0041_browser_assistant');engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO assistant_runs(id,owner_id,revision,command_key,request_hash,status,payload,created_at,updated_at) VALUES('legacy','alice',1,'legacy','hash','queued','{}',0,0)"))
        conn.execute(text("INSERT INTO assistant_events(id,owner_id,run_id,sequence,payload,created_at) VALUES('event','alice','legacy',9,'{}',0)"))
    command.upgrade(config,'head')
    with engine.connect() as conn:
        row=conn.execute(text("SELECT runtime_owner,event_sequence FROM assistant_runs WHERE id='legacy'")).first()
        assert tuple(row)==('browser_legacy',9)
    command.downgrade(config,'0041_browser_assistant');command.upgrade(config,'head')
    with engine.connect() as conn:assert conn.execute(text("SELECT event_sequence FROM assistant_runs WHERE id='legacy'")).scalar_one()==9
    engine.dispose()
