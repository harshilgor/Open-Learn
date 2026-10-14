"""Scheduled browser recovery checks without private portals or paid calls."""
import json
import time
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.identity import Principal, principal_context
from backend.app.session_models import LearningSession
from backend.app.models import utc_now, TopicScope
from backend.app.graph_generator import GraphGenerator
from backend.app.reminder_service import ReminderService, ReminderCreate
from backend.app.reminder_actions import ReminderActionRunner
from backend.app.workflow_store import WorkflowStore, encoded
from backend.app.browser_assistant.connections import Connections
from backend.app.browser_assistant.contracts import ConnectionCreate

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('OPENLEARN_CHAT_REMINDERS','true')
    monkeypatch.setenv('OPENLEARN_SCHEDULED_BROWSER_ENABLED','true')
    monkeypatch.setenv('OPENLEARN_CLASSIFICATION_MODE','off')
    path=Path('work')/('scheduled-'+uuid4().hex+'.sqlite')
    pg_url=os.getenv('OPENLEARN_SCHEDULED_BROWSER_TEST_DATABASE_URL')
    admin=None;schema=None
    if pg_url:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        url=make_url(pg_url)
        if url.host not in {'localhost','127.0.0.1','::1'} or url.get_backend_name()!='postgresql':
            raise ValueError('Scheduled browser tests require an explicit local PostgreSQL test database')
        schema='scheduled_test_'+uuid4().hex
        admin=create_engine(url,connect_args={'connect_timeout':5})
        with admin.begin() as conn:conn.execute(text('CREATE SCHEMA '+schema))
        url=url.update_query_dict({'options':'-csearch_path='+schema})
        store=Store(url.render_as_string(hide_password=False))
    else:
        store=Store(path)
    token=principal_context.set(Principal('alice','local'))
    scope=TopicScope(id='scope',topic='probability',resolved_meaning='probability',objective='Understand probability',depth='introductory',created_at=utc_now())
    store.save_scope(scope);graph=GraphGenerator().generate(scope);store.save_graph(graph)
    store.save_session(LearningSession(id='session',learner_id='alice',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    site=Connections(store).create('alice',ConnectionCreate(label='Portal',origin='https://example.com',executor='cloud'))
    yield store,ReminderService(store),site['id']
    principal_context.reset(token);store.close();path.unlink(missing_ok=True)
    if admin:
        with admin.begin() as conn:conn.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        admin.dispose()

def launch(setup, key='once', recurring=False):
    store,svc,site=setup
    args={'message':'Check assignments','connectionId':site,'sessionId':'session'}
    timing={'schedule':{'type':'cron','cron':'0 18 * * *'}} if recurring else {'when':'in 1 minute'}
    fire=svc.create('alice',ReminderCreate(**timing,message='Portal check',sessionId='session',quietStart=0,quietEnd=0,actions=[{'type':'skill','skillId':'assistant.website_task','args':args},{'type':'buddy_message','bodyTemplate':'{{summary}}'}]),key)
    svc.tick(fire['dueAt']+1)
    jobs=WorkflowStore(store)
    job=jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0])
    ReminderActionRunner(store).execute(job)
    with store.engine.connect() as conn:
        task=conn.execute(text('SELECT job_id FROM reminder_action_runs WHERE fire_id=:fire'),{'fire':fire['id']}).scalar_one()
    return fire,task

def terminal(store,task,status='completed'):
    with store.transaction() as conn:
        row=conn.execute(text('SELECT payload FROM assistant_runs WHERE id=:id'),{'id':task}).scalar_one()
        data=json.loads(row);data.update(status=status,summary='Assignment A is due Friday.',facts=[{'kind':'assignment','entityId':'a','title':'Assignment A'}])
        conn.execute(text('UPDATE assistant_runs SET status=:status,payload=:payload WHERE id=:id'),{'id':task,'status':status,'payload':encoded(data)})

def test_login_pause_restart_and_duplicate_completion(setup):
    store,svc,_=setup
    fire,task=launch(setup)
    terminal(store,task,'waiting_for_login')
    svc.reconcile();svc.reconcile()
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM reminders WHERE id=:id'),{'id':fire['id']}).scalar_one()=='delivering'
        assert conn.execute(text("SELECT count(*) FROM practice_records WHERE kind='reminder_message'")).scalar_one()==1
    terminal(store,task)
    # New service/runner objects simulate loss of process-local state.
    ReminderService(store).reconcile();ReminderService(store).reconcile()
    jobs=WorkflowStore(store)
    for identifier in jobs.ready_ids('interactive',{'reminder_actions'}):
        ReminderActionRunner(store).execute(jobs.claim(identifier))
    svc.reconcile()
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==1
        assert conn.execute(text('SELECT status FROM reminders WHERE id=:id'),{'id':fire['id']}).scalar_one()=='delivered'
        messages=WorkflowStore(store).listing_by_parent('alice','reminder_message','session')
        assert len(messages)==2
        assert any('Assignment A' in m['body'] for m in messages)

