import hashlib,json
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.in_class_models import ClassCreate,ClassCommand
from backend.app.in_class_service import InClassService
from backend.app.lecture_service import LectureService
from backend.app.lecture_models import LectureFinalize
from backend.app.lecture_pipeline import transcribe_chunk
from backend.app.lecture_provider import TranscribedSpan,TranscriptionResult
from backend.app.lecture_observations import LectureObservationService

class Provider:
    def complete_json(self,prompt,tokens=4000):
        if prompt.startswith('FLASHCARD_AUTHOR_V1'):
            payload=json.loads(prompt.split('\n')[-1]);source=payload['sources'][0]
            return {'cards':[{'type':'qa','prompt':'What encloses a cell?','answer':'The cell membrane.','sourceIds':[source['id']],'supportQuote':source['text']}]}
        if prompt.startswith('FLASHCARD_CHECK_V1'):
            payload=json.loads(prompt.split('\n')[-1]);return {'checks':[{'index':i,'supported':True,'clear':True} for i in range(len(payload['cards']))]}
        payload=json.loads(prompt.split('\n',1)[1])
        if 'You author ONE' in prompt:
            context=payload['context']
            if payload.get('previous'):
                return {'kind':'single','stem':'Why would disrupting the nucleus interfere with regulation inside a cell?','reasoning_target':'Relate the nucleus to regulation of cell activity.','options':[{'id':'a','label':'Control loss'},{'id':'b','label':'Control gain'}],'correct_ids':['a'],'solution':'The nucleus supports regulation; damage disrupts this control.','criteria':[{'id':'r1','description':'Predicts disrupted regulation from damage','weight':1}],'hints':['Consider the role of the nucleus.'],'concept_id':context['conceptIds'][0],'family':'nucleus-regulation','source_ids':[context['sources'][0]['spanId']]}
            return {'kind':'single','stem':'Which prediction follows if the cell membrane is damaged?','reasoning_target':'Predict the consequence of damaging the cell boundary.','options':[{'id':'a','label':'Leakage'},{'id':'b','label':'Isolation'}],'correct_ids':['a'],'solution':'The damaged boundary permits leakage of cell contents.','criteria':[{'id':'r1','description':'Identifies loss of membrane containment','weight':1}],'hints':['Consider the boundary function.'],'concept_id':context['conceptIds'][0],'family':'membrane-boundary','source_ids':[context['sources'][0]['spanId']]}
        if 'Independently solve' in prompt:return {'unambiguous':True,'concept_test':True,'novel':True,'supported':True,'correct_ids':['a'],'solution':'A damaged membrane permits leakage of cell contents.'}
        evidence=payload;ids=[evidence[0]['id']]
        if '"blocks"' in prompt:return {'blocks':[{'title':'Cell structure','body':'Cells have membranes and nuclei.','segmentIds':ids}]}
        return {'items':[{'prompt':'What encloses a cell?','answer':'The cell membrane.','segmentIds':ids}]}
class Transcriber:
    def transcribe_chunk(self,content,mime,duration,previous):return TranscriptionResult('fake','test',[TranscribedSpan(0,duration,'A cell has a membrane and a nucleus.')])

@pytest.fixture
def env(monkeypatch):
    path=Path('work')/('class-tests-'+uuid4().hex);path.mkdir(parents=True)
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(path/'notes'));monkeypatch.setenv('AI_TUTOR_RECORDINGS_DIR',str(path/'audio'))
    db=Store(path/'test.sqlite');svc=InClassService(db,Provider())
    body=ClassCreate(recording={'id':'rec_'+uuid4().hex,'title':'Biology','startedAtMs':1000},deviceId='capture-device',policy={'notes':True,'materials':True,'practice':True,'flashcards':True})
    snapshot=svc.create('alice',body)
    yield db,svc,body,snapshot
    db.close()

def audio(env,sequence=0,start=0,end=30000):
    db,svc,body,_=env;content=b'\x1a\x45\xdf\xa3'+bytes([sequence])*50
    LectureService(db).put_chunk('alice',body.recording.id,sequence,content,start_ms=start,end_ms=end,media_type='audio/webm',checksum=hashlib.sha256(content).hexdigest())
    transcribe_chunk(db,'alice',body.recording.id,sequence,Transcriber())

