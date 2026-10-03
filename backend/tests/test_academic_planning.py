"""Academic correction, pairing boundaries and feasible schedule regression tests."""
import pytest
from pathlib import Path
from uuid import uuid4
from backend.app.storage import Store
from backend.app.course_service import CourseService
from backend.app.course_models import CourseCreate
from backend.app.academic_planning import AcademicPlanningService, AcademicError
from backend.app.canvas_reader import CanvasReader
from backend.app.identity import Principal,principal_context

@pytest.fixture
def academic():
    path = Path('work') / ('academic-test-' + uuid4().hex + '.sqlite3')
    store = Store(path)
    course = CourseService(store).create_course('alice', CourseCreate(name='Linear Algebra'))
    token=principal_context.set(Principal('alice','local'))
    yield AcademicPlanningService(store), course.id
    store.close()
    principal_context.reset(token)
    path.unlink(missing_ok=True)

def test_user_override_survives_later_sync_and_partial_import(academic):
    svc, course = academic
    source = {'locator': 'https://canvas.school/courses/1/assignments/7', 'revision': '1', 'studentSpecific': True}
    item = svc.ingest('alice', course, {'kind': 'assignment','externalId':'7','origin':'canvas','fields':{'title':'Homework','due':{'kind':'date_only','value':'2026-10-10'}},'source':source,'idempotencyKey':'one'})
    svc.ingest('alice', course, {'kind':'assignment','entityId':item['id'],'fields':{'due':{'kind':'date_only','value':'2026-10-12'}},'source':{'locator':'manual:override','revision':'1'},'override':True,'reason':'Extension confirmed'})
    svc.ingest('alice', course, {'kind':'assignment','externalId':'7','origin':'canvas','fields':{'due':{'kind':'date_only','value':'2026-10-11'}},'source':dict(source,revision='2'),'idempotencyKey':'two'})
    view = svc.view('alice', course)
    assert len(view['entities']) == 1
    assert view['entities'][0]['facts']['due']['value']['value'] == '2026-10-12'
    assert len(view['observations']) == 4
    with pytest.raises(AcademicError): svc.view('bob', course)

def test_schedule_capacity_protected_time_and_stale_revision(academic):
    svc, course = academic
    tasks = [svc.create_task('alice', course, {'action':'diagnostic','conceptIds':['eigenvectors'],'reason':'Untested','duration':[8,15]}) for _ in range(2)]
    plan = svc.plan('alice',course,{'timezone':'America/Los_Angeles','windows':[{'start':'2026-11-01T01:00:00-07:00','end':'2026-11-01T01:30:00-07:00'}],'protected':[{'start':'2026-11-01T01:20:00-07:00','end':'2026-11-01T01:30:00-07:00'}]})
    assert len(plan['blocks']) == 1 and len(plan['capacityGaps']) == 1
    assert plan['blocks'][0]['end']-plan['blocks'][0]['start'] == 900
    svc.accept_plan('alice',course,plan['id'],plan['revision'])
    with pytest.raises(AcademicError): svc.accept_plan('alice',course,plan['id'],plan['revision'])

def test_canvas_binding_revocation_and_unknown_scope(academic):
    svc, course = academic
    canvas = CanvasReader(svc.store)
    pair = canvas.pair('alice',{'origin':'https://canvas.school','deviceId':'device','courses':{'1':course}})
    command = {'origin':'https://canvas.school','deviceId':'wrong','externalCourseId':'1','courseId':course,'grant':pair['grant'],'skill':'assignments','items':[],'complete':False,'status':'partial'}
    with pytest.raises(AcademicError): canvas.sync('alice',pair['id'],command)
    command['deviceId']=pair['deviceId']
    assert canvas.sync('alice',pair['id'],command)['run']['deletionsInferred'] is False
    canvas.disconnect('alice',pair['id'])
    with pytest.raises(AcademicError): canvas.sync('alice',pair['id'],command)
    exam = svc.ingest('alice',course,{'kind':'assessment','fields':{'title':'Final'},'source':{'locator':'manual:exam','revision':'1'}})
    assert svc.readiness('alice',course,exam['id'])['unknownScope'] is True
