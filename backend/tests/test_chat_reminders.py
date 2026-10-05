import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.identity import Principal, principal_context
from backend.app.reminder_service import ReminderService, ReminderCreate
from backend.app.reminder_worker import NotificationsWorker
from backend.app.reminder_schedule import parse_when, next_fire


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('OPENLEARN_CHAT_REMINDERS','true')
    path=Path('work')/('reminders-'+uuid4().hex+'.sqlite')
    store=Store(path);token=principal_context.set(Principal('alice','local'))
    yield store,ReminderService(store)
    principal_context.reset(token);store.close();path.unlink(missing_ok=True)


def test_once_replay_tick_and_inbox(env):
    store,svc=env
    command=ReminderCreate(when='in 1 minute',message='Call Sam')
    result=svc.create('alice',command,'once')
    assert svc.create('alice',command,'once')['id']==result['id']
    assert svc.tick(result['dueAt']+1)['claimed']==1
    assert svc.tick(result['dueAt']+1)['claimed']==0
    NotificationsWorker(store).tick()
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notification_deliveries WHERE channel='inbox'")).scalar_one()==1
        assert conn.execute(text('SELECT status FROM reminders WHERE id=:id'),{'id':result['id']}).scalar_one()=='delivered'


def test_recurring_cancel_snooze_and_expiration(env):
    store,svc=env
    command=ReminderCreate(schedule={'type':'cron','cron':'40 7 * * 1-5'},message='Quiz time',quietStart=0,quietEnd=0)
    result=svc.create('alice',command,'routine')
    svc.tick(result['dueAt']+1)
    assert len(svc.listing('alice','pending')['reminders'])==1
    svc.cancel('alice',result['id'])
    assert not svc.listing('alice','pending')['reminders']
    one=svc.create('alice',ReminderCreate(when='in 1 minute',message='Late'),'late')
    assert svc.tick(one['dueAt']+7201)['expired']==1


def test_scope_allowlist_and_idempotency(env):
    _,svc=env
    with pytest.raises(HTTPException):svc.create('alice',ReminderCreate(when='in 1 minute',message='Bad',actions=[{'type':'skill','skillId':'shell.exec'}]),'bad')
    one=svc.create('alice',ReminderCreate(when='in 1 minute',message='One'),'one')
    with pytest.raises(HTTPException):svc.cancel('bob',one['id'])
    with pytest.raises(HTTPException):svc.create('alice',ReminderCreate(when='in 1 minute',message='Changed'),'one')


def test_wall_time_and_dst():
    now=datetime(2026,3,7,20,tzinfo=timezone.utc).timestamp()
    with pytest.raises(ValueError):parse_when('2026-03-08T02:30','America/Los_Angeles',now)
    with pytest.raises(ValueError):parse_when('2026-11-01T01:30','America/Los_Angeles',now)
    first=next_fire({'type':'cron','cron':'40 7 * * 1-5'},'America/Los_Angeles',now)
    assert datetime.fromtimestamp(first,timezone.utc).hour==14


def test_action_artifacts_precede_notify_and_failure_fallback(env):
    from backend.app.reminder_actions import Registry,ReminderActionRunner
    from backend.app.workflow_store import WorkflowStore
    store,svc=env
    reg=Registry();reg.register('flashcards.due_summary',lambda owner,args,key,ctx:{'size':3,'deepLink':'/chat?flashcards=library'})
    result=svc.create('alice',ReminderCreate(when='in 1 minute',message='Review',actions=[{'type':'skill','skillId':'flashcards.due_summary'},{'type':'notify','bodyTemplate':'{{size}} cards ready'}]),'actions')
    svc.tick(result['dueAt']+1)
    jobs=WorkflowStore(store);job=jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0])
    ReminderActionRunner(store,registry=reg).execute(job)
    with store.engine.connect() as conn:
        payload=json.loads(conn.execute(text("SELECT payload FROM notification_deliveries WHERE reminder_id=:id AND channel='inbox'"),{'id':result['id']}).scalar_one())
        assert payload['body']=='3 cards ready'
        assert payload['url']=='/chat?flashcards=library'
    reg.handlers['flashcards.due_summary']=lambda *args:(_ for _ in ()).throw(ValueError('provider failed'))
    failed=svc.create('alice',ReminderCreate(when='in 1 minute',message='Review',actions=[{'type':'skill','skillId':'flashcards.due_summary'}]),'failed')
    svc.tick(failed['dueAt']+1)
    job=jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0]);ReminderActionRunner(store,registry=reg).execute(job)
    assert next(r for r in svc.listing('alice')['reminders'] if r['id']==failed['id'])['status']=='failed'


