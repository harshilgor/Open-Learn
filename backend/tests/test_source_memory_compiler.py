import hashlib,json
import pytest
from fastapi import HTTPException
from app.storage import Store
from app.source_memory import SourceMemory
from app.context_compiler import ContextCompiler
from app.identity_import import import_package

@pytest.fixture
def store():
    from pathlib import Path
    from uuid import uuid4
    directory=Path(__file__).resolve().parents[2]/'work'/'memory-tests'
    directory.mkdir(exist_ok=True)
    value=Store(directory/(uuid4().hex+'.db'))
    yield value
    value.engine.dispose()

def test_revision_correction_invalidates_derived_and_commit(store):
    memory=SourceMemory(store)
    memory.revise('alice','s1','Algebra equations are reversible.',expected_revision=0)
    derived=memory.derive('alice','summary','Equations', [{'sourceId':'s1','revision':1}])
    packet=ContextCompiler(store).compile('alice',None,'teaching','algebra')
    memory.revise('alice','s1','Corrected algebra definition.',expected_revision=1)
    with store.engine.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text('SELECT valid FROM memory_derived WHERE id=:id'),derived).scalar()==0
        with pytest.raises(HTTPException) as error: ContextCompiler(store).validate_commit(conn,'alice',packet)
        assert error.value.status_code==409

def test_owner_removal_and_required_budget(store):
    memory=SourceMemory(store); compiler=ContextCompiler(store)
    memory.revise('alice','s1','Algebra '+('required premise '*1000),expected_revision=0)
    assert compiler.compile('bob',None,'assessment','algebra')['manifest']==[]
    packet=compiler.compile('alice',None,'assessment','algebra',required_source_ids=['s1'],token_budget=3000)
    assert packet['status']=='insufficient_context'
    assert packet['budget']['inputUsed']<=packet['budget']['inputAvailable']
    memory.remove('alice','s1',1)
    assert compiler.compile('alice',None,'teaching','algebra',required_source_ids=['s1'])['status']=='insufficient_context'

