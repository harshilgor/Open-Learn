import hashlib
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.tests.test_agent_execution import env
from backend.app.identity import Principal,principal_context
from backend.app.mobile_routes import build_mobile_router
from backend.app.hosted_runtime import configuration_errors
from backend.app.lecture_models import LectureCreate
from backend.app.lecture_service import LectureService

def test_hosted_configuration_fails_closed_without_secret_disclosure():
    assert 'DATABASE_URL' in configuration_errors({})
    configured={'AI_TUTOR_ENV':'production','AI_TUTOR_DEV_IDENTITY':'false','DATABASE_URL':'postgresql+psycopg://secret@host/db','OPENLEARN_OIDC_ISSUER':'https://issuer','OPENLEARN_OIDC_JWKS_URL':'https://issuer/jwks','OPENLEARN_OIDC_AUDIENCE':'api','FORMA_WEB_ORIGIN':'https://web','OPENLEARN_OBJECT_BACKEND':'s3','OPENLEARN_OBJECT_BUCKET':'private','OPENLEARN_ASSISTANT_S3_BUCKET':'private','OPENLEARN_MIGRATE_ON_START':'false'}
    assert configuration_errors(configured)==[]
    configured['FORMA_API_TOKEN']='secret';assert 'secret' not in str(configuration_errors(configured))

def test_voice_receipt_replays_once_and_rejects_changed_input(env,monkeypatch):
    store,_,_=env;monkeypatch.setenv('OPENLEARN_MOBILE_VOICE_ENABLED','true');calls=[]
    provider=SimpleNamespace(transcribe_chunk=lambda *args:(calls.append(args),SimpleNamespace(spans=[SimpleNamespace(text='Review physics')]))[1])
    app=FastAPI();app.include_router(build_mobile_router(lambda:store,lambda:provider));token=principal_context.set(Principal('alice','local'))
    try:
        with TestClient(app) as client:
            headers={'Idempotency-Key':'voice','X-Audio-Duration-Ms':'1000','Content-Type':'audio/wav'}
            first=client.post('/v1/mobile/voice-transcriptions',content=b'voice',headers=headers);assert first.status_code==200
            assert client.post('/v1/mobile/voice-transcriptions',content=b'voice',headers=headers).json()==first.json()
            assert client.post('/v1/mobile/voice-transcriptions',content=b'changed',headers=headers).status_code==409
        assert len(calls)==1
    finally:principal_context.reset(token)

def test_voice_disabled_and_period_budget(env,monkeypatch):
    store,_,_=env;monkeypatch.setenv('OPENLEARN_MOBILE_VOICE_DAILY_CALLS','1');monkeypatch.setenv('OPENLEARN_MOBILE_VOICE_ENABLED','false')
    provider=SimpleNamespace(transcribe_chunk=lambda *args:SimpleNamespace(spans=[]));app=FastAPI();app.include_router(build_mobile_router(lambda:store,lambda:provider));token=principal_context.set(Principal('alice','local'))
    try:
        with TestClient(app) as client:
            headers={'Idempotency-Key':'one','X-Audio-Duration-Ms':'1000','Content-Type':'audio/wav'}
            assert client.post('/v1/mobile/voice-transcriptions',content=b'v',headers=headers).status_code==503
            monkeypatch.setenv('OPENLEARN_MOBILE_VOICE_ENABLED','true')
            assert client.post('/v1/mobile/voice-transcriptions',content=b'v',headers=headers).status_code==200
            headers['Idempotency-Key']='two';assert client.post('/v1/mobile/voice-transcriptions',content=b'v',headers=headers).status_code==429
    finally:principal_context.reset(token)