def test_pause_resume_and_snooze_replay(env):
    _,svc=env
    result=svc.create('alice',ReminderCreate(schedule={'type':'cron','cron':'0 12 * * *'},message='Study'),'pause')
    svc.control_routine('alice',result['policyId'],1,'pause')
    assert not svc.listing('alice','pending')['reminders']
    svc.control_routine('alice',result['policyId'],2,'resume')
    assert len(svc.listing('alice','pending')['reminders'])==1
    one=svc.create('alice',ReminderCreate(when='in 1 minute',message='Call'),'snooze')
    assert svc.snooze('alice',one['id'],60,'same')==svc.snooze('alice',one['id'],60,'same')
    with pytest.raises(HTTPException):svc.snooze('alice',one['id'],30,'same')


def test_chat_api_confirmations_and_cron_auth(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.reminder_routes import build_reminder_router
    from backend.app.material_routes import material_owner
    store,svc=env
    app=FastAPI();app.include_router(build_reminder_router(lambda:store))
    app.dependency_overrides[material_owner]=lambda:'alice'
    client=TestClient(app)
    response=client.post('/v1/reminder-chat-command',json={'message':'Remind me tomorrow at 3pm to call Sam','timezone':'America/Los_Angeles'},headers={'Idempotency-Key':'chat'})
    assert response.status_code==200,response.text
    assert '03:00 PM' in response.json()['message']
    assert response.json()['reminder']['title']=='call Sam'
    assert client.post('/internal/reminders/tick').status_code==403
    monkeypatch.setenv('OPENLEARN_CRON_SECRET','secret')
    assert client.post('/internal/reminders/tick',headers={'X-OpenLearn-Cron-Secret':'secret'}).status_code==200
    invalid=client.post('/v1/reminders',headers={'Idempotency-Key':'too-frequent'},json={'message':'spam','schedule':{'type':'cron','cron':'* * * * *'}})
    assert invalid.status_code==422


def test_async_completion_resumes_once(env):
    from backend.app.reminder_actions import Registry,ReminderActionRunner
    from backend.app.workflow_store import WorkflowStore
    from backend.app.browser_assistant.service import AssistantService
    from backend.app.browser_assistant.contracts import TaskCreate
    store,svc=env
    task=AssistantService(store).create('alice',TaskCreate(message='Read my deadlines'),'async-task')
    reg=Registry();reg.register('assistant.website_task',lambda *args:{'jobId':task['id']})
    fire=svc.create('alice',ReminderCreate(when='in 1 minute',message='Deadlines refreshed',actions=[{'type':'agent','skillId':'assistant.website_task','args':{'message':'Read my deadlines'}},{'type':'notify'}]),'async-fire')
    svc.tick(fire['dueAt']+1)
    jobs=WorkflowStore(store);job=jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0])
    runner=ReminderActionRunner(store,registry=reg);runner.execute(job)
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM notification_deliveries')).scalar_one()==0
    runner.resume(fire['id'],task['id'],'completed',{'summary':'Ready'})
    runner.resume(fire['id'],task['id'],'completed',{'summary':'Ready'})
    ids=jobs.ready_ids('interactive',{'reminder_actions'});assert len(ids)==1
    runner.execute(jobs.claim(ids[0]))
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM notification_deliveries')).scalar_one()==1


def test_push_gone_unsubscribes_without_duplicate_send(env,monkeypatch):
    import sys
    from types import SimpleNamespace
    store,svc=env
    calls=[]
    class Gone(Exception):
        response=SimpleNamespace(status_code=410)
    def send(*args,**kwargs):calls.append(1);raise Gone()
    monkeypatch.setitem(sys.modules,'pywebpush',SimpleNamespace(webpush=send,WebPushException=Gone))
    monkeypatch.setenv('OPENLEARN_VAPID_PRIVATE_KEY','test')
    monkeypatch.setenv('OPENLEARN_VAPID_SUBJECT','mailto:test@example.com')
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO notification_subscriptions(id,owner_id,endpoint_hash,active,payload) VALUES('sub','alice','hash',true,'{}')"))
    fire=svc.create('alice',ReminderCreate(when='in 1 minute',message='Push',channels=['inbox','push']),'push')
    svc.tick(fire['dueAt']+1)
    worker=NotificationsWorker(store);worker.tick();worker.tick();worker.tick()
    assert len(calls)==1
    with store.engine.connect() as conn:assert not conn.execute(text("SELECT active FROM notification_subscriptions WHERE id='sub'")).scalar_one()