def test_cancellation_fences_result_and_task(setup):
    store,svc,_=setup
    fire,task=launch(setup)
    svc.cancel('alice',fire['id'])
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM assistant_runs WHERE id=:id'),{'id':task}).scalar_one()=='cancelled'
    terminal(store,task)
    svc.reconcile()
    assert not WorkflowStore(store).listing_by_parent('alice','reminder_message','session')

def test_overlapping_occurrence_is_skipped(setup):
    store,svc,_=setup
    fire,task=launch(setup,recurring=True)
    next_fire=svc.listing('alice','pending')['reminders'][0]
    svc.tick(next_fire['dueAt']+1)
    with store.engine.connect() as conn:
        row=conn.execute(text('SELECT status,payload FROM reminders WHERE id=:id'),{'id':next_fire['id']}).mappings().one()
        assert row['status']=='expired'
        assert json.loads(row['payload'])['skipReason']=='previous_occurrence_active'
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==1

def test_email_unknown_outcome_retries_frozen_request(setup,monkeypatch):
    import httpx
    from backend.app.scheduled_email import dispatch_email
    store,svc,_=setup
    monkeypatch.setenv('OPENLEARN_REMINDER_EMAIL_ENABLED','true')
    monkeypatch.setenv('RESEND_API_KEY','synthetic')
    monkeypatch.setenv('OPENLEARN_REMINDER_EMAIL_FROM','Open Learn <hello@example.com>')
    monkeypatch.setenv('OPENLEARN_REMINDER_EMAIL_RECIPIENTS','{"alice":"alice@example.com"}')
    monkeypatch.setenv('FORMA_WEB_ORIGIN','https://example.com')
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO reminder_preferences(owner_id,payload) VALUES('alice',:payload)"),{'payload':encoded({'emailOptIn':True,'channels':['email'],'quietStart':0,'quietEnd':0})})
    fire=svc.create('alice',ReminderCreate(when='in 1 minute',message='Notice',channels=['email']),'email')
    svc.tick(fire['dueAt']+1)
    jobs=WorkflowStore(store)
    ReminderActionRunner(store).execute(jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0]))
    identifier=jobs.ready_ids('interactive',{'general_reminder_dispatch'})[0]
    calls=[]
    def sender(url,**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise httpx.ReadTimeout('Response lost')
        return httpx.Response(200,json={'id':'email_1'},request=httpx.Request('POST',url))
    dispatch_email(store,jobs.claim(identifier),sender)
    monkeypatch.setenv('OPENLEARN_REMINDER_EMAIL_RECIPIENTS','{"alice":"changed@example.com"}')
    with store.transaction() as conn:conn.execute(text('UPDATE learning_jobs SET next_retry_at=0 WHERE id=:id'),{'id':identifier})
    dispatch_email(store,jobs.claim(identifier),sender)
    assert calls[0]['json']==calls[1]['json']
    assert calls[0]['headers']['Idempotency-Key']==calls[1]['headers']['Idempotency-Key']
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM notification_deliveries WHERE status='provider_handoff_confirmed'")).scalar_one()==1
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==0


def test_dispatch_commit_rolls_back_with_failed_binding(setup,monkeypatch):
    store,svc,site=setup
    fire=svc.create('alice',ReminderCreate(when='in 1 minute',message='Check',sessionId='session',actions=[{'type':'skill','skillId':'assistant.website_task','args':{'message':'Check assignments','connectionId':site,'sessionId':'session'}}]),'rollback')
    svc.tick(fire['dueAt']+1)
    jobs=WorkflowStore(store);job=jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0])
    original=jobs.__class__.finish
    def failed_finish(*args,**kwargs):raise RuntimeError('crash before commit')
    monkeypatch.setattr(jobs.__class__,'finish',failed_finish)
    with pytest.raises(RuntimeError):ReminderActionRunner(store).execute(job)
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==0
    monkeypatch.setattr(jobs.__class__,'finish',original)
    ReminderActionRunner(store).execute(job)
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==1


def test_partial_result_does_not_advance_checkpoint(setup):
    store,svc,_=setup
    fire,task=launch(setup,recurring=True)
    terminal(store,task,'completed_partial');svc.reconcile()
    assert not WorkflowStore(store).listing('alice','scheduled_portal_checkpoint')
    ledger=WorkflowStore(store)
    with store.engine.connect() as conn:
        data=json.loads(conn.execute(text('SELECT artifacts_json FROM reminder_action_runs WHERE fire_id=:id'),{'id':fire['id']}).scalar_one())
    assert data['summary'].startswith('Partial website check:')


def test_local_connection_cannot_schedule_cloud_work(setup):
    from fastapi import HTTPException
    store,svc,_=setup
    site=Connections(store).create('alice',ConnectionCreate(label='Local',origin='https://local.example',executor='local'))
    with pytest.raises(HTTPException) as exc:
        svc.create('alice',ReminderCreate(when='in 1 minute',message='Check',sessionId='session',actions=[{'type':'skill','skillId':'assistant.website_task','args':{'message':'Check','sessionId':'session','connectionId':site['id']}}]),'local')
    assert exc.value.detail['code']=='cloud_connection_required'


