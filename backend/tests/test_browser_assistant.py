"""Browser assistant contract, recovery, reconciliation and reminder integration."""
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.identity import Principal, principal_context
from backend.app.course_service import CourseService
from backend.app.course_models import CourseCreate
from backend.app.academic_planning import AcademicPlanningService
from backend.app.browser_assistant.contracts import *
from backend.app.browser_assistant.connections import Connections
from backend.app.browser_assistant.service import AssistantService
from backend.app.browser_assistant.store import AssistantStore
from backend.app.browser_assistant.workers import AssistantWorker
from backend.app.browser_assistant.policy import authorize_action, origin
from backend.app.browser_assistant.intent import fallback_intent
from backend.app.browser_assistant.reminders import create_policy, rebuild, tick_reminders, event_instant
from backend.app.browser_assistant.evidence import validate_candidate, date_supported

@pytest.fixture
def environment():
    path=Path('work')/('browser-test-'+uuid4().hex+'.sqlite3')
    store=Store(path)
    token=principal_context.set(Principal('alice','local'))
    course=CourseService(store).create_course('alice',CourseCreate(name='Biology'))
    yield store,course.id
    principal_context.reset(token);store.close();path.unlink(missing_ok=True)


def run_to_end(worker, identifier, limit=25):
    for _ in range(limit):
        worker.tick()
        run=worker.repo.read('assistant_runs','alice',identifier)
        if run['status'] in {'completed','completed_partial','failed','waiting_for_user','waiting_for_login'}:return run
    raise AssertionError('Task did not settle')


class Reader:
    def execute(self,action,connection,run,previous):
        url=connection['origin']+'/courses/1'
        if action.resource=='courses':
            return Observation(url=url,document_revision='courses-v1',account_id='student-1',complete=True,
                platform_items=[{'id':1,'name':'Biology','workflow_state':'available','enrollments':[{'type':'StudentEnrollment'}],'term':{'id':4}},
                                {'id':2,'name':'Archived','workflow_state':'completed','enrollments':[{'type':'StudentEnrollment'}]}])
        if action.resource=='assignments':
            return Observation(url=url+'/assignments',document_revision='assignments-v1',account_id='student-1',complete=True,
                blocks=[TextBlock(ref='item:0',text='Midterm 1 2027-02-10T17:00:00Z')],
                platform_items=[{'id':7,'name':'Midterm 1','due_at':'2027-02-10T17:00:00Z'}])
        return Observation(url=url+'/'+str(action.resource),document_revision='empty-v1',account_id='student-1',complete=True)


def test_canvas_discovery_and_saving_without_model(environment):
    store,course=environment
    site=Connections(store).create('alice',ConnectionCreate(label='University',origin='https://canvas.example.edu',platform='canvas',executor='cloud',preferred=True,category='university_lms'))
    task=AssistantService(store).create('alice',TaskCreate(message='Go to Canvas, find my classes and save my midterms',connection_id=site['id']),'same-key')
    assert AssistantService(store).create('alice',TaskCreate(message=task['message'],connection_id=site['id']),'same-key')['id']==task['id']
    worker=AssistantWorker(store,executor_factory=lambda _:Reader())
    result=run_to_end(worker,task['id'])
    assert result['status']=='completed_partial' # no text reasoning provider
    assert len(result['enrollments'])==1 and len(result['facts'])==1
    assert result['facts'][0]['source']['quote']=='Midterm 1 2027-02-10T17:00:00Z'
    assert result['facts'][0]['date']['kind']=='instant'
    with pytest.raises(HTTPException):worker.repo.read('assistant_runs','bob',task['id'])
    with pytest.raises(HTTPException):AssistantService(store).create('alice',TaskCreate(message='different'),'same-key')