def test_portable_package_rejects_foreign_owner(store):
    package={'format':'openlearn-account-export','version':1,'ownerId':'local','tables':{'memory_sources':[{'owner_id':'foreign','id':'s1','kind':'note','course_id':None,'revision':1,'deleted':False,'updated_at':1}]},'files':[]}
    digest=hashlib.sha256(json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    with pytest.raises(HTTPException) as error: import_package(store,'alice',package,digest)
    assert error.value.status_code==403

def test_portable_memory_copy_is_resumable_and_remaps_source(store):
    from app.identity_data import export_owner
    SourceMemory(store).revise('local','original','Personal algebra source.',expected_revision=0)
    package=export_owner(store,'local')
    digest=hashlib.sha256(json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    result=import_package(store,'alice',package,digest)
    assert result['status']=='completed'
    assert import_package(store,'alice',package,digest)['status']=='completed'
    packet=ContextCompiler(store).compile('alice',None,'teaching','algebra')
    assert len(packet['manifest'])==1
    assert packet['manifest'][0]['sourceId']!='original'
    assert ContextCompiler(store).compile('local',None,'teaching','algebra')['manifest'][0]['sourceId']=='original'

def test_source_api_cross_account_access_and_revision_conflict(store,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.memory_routes import build_memory_router
    from app.identity_middleware import IdentityMiddleware
    monkeypatch.setenv('AI_TUTOR_ENV','development');monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY','true')
    app=FastAPI();app.include_router(build_memory_router(lambda:store));app.add_middleware(IdentityMiddleware,store_provider=lambda:store)
    with TestClient(app) as client:
        alice={'X-Dev-Learner-Id':'alice'};bob={'X-Dev-Learner-Id':'bob'}
        assert client.put('/v1/memory/sources/lesson',headers=alice,json={'content':'Exact algebra source.','expected_revision':0}).status_code==200
        assert client.get('/v1/memory/sources/lesson/revisions/1',headers=bob).status_code==404
        conflict=client.put('/v1/memory/sources/lesson',headers=alice,json={'content':'Overwritten source.','expected_revision':0})
        assert conflict.status_code==409
        assert conflict.json()['detail']['currentRevision']==1
        assert client.delete('/v1/memory/sources/lesson?expected_revision=1',headers=bob).status_code==409
        assert client.get('/v1/memory/sources/lesson/revisions/1',headers=alice).json()['text']=='Exact algebra source.'

def test_account_deletion_revokes_registry_and_future_work(store):
    from sqlalchemy import text
    from app.identity_data import erase_owner
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at) VALUES('alice','testsubject','Alice','active',0)"))
    SourceMemory(store).revise('alice','source','Algebra history.',expected_revision=0)
    erase_owner(store,'alice')
    with pytest.raises(HTTPException) as error: SourceMemory(store).revise('alice','source','Resurrected history.',expected_revision=0)
    assert error.value.status_code==403
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM memory_revisions WHERE owner_id='alice'")).scalar()==0

def test_canvas_device_grant_has_narrow_route_scope_and_revocation(store,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.identity import issue_device_grant,current_principal
    from app.identity_middleware import IdentityMiddleware
    from sqlalchemy import text
    monkeypatch.setenv('AI_TUTOR_ENV','development');monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY','true')
    app=FastAPI();app.add_middleware(IdentityMiddleware,store_provider=lambda:store)
    @app.post('/v1/canvas/pair')
    def issue():
        with store.transaction() as conn: return issue_device_grant(conn,current_principal().owner_id,'Canvas test')
    @app.get('/v1/memory/sources')
    def private(): return {'private':True}
    @app.post('/v1/canvas/connections/approved/sync')
    def sync(): return {'deviceId':current_principal().device_id}
    with TestClient(app) as client:
        grant=client.post('/v1/canvas/pair',headers={'X-Dev-Learner-Id':'alice'}).json()
        headers={'Authorization':'Bearer '+grant['token']}
        assert client.get('/v1/memory/sources',headers=headers).status_code==403
        assert client.post('/v1/canvas/pair',headers=headers).status_code==403
        assert client.post('/v1/canvas/connections/approved/sync',headers=headers).json()['deviceId']==grant['id']
        with store.transaction() as conn: conn.execute(text('UPDATE identity_devices SET revoked_at=1 WHERE id=:id'),grant)
        assert client.post('/v1/canvas/connections/approved/sync',headers=headers).status_code==401

def test_new_academic_observation_invalidates_prepared_context(store):
    from sqlalchemy import text
    packet=ContextCompiler(store).compile('alice',None,'planning','Plan my next study step.')
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO academic_entities(owner_id,id,course_id,revision,payload,created_at) VALUES('alice','assignment',NULL,1,'{}',0)"))
    with store.engine.connect() as conn:
        with pytest.raises(HTTPException) as error: ContextCompiler(store).validate_commit(conn,'alice',packet)
        assert error.value.detail['code']=='context_academic_changed'

def test_reprocessing_material_cannot_change_prepared_premise_silently(store):
    from sqlalchemy import text
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO materials(id,owner_id,title,role,deleted,course_id) VALUES('material','alice','Algebra','reference',false,NULL)"))
        conn.execute(text("INSERT INTO material_versions(id,material_id,version,object_key,media_type,byte_count,status,payload) VALUES('version','material',1,'object','text/plain',30,'ready','{}')"))
        conn.execute(text("INSERT INTO material_blocks(id,version_id,page_index,ordinal,kind,text,payload) VALUES('block','version',0,0,'paragraph','Algebra equation exact premise.','{}')"))
    packet=ContextCompiler(store).compile('alice',None,'assessment','algebra',required_source_ids=['version'])
    assert packet['manifest'][0]['metadata']['pageIndex']==0
    assert packet['manifest'][0]['historicalSnapshotId']
    with store.transaction() as conn: conn.execute(text("UPDATE material_blocks SET text='Changed premise after reprocessing.' WHERE id='block'"))
    with store.engine.connect() as conn:
        with pytest.raises(HTTPException) as error: ContextCompiler(store).validate_commit(conn,'alice',packet)
        assert error.value.detail['code']=='context_source_changed'