def drain(svc):
    for _ in range(5):svc.tick(10)

def test_setup_idempotency_stable_chat_and_foreign_owner(env):
    db,svc,body,created=env
    assert svc.create('alice',body)['session']['sessionId']==created['session']['sessionId']
    with pytest.raises(HTTPException):svc.snapshot('bob',created['session']['id'])
    with pytest.raises(HTTPException):svc.create('alice',body.model_copy(update={'device_id':'second-device'}))
    with db.engine.connect() as conn:assert conn.execute(text('SELECT COUNT(*) FROM class_sessions')).scalar_one()==1

def test_live_outputs_arrive_before_stop_and_share_quiz_engine(env):
    db,svc,body,created=env;audio(env);drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    assert not snap['recording']['captureComplete'] and snap['session']['watermark']==0
    assert {o['kind'] for o in snap['outputs'] if o['status']=='ready'}=={'notes','materials','practice','flashcards'}
    quiz=next(o for o in snap['outputs'] if o['kind']=='practice')['result']['quizId']
    from backend.app.workflow_store import WorkflowStore
    stored=WorkflowStore(db).read('alice',quiz,'quiz')
    assert stored['lectureOnly'] and stored['current']
    assert len(stored['presentations'])==1 and not stored['attempts']

def test_reordered_chunks_wait_for_contiguous_transcription(env):
    _,svc,_,created=env;audio(env,1,30000,60000);drain(svc)
    assert svc.snapshot('alice',created['session']['id'])['outputs']==[]
    audio(env);drain(svc);assert svc.snapshot('alice',created['session']['id'])['session']['watermark']==1

def test_correction_supersedes_outputs_without_deleting_quiz_attempts(env):
    db,svc,body,created=env;audio(env);drain(svc);first=svc.snapshot('alice',created['session']['id']);old={o['id'] for o in first['outputs']}
    segment=first['transcript'][0]
    LectureObservationService(db).correct_transcript('alice',body.recording.id,segment['id'],'Cells have a membrane.',1)
    drain(svc);next=svc.snapshot('alice',created['session']['id'])
    assert not old & {o['id'] for o in next['outputs']}
    with db.engine.connect() as conn:assert conn.execute(text("SELECT COUNT(*) FROM practice_records WHERE kind='quiz'")).scalar_one()==2

def test_stop_produces_independent_revision_outputs(env):
    db,svc,body,created=env;audio(env)
    LectureService(db).finalize('alice',body.recording.id,LectureFinalize(expectedChunkCount=1,durationMs=30000));drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    assert {'summary','recall','revision_quiz'}<={o['kind'] for o in snap['outputs'] if o['status']=='ready'}
    assert snap['session']['processing']=='completed'