def test_compiler_binds_owned_conversation(setup):
    from backend.app.reminder_intent import compile_reminder
    store,svc,site=setup
    class Provider:
        def complete_json(self,prompt,**kwargs):
            assert 'assistant.website_task' in prompt
            return {'schedule':{'type':'cron','cron':'0 18 * * *'},'message':'Check portal','actions':[{'type':'skill','skillId':'assistant.website_task','args':{'message':'Check assignments','connectionId':site,'sessionId':'invented'}},{'type':'buddy_message','bodyTemplate':'{{summary}}'}]}
    value=compile_reminder('Every evening at 6pm check my portal',{'sessionId':'session','courseId':None,'buddyId':None,'timezone':'America/Los_Angeles','channels':['inbox'],'quietStart':0,'quietEnd':0,'connections':[{'id':site,'executor':'cloud'}]},Provider())
    assert value['actions'][0]['args']['sessionId']=='session'
    assert svc.create('alice',ReminderCreate.model_validate(value),'compiled')['sessionId']=='session'


def test_worker_mode_overrides_preserve_other_roles(monkeypatch):
    from backend.app.agent_execution.config import worker_mode
    monkeypatch.setenv('OPENLEARN_WORKER_MODE','embedded')
    monkeypatch.setenv('OPENLEARN_BROWSER_WORKER_MODE','external')
    monkeypatch.setenv('OPENLEARN_NOTIFICATIONS_WORKER_MODE','external')
    assert worker_mode()=='embedded'
    assert worker_mode('browser')=='external'
    assert worker_mode('notifications')=='external'


def test_repeated_unchanged_assignment_is_not_new(setup):
    store,svc,_=setup
    fire,task=launch(setup,recurring=True)
    terminal(store,task);svc.reconcile()
    jobs=WorkflowStore(store)
    for identifier in jobs.ready_ids('interactive',{'reminder_actions'}):ReminderActionRunner(store).execute(jobs.claim(identifier))
    next_fire=svc.listing('alice','pending')['reminders'][0]
    svc.tick(next_fire['dueAt']+1)
    ReminderActionRunner(store).execute(jobs.claim(jobs.ready_ids('interactive',{'reminder_actions'})[0]))
    with store.engine.connect() as conn:
        next_task=conn.execute(text('SELECT job_id FROM reminder_action_runs WHERE fire_id=:id'),{'id':next_fire['id']}).scalar_one()
    terminal(store,next_task);svc.reconcile()
    with store.engine.connect() as conn:
        data=json.loads(conn.execute(text('SELECT artifacts_json FROM reminder_action_runs WHERE fire_id=:id'),{'id':next_fire['id']}).scalar_one())
    assert 'No newly observed or changed assignments' in data['summary']


def test_schedule_retry_uses_frozen_interpretation(setup):
    from backend.app.reminder_admission import freeze,cached
    from backend.app.reminder_routes import ChatCommand
    from fastapi import HTTPException
    store,svc,_=setup
    body=ChatCommand(message='Every evening check my portal',sessionId='session')
    first={'message':'Check','when':'in 1 minute'}
    assert freeze(store,'alice',body,'key',first)==first
    assert freeze(store,'alice',body,'key',{'message':'Changed','when':'in 2 minutes'})==first
    assert cached(store,'alice',body,'key')==first
    with pytest.raises(HTTPException):cached(store,'alice',body.model_copy(update={'message':'Different'}),'key')


def test_explicit_portal_schedule_routes_to_reminder():
    from backend.app.agent_execution.admission import plan_message
    assert plan_message('Every evening check my connected portal for new assignments').kind=='reminder'
    assert plan_message('Check my portal tomorrow at 6pm').kind=='reminder'
    assert plan_message('Open YouTube').kind=='browser'


@pytest.mark.skipif(not os.getenv('OPENLEARN_SCHEDULED_BROWSER_TEST_DATABASE_URL'),reason='Requires explicit isolated local PostgreSQL URL')
def test_postgres_two_completion_reconcilers_publish_once(setup):
    from concurrent.futures import ThreadPoolExecutor
    store,svc,_=setup
    fire,task=launch(setup)
    terminal(store,task)
    def reconcile():
        token=principal_context.set(Principal('alice','local'))
        try:ReminderService(store).reconcile()
        finally:principal_context.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(reconcile) for _ in range(2)]
        for future in futures:future.result(timeout=20)
    jobs=WorkflowStore(store)
    ids=jobs.ready_ids('interactive',{'reminder_actions'})
    assert len(ids)==1
    ReminderActionRunner(store).execute(jobs.claim(ids[0]))
    assert len(WorkflowStore(store).listing_by_parent('alice','reminder_message','session'))==1
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==1
        assert conn.execute(text('SELECT status FROM reminders WHERE id=:id'),{'id':fire['id']}).scalar_one()=='delivered'