def test_summary_does_not_save(environment):
    store,_=environment
    site=Connections(store).create('alice',ConnectionCreate(label='University',origin='https://canvas.example.edu',platform='canvas',executor='cloud'))
    task=AssistantService(store).create('alice',TaskCreate(message='Open Canvas and just summarize my midterms, do not save',connection_id=site['id']))
    result=run_to_end(AssistantWorker(store,executor_factory=lambda _:Reader()),task['id'])
    assert len(result['facts'])==1 and result['facts'][0]['saved'] is False
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM academic_entities')).scalar()==0
        assert conn.execute(text('SELECT count(*) FROM courses')).scalar()==1


def test_device_ack_fencing_duplicate_and_cancel(environment):
    store,_=environment
    sites=Connections(store);svc=AssistantService(store)
    site=sites.create('alice',ConnectionCreate(label='Study',origin='https://study.example.org'))
    grant=sites.pair('alice',site['id']);device=Principal('alice','browser',grant['deviceId'])
    task=svc.create('alice',TaskCreate(message='Open https://study.example.org',connection_id=site['id']))
    AssistantWorker(store).tick()
    command=svc.poll(device)['commands'][0]
    result=BrowserResult(generation=command['generation'],connection_revision=command['connectionRevision'],observation=Observation(url=site['origin'],document_revision='a',complete=False))
    with pytest.raises(HTTPException):svc.acknowledge(Principal('bob','browser','other'),command['id'],result)
    with pytest.raises(HTTPException):svc.acknowledge(device,command['id'],result.model_copy(update={'generation':'old'}))
    assert svc.acknowledge(device,command['id'],result)['status']=='accepted'
    assert svc.acknowledge(device,command['id'],result)['duplicate']
    current=AssistantStore(store).read('assistant_runs','alice',task['id'])
    svc.command('alice',task['id'],TaskCommand(action='cancel',expected_revision=current['revision']))
    assert svc.poll(device)['commands']==[] and svc.poll(device)['activeTaskIds']==[]


def test_timeout_recovery_is_attention_not_completion(environment):
    store,_=environment;sites=Connections(store)
    site=sites.create('alice',ConnectionCreate(label='Study',origin='https://study.example.org'));sites.pair('alice',site['id'])
    task=AssistantService(store).create('alice',TaskCreate(message='Open https://study.example.org',connection_id=site['id']))
    worker=AssistantWorker(store);worker.tick()
    with store.engine.begin() as conn:conn.execute(text('UPDATE assistant_steps SET expires_at=0'))
    worker.recover();result=worker.repo.read('assistant_runs','alice',task['id'])
    assert result['status']=='waiting_for_device' and result['error']=='device_offline'
    assert result['facts']==[]


def test_new_source_revision_supersedes_and_repeated_import_is_noop(environment):
    store,course=environment;svc=AcademicPlanningService(store)
    base={'kind':'assessment','externalId':'exam-1','origin':'browser','fields':{'title':'Midterm','date':{'kind':'date_only','value':'2027-02-10'}},'source':{'locator':'https://study.example.org/syllabus','connectionId':'one','revision':'1'},'idempotencyKey':'one','observedAt':'2026-10-01T00:00:00Z'}
    first=svc.ingest('alice',course,base);assert svc.ingest('alice',course,base)['revision']==first['revision']
    changed={**base,'fields':{**base['fields'],'date':{'kind':'date_only','value':'2027-02-12'}},'source':{**base['source'],'revision':'2'},'idempotencyKey':'two','observedAt':'2026-10-02T00:00:00Z'}
    newer=svc.ingest('alice',course,changed)
    assert not newer['facts']['date']['conflict'] and newer['facts']['date']['value']['value']=='2027-02-12'
    competing={**changed,'source':{**changed['source'],'locator':'https://study.example.org/announcement'},'idempotencyKey':'three','fields':{'date':{'kind':'date_only','value':'2027-02-15'}}}
    assert svc.ingest('alice',course,competing)['facts']['date']['conflict']