def test_processing_cancel_preserves_ready_content_and_revision_guard(env):
    _,svc,_,created=env;audio(env);drain(svc);snap=svc.snapshot('alice',created['session']['id'])
    result=svc.command('alice',snap['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='cancel_processing'))
    assert result['outputs'] and result['session']['cancelled']
    with pytest.raises(HTTPException):svc.command('alice',snap['session']['id'],ClassCommand(expectedRevision=1,action='resume_processing'))

def test_partial_package_requires_stopped_capture(env):
    _,svc,_,created=env
    with pytest.raises(HTTPException):svc.command('alice',created['session']['id'],ClassCommand(expectedRevision=created['session']['revision'],action='partial_package'))


def test_duplicate_handoffs_do_not_duplicate_presentations_or_events(env):
    db,svc,body,created=env;audio(env);drain(svc)
    first=svc.snapshot('alice',created['session']['id'])
    from backend.app.in_class_service import handoff
    with db.transaction() as conn:handoff(conn,'alice',body.recording.id,'setup')
    drain(svc)
    second=svc.snapshot('alice',created['session']['id'],first['cursor'])
    assert second['events']==[] and second['cursor']==first['cursor']
    assert [(o['id'],o['revision']) for o in second['outputs']]==[(o['id'],o['revision']) for o in first['outputs']]


def test_correction_during_provider_call_cannot_publish_stale_notes(env):
    db,svc,body,created=env;audio(env)
    delegate=svc.provider
    class CorrectingProvider:
        changed=False
        def complete_json(self,prompt,tokens=4000):
            if 'Create organized lecture notes' in prompt and not self.changed:
                self.changed=True
                segment=LectureService(db).transcript('alice',body.recording.id)[0]
                LectureObservationService(db).correct_transcript('alice',body.recording.id,segment['id'],'Corrected cell wording.',1)
            return delegate.complete_json(prompt,tokens)
    svc.provider=CorrectingProvider();svc.tick(10)
    first=svc.snapshot('alice',created['session']['id'])
    assert not any(o['kind']=='notes' and o['status']=='ready' for o in first['outputs'])
    drain(svc)
    assert any(o['kind']=='notes' and o['status']=='ready' for o in svc.snapshot('alice',created['session']['id'])['outputs'])


def test_independent_failure_and_explicit_retry(env):
    _,svc,_,created=env;audio(env)
    delegate=svc.provider
    class FailingProvider:
        def complete_json(self,prompt,tokens=4000):
            if 'Create organized lecture notes' in prompt:raise ValueError('Provider configuration invalid')
            return delegate.complete_json(prompt,tokens)
    svc.provider=FailingProvider();drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    failed=next(o for o in snap['outputs'] if o['kind']=='notes')
    assert failed['status']=='failed' and any(o['kind']=='practice' and o['status']=='ready' for o in snap['outputs'])
    svc.provider=delegate
    svc.command('alice',snap['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='retry',outputId=failed['id']))
    drain(svc)
    assert next(o for o in svc.snapshot('alice',snap['session']['id'])['outputs'] if o['id']==failed['id'])['status']=='ready'


def test_missing_audio_requires_explicit_partial_and_retains_gap(env):
    db,svc,body,created=env;audio(env,1,30000,60000)
    LectureService(db).finalize('alice',body.recording.id,LectureFinalize(expectedChunkCount=2,durationMs=60000));drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    assert not snap['outputs'] and snap['recording']['chunks']['missing']==[0]
    svc.command('alice',snap['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='partial_package'));drain(svc)
    result=svc.snapshot('alice',snap['session']['id'])
    assert result['session']['processing']=='completed-partial'
    assert result['recording']['chunks']['missing']==[0]


def test_expired_lease_cannot_publish(env):
    db,svc,body,created=env;audio(env)
    from backend.app.execution import Outbox
    Outbox(db).deliver_one({'class.transcript':svc.coordinate})
    job=svc.jobs.claim(svc.jobs.ready_ids('interactive',{'class_specialist'},1)[0])
    with db.transaction() as conn:conn.execute(text('UPDATE learning_jobs SET expires=0 WHERE id=:id'),{'id':job['id']})
    with pytest.raises(HTTPException):svc.execute(job)
    assert not any(o['status']=='ready' for o in svc.snapshot('alice',created['session']['id'])['outputs'])


def test_material_revocation_hides_copied_passages(env,monkeypatch):
    db,svc,_,created=env;audio(env);drain(svc)
    with db.transaction() as conn:
        row=conn.execute(text("select id,payload from class_output_versions where kind='materials'")).first()
        payload=json.loads(row[1]);payload['result']['sources']=[{'versionId':'revoked','spanId':'span','text':'Private source','title':'Private','pageIndex':0}]
        conn.execute(text('update class_output_versions set payload=:data where id=:id'),{'data':json.dumps(payload),'id':row[0]})
    from backend.app.material_service import MaterialService
    def unavailable(*args,**kwargs):raise HTTPException(404,'unavailable')
    monkeypatch.setattr(MaterialService,'version',unavailable)
    assert next(o for o in svc.snapshot('alice',created['session']['id'])['outputs'] if o['kind']=='materials')['result']['sources']==[]


def test_owner_export_and_recording_delete_include_class_artifacts(env):
    db,svc,body,created=env;audio(env);drain(svc)
    from backend.app.identity_data import owned_rows
    with db.engine.connect() as conn:
        _,tables=owned_rows(conn,'alice')
        assert len(tables['class_sessions'])==1 and tables['class_output_versions'] and tables['class_input_windows']
        _,foreign=owned_rows(conn,'bob');assert not foreign['class_sessions'] and not foreign['class_output_versions']
    LectureService(db).delete('alice',created['session']['noteId'])
    with db.engine.connect() as conn:
        assert conn.execute(text('select count(*) from class_sessions')).scalar_one()==0
        assert conn.execute(text('select count(*) from class_output_versions')).scalar_one()==0
        assert not conn.execute(text("select id from learning_jobs where kind='class_specialist' and status in ('queued','running','retry_wait')")).first()
        assert not conn.execute(text("select id from practice_records where kind='flashcard_deck'")).first()
    with pytest.raises(HTTPException):svc.snapshot('alice',created['session']['id'])


def test_import_remaps_class_and_deck_without_restarting_capture(env):
    db,svc,_,created=env;audio(env);drain(svc)
    from backend.app.identity_import import inventory,import_profile
    plan=inventory(db,'bob',profile='alice')
    import_profile(db,'bob',plan['checksum'],profile='alice')
    with db.engine.connect() as conn:
        identifier=conn.execute(text("SELECT id FROM class_sessions WHERE owner_id='bob'")).scalar_one()
        deck=json.loads(conn.execute(text("SELECT payload FROM practice_records WHERE owner_id='bob' AND kind='flashcard_deck'")).scalar_one())
    copied=svc.snapshot('bob',identifier)
    assert copied['session']['cancelled'] and copied['session']['id']!=created['session']['id']
    assert copied['outputs'] and not deck['scheduled']
    assert set(deck['windows'])==set(copied['session']['activeWindows'])
    assert svc.snapshot('alice',created['session']['id'])['session']['id']==created['session']['id']


def test_http_setup_and_capture_device_fence(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.material_routes import material_owner
    from backend.app.in_class_routes import build_in_class_router
    from backend.app.lecture_routes import build_lecture_router
    monkeypatch.setenv('OPENLEARN_WORKER_MODE','external')
    db,svc,body,created=env
    app=FastAPI();app.dependency_overrides[material_owner]=lambda:'alice'
    app.include_router(build_in_class_router(lambda:db,lambda:svc.provider))
    app.include_router(build_lecture_router(lambda:db,lambda:svc.provider,Transcriber()))
    with TestClient(app) as client:
        assert client.post('/v1/class-sessions',json=body.model_dump(by_alias=True,mode='json')).status_code==200
        assert client.get('/v1/class-sessions/'+created['session']['id']).status_code==200
        content=b'\x1a\x45\xdf\xa3'+b'fake-audio'*5
        headers={'Content-Type':'audio/webm','X-Chunk-Start-Ms':'0','X-Chunk-End-Ms':'8000','X-Chunk-Sha256':hashlib.sha256(content).hexdigest(),'X-Capture-Epoch':'1'}
        url='/v1/learners/alice/lecture-recordings/'+body.recording.id+'/chunks/0'
        headers['X-Capture-Device']='wrong-device';assert client.put(url,headers=headers,content=content).status_code==409
        headers['X-Capture-Device']=body.device_id;assert client.put(url,headers=headers,content=content).status_code==200
        app.dependency_overrides[material_owner]=lambda:'bob'
        assert client.get('/v1/class-sessions/'+created['session']['id']).status_code==404


def test_upgrade_repairs_early_worker_schema(env):
    db,_,_,_=env
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from importlib import import_module
    with db.transaction() as conn:
        conn.execute(text('ALTER TABLE agent_responsibilities DROP COLUMN event_after'))
        conn.execute(text('ALTER TABLE agent_responsibilities DROP COLUMN last_checked'))
        with Operations.context(MigrationContext.configure(conn)):
            import_module('backend.migrations.versions.0050_agent_worker_compat').upgrade()
        columns={row[1] for row in conn.execute(text('PRAGMA table_info(agent_responsibilities)'))}
        assert {'event_after','last_checked'}<=columns
    from backend.app.agent_execution.responsibilities import Responsibilities
    Responsibilities(db).tick()


def test_partial_package_without_speech_explains_unavailable_outputs(env):
    db,svc,body,created=env
    LectureService(db).finalize('alice',body.recording.id,LectureFinalize(expectedChunkCount=1,durationMs=5000));drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    svc.command('alice',snap['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='partial_package'));drain(svc)
    final=svc.snapshot('alice',snap['session']['id'])
    assert final['session']['noSpeech'] and final['session']['processing']=='completed-partial'
    assert final['outputs']==[] and final['recording']['chunks']['missing']==[0]
