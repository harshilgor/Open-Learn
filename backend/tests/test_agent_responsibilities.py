import json,time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_agent_execution import env
from backend.app.course_service import CourseService
from backend.app.course_models import CourseCreate
from backend.app.agent_execution.responsibilities import Responsibilities,ResponsibilitySpec,occurrences
from backend.app.agent_execution.worker import AgentWorker

@pytest.fixture
def context(env):
    store,_,_=env
    course=CourseService(store).create_course('alice',CourseCreate(name='Physics'))
    with store.transaction() as conn:conn.execute(text('UPDATE learning_sessions SET course_id=:course WHERE id=\'session\''),{'course':course.id})
    svc=Responsibilities(store)
    spec=ResponsibilitySpec(sessionId='session',courseId=course.id,goal='Prepare physics review',schedule='once',wakeAt=time.time()+20,lectureEvents=False)
    return store,svc,spec

def test_dst_gap_and_fold_once():
    spec=ResponsibilitySpec(sessionId='s',courseId='c',goal='g',weekday=6,hour=2,minute=30)
    dates=occurrences(spec,datetime(2026,3,7,tzinfo=timezone.utc).timestamp())
    local=datetime.fromtimestamp(dates[0],ZoneInfo(spec.timezone))
    assert (local.hour,local.minute)==(3,0)
    spec=spec.model_copy(update={'hour':1})
    dates=occurrences(spec,datetime(2026,10,31,tzinfo=timezone.utc).timestamp())
    assert datetime.fromtimestamp(dates[0],ZoneInfo(spec.timezone)).fold==0
    assert dates[1]-dates[0]>6*86400

def test_idempotent_due_and_real_outbox_dispatch(context):
    store,svc,spec=context
    first=svc.create('alice',spec,'key')
    assert svc.create('alice',spec,'key')['id']==first['id']
    now=spec.wakeAt+1
    svc.tick(now=now);svc.tick(now=now)
    with store.engine.connect() as conn:
        rows=conn.execute(text('SELECT * FROM agent_responsibility_occurrences')).mappings().all()
        assert len(rows)==1 and rows[0]['run_id']
    AgentWorker(store).tick()
    assert svc.repo.read('alice',rows[0]['run_id'])['status']!='queued'

def test_overlap_budget_and_self_causation(context):
    store,svc,spec=context
    item=svc.create('alice',spec.model_copy(update={'maxRunsPerWeek':1}),'k')
    now=time.time()
    with svc.repo.transaction() as conn:
        row=svc.row(conn,'alice',item['id'])
        svc.trigger(conn,row,'one',now)
        svc.trigger(conn,row,'two',now)
        svc.trigger(conn,row,'self',now,causation=row['id'])
    with store.engine.connect() as conn:
        rows=conn.execute(text('SELECT * FROM agent_responsibility_occurrences ORDER BY created_at')).mappings().all()
        assert len(rows)==2 and {r['status'] for r in rows}=={'started','overlap_skipped'}
    run=svc.repo.read('alice',next(r['run_id'] for r in rows if r['run_id']))
    with svc.repo.transaction() as conn:
        svc.repo.update(conn,run,status='completed')
        svc.trigger(conn,svc.row(conn,'alice',item['id']),'three',now)
    with store.engine.connect() as conn:assert conn.execute(text("SELECT count(*) FROM agent_responsibility_occurrences WHERE status='budget_exhausted'")).scalar_one()==1

def test_disable_pause_resume_stop_and_steer(context):
    store,svc,spec=context
    item=svc.create('alice',spec,'k');svc.tick(now=spec.wakeAt+1)
    with store.engine.connect() as conn:run_id=conn.execute(text('SELECT run_id FROM agent_responsibility_occurrences')).scalar_one()
    item=svc.control('alice',item['id'],item['revision'],'disable')
    assert svc.repo.read('alice',run_id)['status']=='queued'
    item=svc.control('alice',item['id'],item['revision'],'pause')
    assert svc.repo.read('alice',run_id)['status']=='paused'
    item=svc.control('alice',item['id'],item['revision'],'resume')
    assert svc.repo.read('alice',run_id)['status']=='queued'
    item=svc.control('alice',item['id'],item['revision'],'edit',spec.model_copy(update={'goal':'Updated goal'}))
    assert svc.repo.read('alice',run_id)['status']=='cancelled'
    item=svc.control('alice',item['id'],item['revision'],'stop_all')
    with pytest.raises(HTTPException):svc.control('alice',item['id'],item['revision'],'resume')

def test_owner_scope_notes_and_notification_dedupe(context):
    store,svc,spec=context
    item=svc.create('alice',spec,'k')
    with pytest.raises(HTTPException):svc.control('bob',item['id'],1,'pause')
    note=svc.note('alice',item['id'],'Keep the review short')[0]
    with pytest.raises(HTTPException):svc.note('alice',item['id'],'changed',note['id'],0)
    assert svc.note('alice',item['id'],'Focus on units',note['id'],1)[0]['revision']==2
    svc.delete_note('alice',item['id'],note['id'],2)
    assert not svc.notes('alice',item['id'])
    svc.tick(now=spec.wakeAt+1)
    with store.engine.connect() as conn:run_id=conn.execute(text('SELECT run_id FROM agent_responsibility_occurrences')).scalar_one()
    with svc.repo.transaction() as conn:svc.repo.update(conn,svc.repo.run(conn,'alice',run_id),status='completed')
    svc.notify(time.time());svc.notify(time.time())
    with store.engine.connect() as conn:assert conn.execute(text("SELECT count(*) FROM notification_deliveries WHERE channel='inbox'")).scalar_one()==1