def test_reminder_revision_dedup_and_revocation(environment,monkeypatch):
    store,course=environment;svc=AcademicPlanningService(store)
    now=time.time();from datetime import datetime,timezone
    date=datetime.fromtimestamp(now+3600,timezone.utc).isoformat()
    item=svc.ingest('alice',course,{'kind':'assessment','externalId':'exam','fields':{'title':'Midterm','date':{'kind':'instant','value':date}},'source':{'locator':'manual:exam','revision':'1'},'idempotencyKey':'one'})
    policy=create_policy(store,'alice',ReminderPolicyInput(course_id=course,offsets_minutes=[60],quiet_start=0,quiet_end=0))
    with store.transaction() as conn:rebuild(store,conn,'alice',item);rebuild(store,conn,'alice',item)
    tick_reminders(store);tick_reminders(store)
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM reminders')).scalar()==1
        assert conn.execute(text('SELECT count(*) FROM notification_deliveries')).scalar()==1
    create_policy(store,'alice',ReminderPolicyInput(course_id=course,active=False,expected_revision=policy['revision']),policy['id'])
    from backend.app.browser_assistant.reminders import valid_reminder
    with store.engine.connect() as conn:assert not valid_reminder(conn,dict(conn.execute(text('SELECT * FROM reminders')).mappings().one()))


def test_dst_gap_and_uncertain_dates_never_schedule():
    entity={'facts':{'date':{'value':{'kind':'date_only','value':'2027-03-14'}}}}
    assert event_instant(entity,{'dateOnlyTime':'02:30','timezone':'America/Los_Angeles'}) is None
    assert event_instant(entity,{'timezone':'America/Los_Angeles'}) is None
    assert not date_supported(DateValue(kind='instant',value='2027-02-10T17:00:00Z'),'Exam on 2027-02-10')
    assert not date_supported(DateValue(kind='date_only',value='2027-02-10'),'Midterm February 10')


@pytest.mark.parametrize('url',['http://study.example.org','https://127.0.0.1','https://10.1.1.1','https://localhost','https://u:p@example.org','https://study.example.org:8443'])
def test_connection_rejects_private_origins(url):
    with pytest.raises(HTTPException):origin(url)


def test_action_and_evidence_cannot_expand_scope():
    connection={'origin':'https://study.example.org','approvedOrigins':[]}
    snap={'id':'s','controls':[{'ref':'x','name':'Submit exam','writable':False}],'blocks':[{'ref':'b','text':'Midterm February 10, 2027'}]}
    with pytest.raises(HTTPException):authorize_action(BrowserAction(tool='click',snapshot_id='s',element_ref='x'),connection,snap)
    with pytest.raises(HTTPException):authorize_action(BrowserAction(tool='navigate',url='https://attacker.example.org'),connection,snap)
    with pytest.raises(HTTPException):validate_candidate(EvidenceCandidate(kind='assessment',title='Exam',snapshot_id='s',block_ref='b',quote='Fake exam 2027-02-10'),[snap])
    assert not fallback_intent('Open Canvas but do not save or remind me').save
    assert not fallback_intent('Open Canvas but do not save or remind me').reminder_requested

def test_api_owner_device_scope_and_event_replay(environment):
    store,_=environment
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.browser_assistant.routes import build_assistant_router
    app=FastAPI();app.include_router(build_assistant_router(lambda:store));app.add_middleware(IdentityMiddleware,store_provider=lambda:store)
    client=TestClient(app);headers={'X-Dev-Learner-Id':'alice'}
    response=client.post('/v1/site-connections',headers=headers,json={'label':'Study','origin':'https://study.example.org'})
    assert response.status_code==201
    site=response.json();grant=client.post(f"/v1/site-connections/{site['id']}/pair",headers=headers).json()
    device={'Authorization':'Bearer '+grant['authToken']}
    assert client.get('/v1/site-connections',headers=device).status_code==403
    assert client.get('/v1/browser-devices/commands',headers=device).status_code==200
    task=client.post('/v1/assistant/tasks',headers={**headers,'Idempotency-Key':'api-task'},json={'message':'Open https://study.example.org','connectionId':site['id']}).json()
    assert client.get('/v1/assistant/tasks/'+task['id'],headers={'X-Dev-Learner-Id':'bob'}).status_code==404
    events=client.get('/v1/assistant/tasks/'+task['id']+'/events',headers=headers).json()['events']
    assert [e['sequence'] for e in events]==[1]
    assert client.get('/v1/assistant/tasks/'+task['id']+'/events?after=1',headers=headers).json()['events']==[]
    assert client.patch('/v1/site-connections/'+site['id'],headers=headers,json={'expectedRevision':site['revision'],'preferred':True}).status_code==409
    assert client.post('/v1/site-connections/'+site['id']+'/cloud-login',headers=headers,json={'expectedRevision':2}).status_code==422
    assert client.delete('/v1/site-connections/'+site['id'],headers=headers).status_code==200
    assert client.get('/v1/browser-devices/commands',headers=device).status_code==401