def test_lecture_audio_uses_object_adapter_and_owner_scope(env):
    store,_,_=env;svc=LectureService(store);rid='rec_'+'b'*32
    svc.create('alice',LectureCreate(id=rid,title='Physics',startedAtMs=1000))
    audio=b'\x1a\x45\xdf\xa3'+b'a'*50
    svc.put_chunk('alice',rid,0,audio,start_ms=0,end_ms=1000,media_type='audio/webm',checksum=hashlib.sha256(audio).hexdigest())
    with store.engine.connect() as conn:key=conn.execute(text('SELECT storage_key FROM lecture_audio_chunks WHERE recording_id=:id'),{'id':rid}).scalar_one()
    svc.objects=SimpleNamespace(read=lambda owner,record,key:audio)
    assert svc.chunk_audio('alice',rid,0)==(audio,'audio/webm')
    with pytest.raises(Exception):svc.chunk_audio('bob',rid,0)
    svc.objects=SimpleNamespace(read=lambda *args:b'corrupt')
    with pytest.raises(Exception):svc.chunk_audio('alice',rid,0)

def test_read_only_schema_check_does_not_run_migrations(env,monkeypatch):
    from backend.app.storage import Store
    store,_,_=env;monkeypatch.setenv('OPENLEARN_MIGRATE_ON_START','false')
    other=Store(store.url);other.close()
    with store.engine.begin() as conn:conn.execute(text("UPDATE alembic_version SET version_num='0048_in_class'"))
    with pytest.raises(RuntimeError,match='release migration'):Store(store.url)


def test_material_ingestion_reads_shared_objects_on_another_service(env,monkeypatch):
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    from backend.app.object_store import LocalObjectStore
    from pathlib import Path
    from uuid import uuid4
    store,_,_=env
    shared=LocalObjectStore(Path('work')/('shared-objects-'+uuid4().hex))
    first=MaterialService(store);first.objects=shared
    content=b'Course physics preparation uses conservation of momentum.'
    item=first.create('alice',UploadRequest(title='Physics',mediaType='text/plain',byteCount=len(content)))
    first.upload('alice',item['materialId'],item['versionId'],content)
    second=MaterialService(store);second.objects=shared
    assert not second.object_path(second.version('alice',item['versionId'])['object_key']).exists()
    assert second.process_one()
    assert second.details('alice',item['materialId'])['status'] in {'ready','partially_ready'}


def test_hosted_notes_rehydrate_from_database_without_local_vault(env,monkeypatch):
    from backend.app.workspace_note_service import WorkspaceNoteService
    from backend.app.workspace_note_models import WorkspaceNoteCreate,WorkspaceNoteUpdate
    from backend.app.identity_data import export_owner
    from pathlib import Path
    from uuid import uuid4
    store,_,_=env
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(Path('work')/('vault-a-'+uuid4().hex)))
    first=WorkspaceNoteService(store);record=first.create('alice',WorkspaceNoteCreate(title='Physics',body='A conserved quantity.'))
    monkeypatch.setenv('AI_TUTOR_ENV','production')
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(Path('work')/('vault-b-'+uuid4().hex)))
    second=WorkspaceNoteService(store);assert not second.note_path('alice',record.id).exists()
    restored=second.get('alice',record.id);assert restored.body=='A conserved quantity.'
    edited=second.update('alice',record.id,WorkspaceNoteUpdate(expectedRevision=1,body='Momentum is conserved.'));assert edited.revision==2
    assert first.get('alice',record.id).body=='Momentum is conserved.'
    assert export_owner(store,'alice')['files']


def test_token_registration_reassigns_this_install_without_foreign_push(env):
    from backend.app.agent_execution.responsibility_routes import build_responsibility_router
    store,_,_=env;app=FastAPI();app.include_router(build_responsibility_router(lambda:store))
    with TestClient(app) as client:
        token=principal_context.set(Principal('alice','local'))
        try:assert client.post('/v1/assistant/responsibility-push-token',json={'token':'ExpoPushToken[test]'}).status_code==200
        finally:principal_context.reset(token)
        token=principal_context.set(Principal('bob','local'))
        try:assert client.post('/v1/assistant/responsibility-push-token',json={'token':'ExpoPushToken[test]'}).status_code==200
        finally:principal_context.reset(token)
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT owner_id FROM notification_subscriptions WHERE active=true")).scalar_one()=='bob'