def test_push_quiet_hours_and_revoked_token(context):
    store,svc,spec=context
    item=svc.create('alice',spec.model_copy(update={'expoPush':True}),'k');svc.tick(now=spec.wakeAt+1)
    with store.engine.connect() as conn:run_id=conn.execute(text('SELECT run_id FROM agent_responsibility_occurrences')).scalar_one()
    with svc.repo.transaction() as conn:
        svc.repo.update(conn,svc.repo.run(conn,'alice',run_id),status='completed')
        conn.execute(text("INSERT INTO notification_subscriptions(id,owner_id,endpoint_hash,active,payload) VALUES('token','alice','hash',true,:payload)"),{'payload':json.dumps({'kind':'expo','token':'ExpoPushToken[test]'})})
    night=datetime.now(ZoneInfo(spec.timezone)).replace(hour=23).timestamp();svc.notify(night)
    calls=[]
    def sender(token,payload):calls.append(token);return {'status':'error','details':{'error':'DeviceNotRegistered'}}
    svc.deliver(night,sender);assert not calls
    day=datetime.fromtimestamp(night,ZoneInfo(spec.timezone)).replace(hour=10).timestamp()
    svc.deliver(day,sender);assert len(calls)==1
    svc.deliver(day,sender);assert len(calls)==1
    with store.engine.connect() as conn:assert not conn.execute(text("SELECT active FROM notification_subscriptions WHERE id='token'")).scalar_one()

def test_finalized_lecture_once_and_revision_does_not_replay_history(context):
    from backend.app.lecture_service import LectureService
    from backend.app.lecture_models import LectureCreate
    store,svc,spec=context
    item=svc.create('alice',spec.model_copy(update={'schedule':'events','lectureEvents':True}),'event')
    lecture=LectureService(store).create('alice',LectureCreate(id='rec_'+'a'*32,title='Physics',courseId=spec.courseId,startedAtMs=1000))
    with store.transaction() as conn:conn.execute(text("UPDATE lecture_recordings SET status='completed',updated_at=:now WHERE id=:id"),{'id':lecture['id'],'now':time.time()})
    svc.tick();svc.tick()
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM agent_responsibility_occurrences')).scalar_one()==1
    svc.control('alice',item['id'],item['revision'],'edit',spec.model_copy(update={'schedule':'events','lectureEvents':True,'goal':'New prep'}))
    svc.tick()
    with store.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM agent_responsibility_occurrences')).scalar_one()==1

def test_http_routes_preview_controls_and_notes(context):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.identity import Principal,principal_context
    from backend.app.agent_execution.routes import build_agent_router
    store,svc,spec=context
    app=FastAPI();app.include_router(build_agent_router(lambda:store))
    token=principal_context.set(Principal('alice','local'))
    try:
        with TestClient(app) as client:
            assert client.post('/v1/assistant/responsibilities/preview',json=spec.model_dump()).status_code==200
            created=client.post('/v1/assistant/responsibilities',json=spec.model_dump(),headers={'Idempotency-Key':'api'})
            assert created.status_code==201
            item=created.json()
            assert client.post('/v1/assistant/responsibilities/'+item['id']+'/notes',json={'text':'Short review'}).status_code==200
            assert client.post('/v1/assistant/responsibilities/'+item['id']+'/commands',json={'action':'pause','expectedRevision':item['revision']}).status_code==200
    finally:principal_context.reset(token)


def test_restart_fairness_and_account_export_delete(context):
    from backend.app.identity_data import export_owner,erase_owner
    from backend.app.identity_import import OMIT
    store,svc,spec=context
    first=svc.create('alice',spec.model_copy(update={'schedule':'events'}),'first')
    second=svc.create('alice',spec.model_copy(update={'schedule':'events'}),'second')
    svc.note('alice',first['id'],'Keep it short')
    now=time.time()
    Responsibilities(store).tick(limit=1,now=now)
    Responsibilities(store).tick(limit=1,now=now+1)
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_responsibilities WHERE last_checked>0')).scalar_one()==2
    exported=export_owner(store,'alice')
    assert len(exported['tables']['agent_responsibilities'])==2
    assert exported['tables']['agent_operational_notes'][0]['owner_id']=='alice'
    assert {'agent_responsibilities','agent_responsibility_occurrences','agent_operational_notes'}<=OMIT
    erase_owner(store,'alice')
    Responsibilities(store).tick()
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_responsibilities')).scalar_one()==0
        assert conn.execute(text('SELECT count(*) FROM agent_operational_notes')).scalar_one()==0


def test_push_receipt_failure_is_not_hidden_by_missing_receipt(context):
    store,svc,spec=context
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES('receipt','alice','receipt','expo','ticket_accepted',:payload,:now)"),{'payload':json.dumps({'tickets':[{'id':'failed','subscriptionId':'one'},{'id':'missing','subscriptionId':'two'}]}),'now':time.time()})
    svc.receipts(time.time(),lambda ids:{'failed':{'status':'error'}})
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM notification_deliveries WHERE id='receipt'")).scalar_one()=='failed'