def test_cloud_browser_requires_verified_bounded_lifecycle(monkeypatch):
    monkeypatch.setenv('OPENLEARN_USAGE_MODE','enforce')
    monkeypatch.setenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED','true')
    monkeypatch.setenv('OPENLEARN_PROVIDER_RATE_VERSION','browser-test-rates-v1')
    monkeypatch.setenv('OPENLEARN_PLATFORM_DAILY_BUDGET_USD','10')
    monkeypatch.setenv('OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD','100')
    monkeypatch.setenv('OPENLEARN_CLOUD_BROWSER_ENABLED','true')
    monkeypatch.setenv('OPENLEARN_BROWSERBASE_USD_PER_MINUTE','0.12')
    monkeypatch.setenv('BROWSERBASE_API_KEY','test-key')
    monkeypatch.setenv('BROWSERBASE_PROJECT_ID','test-project')
    monkeypatch.setenv('OPENLEARN_BROWSER_EGRESS_VERIFIED','true')
    monkeypatch.setenv('OPENLEARN_BROWSER_LIFECYCLE_VERIFIED','false')
    monkeypatch.setenv('OPENLEARN_SANDBOX_ENABLED','false')
    monkeypatch.setenv('AI_TUTOR_WEB_EVIDENCE','false')
    monkeypatch.setenv('AI_TUTOR_MODE_CLASSIFICATION','rules')
    monkeypatch.setenv('AI_TUTOR_EMBEDDING_MODEL','')
    from backend.app.browser_assistant.executors.cloud import readiness, require_cloud_ready
    from fastapi import HTTPException
    assert readiness()['lifecycleVerified'] is False
    with pytest.raises(HTTPException) as error:
        require_cloud_ready()
    assert error.value.detail['code']=='capability_unavailable'


def test_export_and_erasure_remove_credentials_and_queue_provider_cleanup(environment):
    store,_=environment
    from backend.app.identity_data import export_owner,erase_owner,cleanup_objects
    from backend.app.browser_assistant.evidence import retain_snapshot
    site=Connections(store).create('alice',ConnectionCreate(label='Cloud',origin='https://study.example.org',executor='cloud'))
    task=AssistantService(store).create('alice',TaskCreate(message='Read the website',connection_id=site['id']))
    with store.engine.begin() as conn:
        data=json.loads(conn.execute(text('SELECT payload FROM site_connections WHERE id=:id'),{'id':site['id']}).scalar_one());data['providerContextId']='PRIVATE_CONTEXT'
        conn.execute(text('UPDATE site_connections SET payload=:data WHERE id=:id'),{'data':json.dumps(data),'id':site['id']})
        conn.execute(text("INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload) VALUES('lease','alice',:run,:connection,'SESSION','active',:expires,:payload)"),{'run':task['id'],'connection':site['id'],'expires':time.time()+600,'payload':json.dumps({'connectUrl':'SECRET_URL'})})
        conn.execute(text("INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at) VALUES('alice','hash','Alice','active',:now)"),{'now':time.time()})
    exported=export_owner(store,'alice');assert 'PRIVATE_CONTEXT' not in json.dumps(exported) and 'SECRET_URL' not in json.dumps(exported)
    erase_owner(store,'alice')
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM site_connections')).scalar()==0
        assert conn.execute(text('SELECT count(*) FROM browser_provider_cleanup')).scalar()==2
        assert conn.execute(text("SELECT status FROM identity_accounts WHERE id='alice'")).scalar()=='deleted'
    with pytest.raises(HTTPException):AssistantService(store).create('alice',TaskCreate(message='Open website'))


