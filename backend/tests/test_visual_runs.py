import time
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.session_models import LearningSession, LessonArtifact, LessonBlock
from backend.app.models import utc_now
from backend.app.visual_runs import VisualRuns, run_visual_job
from backend.app.workflow_store import WorkflowStore
from backend.app.openintelligentui import GeneratedVisual, extract_controls
from backend.app.visualization_service import VisualChange


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = Store(tmp_path / 'visuals.db')
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO topic_scopes(id,payload) VALUES('scope-test','{}')"))
        conn.execute(text("INSERT INTO graph_versions(id,scope_id,payload) VALUES('graph-test','scope-test','{}')"))
    now=utc_now()
    store.save_session(LearningSession(id='session-test', graph_id='graph-test', created_at=now, updated_at=now))
    artifact=LessonArtifact(id='lesson-test',session_id='session-test',concept_id='concept-test',gear='Quick',title='Force',
                           blocks=[LessonBlock(id='block-test',kind='explanation',body='Force is mass times acceleration.',order=0)])
    store.save_artifact(artifact)
    # Tests exercise run/lease ownership separately from account provisioning.
    monkeypatch.setattr('backend.app.identity.assert_principal_active', lambda *args: None)
    service=VisualRuns(store)
    with store.transaction() as conn:
        run=service.admit(conn,'local','session-test','lesson-test',{'title':'Force','sources':[]},'Explain force','visual-key')
    yield store,service,run
    store.close()


def visual():
    html='<label>Mass <input id="mass" aria-label="Mass" type="range" min="1" max="10" value="2"></label><p>Force</p>'
    return GeneratedVisual(id='temporary',renderer='open_generative_ui',title='Force',
        content={'html':[html],'htmlComplete':True,'cssComplete':True,'generating':False},controls=extract_controls(html)).model_dump(mode='json',by_alias=True)


def test_durable_admission_idempotency_and_owner(setup):
    store,service,run=setup
    with store.transaction() as conn:
        duplicate=service.admit(conn,'local','session-test','lesson-test',{'title':'Force'},'Explain force','visual-key')
    assert duplicate['id']==run['id']
    assert VisualRuns(Store(store.url)).listing('local','lesson-test')[0]['phase']=='queued'
    with pytest.raises(HTTPException):service.read('another-owner',run['id'])


def test_restart_commits_saved_candidate_without_provider(setup,monkeypatch):
    store,service,run=setup
    records=WorkflowStore(store)
    job=records.claim(run['jobId'],lease_seconds=240)
    service.update(job,phase='generated',candidates=[visual()])
    with store.transaction() as conn:
        conn.execute(text('UPDATE learning_jobs SET expires=:expired WHERE id=:id'),{'expired':time.time()-1,'id':job['id']})
    async def forbidden(*args):raise AssertionError('Recovery must not bill another model call')
    monkeypatch.setattr('backend.app.visual_runs.generate',forbidden)
    run_visual_job(store,None,job['id'])
    assert records.job('local',job['id'])['status']=='completed'
    final=service.listing('local','lesson-test')[0]
    assert final['phase']=='completed'
    ref=store.get_artifact('lesson-test').blocks[0].visualizations[0]
    assert ref['type']=='generated_ui_ref'
    assert 'content' not in ref
    assert records.read('local',ref['id'],'generated_visual')['spec']['content']['html']


def test_restart_mid_provider_requires_explicit_retry(setup,monkeypatch):
    store,service,run=setup
    records=WorkflowStore(store);job=records.claim(run['jobId'])
    service.update(job,phase='running')
    with store.transaction() as conn:
        conn.execute(text('UPDATE learning_jobs SET expires=:expired WHERE id=:id'),{'expired':time.time()-1,'id':job['id']})
    async def forbidden(*args):raise AssertionError('Interrupted runs cannot auto-regenerate')
    monkeypatch.setattr('backend.app.visual_runs.generate',forbidden)
    run_visual_job(store,None,job['id'])
    assert records.job('local',job['id'])['status']=='failed'
    retry=service.retry('local',run['id'],'retry-key')
    assert retry['jobId']!=run['jobId']
    assert service.retry('local',run['id'],'retry-key')['jobId']==retry['jobId']


def test_cancelled_lease_cannot_attach_visual(setup):
    store,service,run=setup; records=WorkflowStore(store)
    job=records.claim(run['jobId']);service.cancel('local',run['id'])
    with pytest.raises(HTTPException):service.update(job,phase='generated',candidates=[visual()])
    assert not store.get_artifact('lesson-test').blocks[0].visualizations


def test_numeric_revisions_reject_stale_and_out_of_range(setup):
    store,service,run=setup;records=WorkflowStore(store);job=records.claim(run['jobId'])
    with store.transaction() as conn:
        service.commit(conn,job,[visual()]);records.finish(conn,job,{})
    ref=store.get_artifact('lesson-test').blocks[0].visualizations[0]
    changed=service.change('local','lesson-test',ref['id'],VisualChange(operation='change_parameter',expected_revision=1,parameter_id='mass',value=5))
    assert changed.revision==2 and changed.control_values=={'mass':5}
    assert store.get_artifact('lesson-test').blocks[0].visualizations[0]['revision']==2
    assert len(records.listing_by_parent('local','visual_revision',ref['id']))==2
    from backend.app.voice.tools import Tools
    context=Tools(store,None).visual_context('local',{'lesson_id':'lesson-test','visualization_id':ref['id']})
    assert context['revision']==2 and context['controls'][0]['current']==5
    assert 'content' not in context
    with pytest.raises(HTTPException):service.change('local','lesson-test',ref['id'],VisualChange(operation='change_parameter',expected_revision=1,parameter_id='mass',value=6))
    with pytest.raises(HTTPException):service.change('local','lesson-test',ref['id'],VisualChange(operation='change_parameter',expected_revision=2,parameter_id='mass',value=50))


def test_control_manifest_rejects_unbounded_and_unsafe_input_ids():
    assert extract_controls('<input id="password" type="password" value="secret">')==[]
    assert extract_controls('<input id="unsafe.id" type="range" min="1" max="10" value="2">')==[]
    assert extract_controls('<input id="mass" type="range" min="NaN" max="10" value="2">')==[]


def test_visual_brief_contains_explanation_and_exact_prior_table_without_code(setup):
    store,service,run=setup;records=WorkflowStore(store)
    with store.transaction() as conn:
        records.put(conn,'local','generated_visual',{'id':'table-owned','sessionId':'session-test','lessonId':'lesson-test',
            'spec':{'id':'table-owned','title':'Values','revision':1,'renderer':'a2ui','content':{'title':'Values','columns':['Mass'],'rows':[['5']],'source':'User data'}}},'lesson-test')
        records.put(conn,'local','journey',{'id':'journey_session-test','sessionId':'session-test','turns':[
            {'question':'Compare masses','lesson':{'id':'lesson-test','blocks':[{'body':'The mass is 5 kg.','visualizations':[{'type':'generated_ui_ref','id':'table-owned'}]}]}}]},'session-test')
        admitted=service.admit(conn,'local','session-test','lesson-test',{'title':'Compare'},'Turn that into a chart','chart-context')
    assert admitted['brief']['explanation']=='Force is mass times acceleration.'
    assert admitted['brief']['conversation'][-1]['content']=='The mass is 5 kg.'
    assert admitted['brief']['priorVisuals'][0]['table']['rows']==[['5']]
    from backend.app.visual_context import readable_html
    assert 'secret()' not in readable_html('<script>secret()</script><p>Mass 5 kg</p>')
