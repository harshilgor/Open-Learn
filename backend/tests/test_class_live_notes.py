import hashlib
import json
import time
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_in_class import env,audio,drain,Transcriber
from backend.app.in_class_models import ClassLiveTranscriptSegmentCreate,ClassLiveTranscriptInterimUpdate,ClassCommand
from backend.app.class_live_notes import ClassLiveNoteService
from backend.app.lecture_observations import LectureObservationService
from backend.app.lecture_provider import TranscriptionResult


def capability(env):
    db,svc,_,created=env
    token='capture_'+('x'*40)
    with db.transaction() as conn:
        item=svc.row(conn,'alice',created['session']['id'],True)
        item['captureCapabilityHash']=hashlib.sha256(token.encode()).hexdigest();svc.save(conn,item)
    return token


def final(env,token,sequence=1,version=1):
    _,svc,_,created=env
    return svc.append_live_transcript('alice',created['session']['id'],token,
        ClassLiveTranscriptSegmentCreate(streamId='stream_'+('x'*32),streamSequence=sequence,
            providerItemId='provider_'+str(sequence),transcript='A cell has a membrane.' if version==1 else 'A cell has a nucleus.',
            transcriptionVersion=version,startMs=0,endMs=12000))


def test_caption_notes_precede_archive_and_reconcile_to_revisions(env):
    db,svc,body,created=env;token=capability(env)
    segment=final(env,token);final(env,token);drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    assert not snap['transcript']
    assert len(snap['provisionalNotes'])==1 and snap['provisionalNotes'][0]['status']=='ready'
    assert snap['provisionalNotes'][0]['result']['blocks'][0]['segmentIds']==[segment['id']]
    assert 'caption_note' in svc.metrics('alice',created['session']['id'])['stages']
    audio(env);drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    note=snap['provisionalNotes'][0]
    assert note['status']=='reconciled' and note['authoritativeSources'][0]['revision']==1
    source=note['authoritativeSources'][0]['segmentId']
    LectureObservationService(db).correct_transcript('alice',body.recording.id,source,'Corrected membrane wording.',1)
    drain(svc)
    assert svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]['authoritativeSources'][0]['revision']==2


def test_interim_bounds_revision_fence_expiry_and_no_permanent_text(env):
    db,svc,_,created=env;token=capability(env);live=ClassLiveNoteService(svc);identifier=created['session']['id']
    def interim(i,revision=1,wording='Private provisional words'):
        return ClassLiveTranscriptInterimUpdate(streamId='stream_'+('x'*32),providerItemId='provider_'+str(i),updateRevision=revision,transcript=wording)
    with pytest.raises(HTTPException):live.append_interim('bob',identifier,token,interim(1))
    with pytest.raises(HTTPException):live.append_interim('alice',identifier,'wrong',interim(1))
    assert live.append_interim('alice',identifier,token,interim(1))['accepted']
    assert not live.append_interim('alice',identifier,token,interim(1))['accepted']
    with pytest.raises(HTTPException):live.append_interim('alice',identifier,token,interim(1,1,'different'))
    for i in range(2,25):live.append_interim('alice',identifier,token,interim(i))
    assert len(svc.snapshot('alice',identifier)['interimTranscript'])==20
    with db.transaction() as conn:
        assert not any('Private provisional words' in raw for raw in conn.execute(text("SELECT payload FROM class_session_events WHERE kind='transcript.live_interim_changed'")).scalars())
        conn.execute(text('UPDATE class_caption_interims SET expires_at=:now'),{'now':time.time()-1})
    assert svc.snapshot('alice',identifier)['interimTranscript']==[]
    live.append_interim('alice',identifier,token,interim(1,2));final(env,token)
    assert not live.append_interim('alice',identifier,token,interim(1,3))['accepted']


def test_new_caption_version_fences_running_note_job(env):
    db,svc,_,created=env;token=capability(env);final(env,token)
    with db.engine.connect() as conn:job_id=conn.execute(text("SELECT id FROM learning_jobs WHERE kind='class_live_note'")).scalar_one()
    job=svc.jobs.claim(job_id)
    final(env,token,version=2)
    svc.execute(job)
    with db.engine.connect() as conn:
        assert json.loads(conn.execute(text('SELECT payload FROM learning_jobs WHERE id=:id'),{'id':job_id}).scalar_one()).get('noteId')
        assert conn.execute(text('SELECT status FROM class_live_notes')).scalar_one()=='preparing'
    drain(svc)
    note=svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]
    assert note['status']=='ready' and note['sourceVersion']==2


def test_no_speech_archive_retires_draft_as_unmatched(env,monkeypatch):
    token=capability(env);final(env,token);_,svc,_,created=env;drain(svc)
    monkeypatch.setattr(Transcriber,'transcribe_chunk',lambda *args:TranscriptionResult('fake','test',[]))
    audio(env);drain(svc)
    assert svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]['status']=='unmatched'


def test_caption_revision_after_archival_reconciles_again(env):
    token=capability(env);final(env,token);_,svc,_,created=env
    drain(svc);audio(env);drain(svc)
    first=svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]
    assert first['status']=='reconciled'
    final(env,token,version=2);drain(svc)
    revised=svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]
    assert revised['status']=='reconciled' and revised['sourceVersion']==2
    assert revised['revision']>first['revision']


def test_processing_pause_resume_requeues_provisional_notes(env):
    token=capability(env);final(env,token);_,svc,_,created=env
    snap=svc.snapshot('alice',created['session']['id'])
    svc.command('alice',created['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='cancel_processing'))
    drain(svc)
    snap=svc.snapshot('alice',created['session']['id'])
    assert snap['provisionalNotes'][0]['status']!='ready'
    svc.command('alice',created['session']['id'],ClassCommand(expectedRevision=snap['session']['revision'],action='resume_processing'))
    drain(svc)
    assert svc.snapshot('alice',created['session']['id'])['provisionalNotes'][0]['status']=='ready'


def test_http_caption_and_course_lookup_contract(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.in_class_routes import build_in_class_router
    from backend.app.lecture_routes import build_lecture_router
    from backend.app.material_routes import material_owner
    from backend.app.material_index import MaterialIndexService
    db,svc,body,created=env;token=capability(env)
    app=FastAPI();app.dependency_overrides[material_owner]=lambda:'alice'
    app.include_router(build_in_class_router(lambda:db,lambda:svc.provider))
    app.include_router(build_lecture_router(lambda:db,lambda:svc.provider,Transcriber()))
    monkeypatch.setenv('OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED','true')
    captured=[]
    monkeypatch.setattr(MaterialIndexService,'lookup',lambda self,*args,**kwargs:captured.append((args,kwargs)) or {'candidates':[],'ambiguous':False,'hasMore':False,'indexVersion':2})
    with TestClient(app) as client:
        path='/v1/learners/alice/lecture-recordings/'+body.recording.id
        interim={'streamId':'stream_'+('x'*32),'providerItemId':'provider_1','updateRevision':1,'transcript':'A cell'}
        assert client.post(path+'/live-transcription-interim',json=interim,headers={'X-Capture-Capability':token}).status_code==200
        assert client.post(path+'/live-transcription-interim',json=interim).status_code==409
        result=client.get('/v1/class-sessions/'+created['session']['id']+'/reference-lookup',params={'kind':'page_label','value':'iv'})
        assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
        assert captured[0][0][0]=='alice' and captured[0][1]['session_id']==created['session']['sessionId']
        assert client.get('/v1/class-sessions/'+created['session']['id']+'/reference-lookup',params={'kind':'invalid','value':'x'}).status_code==422