def test_visual_transcription_cannot_trigger_precise_reminders():
    fact=EvidenceCandidate(kind='assessment',title='Midterm',snapshot_id='s',block_ref='vision',quote='Midterm February 10, 2027',date=DateValue(kind='date_only',value='2027-02-10'),image_region=[0,.2,.5,.3],confirmation='confirmed')
    validate_candidate(fact,[{'id':'s','imageObject':'image','blocks':[]}]);assert fact.confirmation=='tentative'
    entity={'facts':{'date':{'value':fact.date.model_dump(),'source':{'extractionMethod':'visual_needs_review'}}}}
    assert event_instant(entity,{'dateOnlyTime':'09:00','timezone':'America/Los_Angeles'}) is None


def test_model_reads_beyond_first_extraction(environment):
    store,course=environment
    class Provider:
        def complete_json(self,prompt,*args,**kwargs):
            if prompt.startswith('Classify'):return TaskIntent(goal='Find midterms',operations=['browse','save_academic_facts'],save=True).model_dump(by_alias=True)
            state=json.loads(prompt.split('TASK STATE AND OBSERVATIONS:\n')[1]);run=state['task'];snap=state['observations'][-1]
            if not run['facts']:
                return {'kind':'evidence','facts':[{'kind':'assessment','title':'Midterm','snapshotId':snap['id'],'blockRef':'b0','quote':'Midterm February 10, 2027','date':{'kind':'date_only','value':'2027-02-10'},'confirmation':'confirmed'}]}
            if len(run['visited'])==1:return {'kind':'action','action':{'tool':'navigate','url':'https://study.example.org/announcements'}}
            return {'kind':'finish','summary':'Checked the syllabus and announcements.'}
    class Pages:
        def execute(self,action,connection,run,previous):return Observation(url=action.url or connection['origin'],document_revision=action.url or '1',complete=True,blocks=[TextBlock(ref='b0',text='Midterm February 10, 2027')])
    site=Connections(store).create('alice',ConnectionCreate(label='Study',origin='https://study.example.org',executor='cloud'))
    task=AssistantService(store).create('alice',TaskCreate(message='Open the website and save my midterms',course_id=course,connection_id=site['id']))
    result=run_to_end(AssistantWorker(store,provider_getter=lambda:Provider(),executor_factory=lambda _:Pages()),task['id'])
    assert result['status']=='completed' and len(result['visited'])==2 and len(result['facts'])==1

def test_reminder_followup_is_limited_to_prior_task_entities(environment):
    store,course=environment
    from backend.app.browser_assistant.intent import compile_intent
    prior={'id':'previous','message':'Save my midterms','facts':[{'entityId':'exam-a'}]}
    result=compile_intent('Also remind me two hours before those',previous=prior)
    assert result.handled and result.reminder_requested and 'query_saved' in result.operations
    entity={'id':'exam-b','courseId':course,'kind':'assessment','revision':1,'facts':{'date':{'value':{'kind':'instant','value':'2027-02-10T17:00:00Z'}}}}
    policy=create_policy(store,'alice',ReminderPolicyInput(entity_ids=['exam-a'],offsets_minutes=[120]))
    with store.transaction() as conn:rebuild(store,conn,'alice',entity)
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM reminders')).scalar()==0


def test_refresh_schedule_enqueues_atomically(environment):
    store,_=environment
    site=Connections(store).create('alice',ConnectionCreate(label='Public site',origin='https://study.example.org',executor='public_fetch'))
    with store.engine.begin() as conn:
        conn.execute(text("INSERT INTO connection_refresh_schedules(id,owner_id,connection_id,revision,active,next_due,payload) VALUES('schedule','alice',:connection,1,true,0,:payload)"),{'connection':site['id'],'payload':json.dumps({'message':'Check website updates','intervalHours':24})})
    worker=AssistantWorker(store);worker.refresh_due();worker.refresh_due()
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar()==1
        assert conn.execute(text('SELECT count(*) FROM learning_jobs')).scalar()==1
        assert conn.execute(text('SELECT next_due FROM connection_refresh_schedules')).scalar()>time.time()

def test_date_correction_replaces_pending_reminder_and_disconnect_preserves_override(environment):
    store,course=environment;svc=AcademicPlanningService(store)
    site=Connections(store).create('alice',ConnectionCreate(label='Study',origin='https://study.example.org',executor='public_fetch'))
    item=svc.ingest('alice',course,{'kind':'assessment','externalId':'one','origin':'browser','fields':{'title':'Midterm','date':{'kind':'instant','value':'2027-02-10T17:00:00Z'}},'source':{'locator':'https://study.example.org/syllabus','revision':'1','connectionId':site['id']},'idempotencyKey':'one'})
    create_policy(store,'alice',ReminderPolicyInput(course_id=course,quiet_start=0,quiet_end=0));tick_reminders(store)
    corrected=svc.ingest('alice',course,{'kind':'assessment','entityId':item['id'],'fields':{'date':{'kind':'instant','value':'2027-02-12T17:00:00Z'}},'source':{'locator':'manual:correction','revision':'1'},'override':True,'idempotencyKey':'correction'})
    tick_reminders(store)
    with store.engine.connect() as conn:
        rows=conn.execute(text('SELECT entity_revision,status FROM reminders ORDER BY entity_revision')).all()
        assert rows==[(1,'cancelled'),(corrected['revision'],'pending')]
    Connections(store).revoke('alice',site['id'],delete_imports=True)
    kept=svc.view('alice',course)['entities'][0]
    assert kept['facts']['date']['value']['value']=='2027-02-12T17:00:00Z'
    assert len(svc.view('alice',course)['observations'])==1


def test_precise_dates_cannot_combine_parts_of_unrelated_dates():
    assert not date_supported(DateValue(kind='date_only',value='2027-02-10'),'Midterm February 10, 2026; final November 20, 2027')

def test_reclaimed_cloud_command_observes_before_continuing(environment):
    store,_=environment
    class Provider:
        def complete_json(self,prompt,*args,**kwargs):
            if prompt.startswith('Classify'):return TaskIntent(goal='Read linked page',operations=['browse','summarize']).model_dump(by_alias=True)
            data=json.loads(prompt.split('TASK STATE AND OBSERVATIONS:\n')[1]);snapshot=data['observations'][-1]
            if snapshot['url'].endswith('/destination'):return {'kind':'finish','summary':'Read the destination.'}
            return {'kind':'action','action':{'tool':'click','snapshotId':snapshot['id'],'elementRef':'e0'}}
    class Pages:
        def __init__(self):self.tools=[]
        def execute(self,action,connection,run,previous):
            self.tools.append(action.tool)
            if action.tool=='click':raise SystemExit('simulated worker loss after click')
            if action.tool=='observe':return Observation(url=connection['origin']+'/destination',document_revision='dest',complete=True)
            return Observation(url=connection['origin'],document_revision='home',complete=True,controls=[Control(ref='e0',name='Syllabus',role='link',href=connection['origin']+'/destination')])
    pages=Pages();site=Connections(store).create('alice',ConnectionCreate(label='Study',origin='https://study.example.org',executor='cloud'))
    task=AssistantService(store).create('alice',TaskCreate(message='Open the website',connection_id=site['id']))
    worker=AssistantWorker(store,provider_getter=lambda:Provider(),executor_factory=lambda _:pages)
    worker.tick()
    with pytest.raises(SystemExit):worker.tick()
    with store.engine.begin() as conn:conn.execute(text("UPDATE learning_jobs SET expires=0 WHERE status='running'"))
    result=run_to_end(worker,task['id'])
    assert result['status']=='completed' and pages.tools==['navigate','click','observe']
