"""Course-library and material-v2 contracts without external OCR/providers."""
import json
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.material_service import MaterialService
from backend.app.material_models import UploadRequest
from backend.app.material_index import MaterialIndexService, pdf_layout

@pytest.fixture
def env(monkeypatch):
    path=Path('work')/('material-v2-'+uuid4().hex);path.mkdir(parents=True)
    monkeypatch.setenv('AI_TUTOR_MATERIAL_DIR',str(path/'objects'))
    db=Store(path/'db.sqlite')
    yield db,MaterialService(db),MaterialIndexService(db),path
    db.close()

def add(env, content, title='Book', owner='alice', course='biology', role='reference', media='text/plain'):
    db,svc,index,_=env
    raw=content.encode() if isinstance(content,str) else content
    item=svc.create(owner,UploadRequest(title=title,byte_count=len(raw),media_type=media,course_id=course,role=role))
    svc.upload(owner,item['materialId'],item['versionId'],raw)
    svc.process_one()
    return item

def test_library_cues_ambiguity_access_and_delete(env):
    a=add(env,'Chapter 3\nFigure 3.2 describes the membrane. Equation 1.4 calculates transport.')
    add(env,'Figure 3.2 is also mentioned.',title='Other book')
    add(env,'Figure 3.2 forbidden answer.',role='answer_key')
    add(env,'Figure 3.2 foreign owner.',owner='bob')
    add(env,'Figure 3.2 foreign course.',course='chemistry')
    index=env[2]
    result=index.lookup('alice','biology',cue={'kind':'figure','value':'3.2'})
    assert result['ambiguous'] and len(result['candidates'])==2
    assert {r['title'] for r in result['candidates']}=={'Book','Other book'}
    assert all(r['sourceRevision'] and r['provenance']=='authorized_course_library' for r in result['candidates'])
    assert len(index.lookup('alice','biology',cue={'kind':'equation','value':'1.4'})['candidates'])==1
    env[1].delete('alice',a['materialId'])
    assert not index.lookup('alice','biology',cue={'kind':'equation','value':'1.4'})['candidates']
    with env[0].engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM material_index_pages WHERE version_id=:v'),{'v':a['versionId']}).scalar_one()==0

def test_physical_and_printed_pages_are_distinct_and_geometry_rotates(env):
    fitz=pytest.importorskip('fitz')
    doc=fitz.open();page=doc.new_page(width=400,height=600)
    page.insert_text((40,80),'Figure 2.1: Membrane transport')
    page.set_rotation(90)
    doc.set_page_labels([{'startpage':0,'prefix':'','style':'r','firstpagenum':4}])
    raw=doc.tobytes();doc.close()
    item=add(env,raw,media='application/pdf')
    index=env[2]
    physical=index.lookup('alice','biology',cue={'kind':'physical_page','value':'1'})['candidates']
    printed=index.lookup('alice','biology',cue={'kind':'page_label','value':'iv'})['candidates']
    assert physical and printed and physical[0]['spanId']==printed[0]['spanId']
    assert not index.lookup('alice','biology',cue={'kind':'physical_page','value':'4'})['candidates']
    geometry=printed[0]['geometry']
    assert geometry['status']=='measured' and geometry['pageSpace']['rotation']==90
    assert len(geometry['regions'][0]['quad'])==4
    assert all(0<=geometry['regions'][0][key]<=1 for key in ('x','y','width','height'))
    progress=index.progress('alice',item['versionId'])
    assert progress['pages']=={'text':1}

def test_background_ocr_page_resume_and_idempotency(env,monkeypatch):
    fitz=pytest.importorskip('fitz')
    doc=fitz.open()
    for _ in range(22):doc.new_page(width=100,height=100)
    raw=doc.tobytes();doc.close()
    import backend.app.material_service as module
    monkeypatch.setattr(module,'_ocr_pdf_pages',lambda path,pages:{p:{'status':'failed'} for p in pages})
    item=add(env,raw,media='application/pdf')
    index=env[2]
    assert index.progress('alice',item['versionId'])['ocrWork']=={'queued':22}
    monkeypatch.setattr(module,'_ocr_pdf_pages',lambda path,pages:{p:{'status':'completed','text':f'Figure 9.{p} detected by OCR.','confidence':88,'fragments':[]} for p in pages})
    assert index.process_one()
    assert index.progress('alice',item['versionId'])['ocrWork']=={'completed':1,'queued':21}
    with env[0].transaction() as conn:
        conn.execute(text("UPDATE material_ocr_work SET status='queued' WHERE version_id=:v AND page_index=0"),{'v':item['versionId']})
    monkeypatch.setattr(module,'_ocr_pdf_pages',lambda path,pages:{p:{'status':'completed','text':'Equation 88 changed retry wording.','confidence':90,'fragments':[]} for p in pages})
    assert index.process_one()
    with env[0].engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM material_blocks WHERE version_id=:v AND page_index=0'),{'v':item['versionId']}).scalar_one()==1
    assert index.lookup('alice','biology',cue={'kind':'figure','value':'9.0'})['candidates']
    assert not index.lookup('alice','biology',cue={'kind':'equation','value':'88'})['candidates']
    assert index.lookup('alice','biology',query='detected')['candidates']
    assert not index.lookup('alice','biology',query='changed')['candidates']

def test_checkpoint_source_revision_and_optional_vector_fallback(env,monkeypatch):
    item=add(env,'Transport across membranes requires energy.')
    import backend.app.semantic_retrieval as semantic
    monkeypatch.setattr(semantic,'configured_model',lambda:'test')
    monkeypatch.setattr(semantic,'similarity_scores',lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('offline')))
    result=env[2].lookup('alice','biology',query='transport')
    assert result['candidates'] and result['candidates'][0]['retrieval']=='lexical'
    assert not env[2].lookup('bob','biology',query='transport')['candidates']

def test_material_migrations_roundtrip_backfills_legacy_passages(env):
    from alembic import command
    from alembic.config import Config
    from backend.app.database import BACKEND_ROOT
    item=add(env,'Chapter 4\nFigure 4.2 membrane transport legacy passage.')
    config=Config(str(BACKEND_ROOT/'alembic.ini'))
    config.set_main_option('script_location',str(BACKEND_ROOT/'migrations'))
    config.set_main_option('sqlalchemy.url',env[0].url)
    command.downgrade(config,'0067_class_chunk_coverage')
    command.upgrade(config,'head')
    result=env[2].lookup('alice','biology',cue={'kind':'figure','value':'4.2'})
    assert len(result['candidates'])==1
    assert result['candidates'][0]['versionId']==item['versionId']
    assert env[2].lookup('alice','biology',query='legacy')['candidates']


def test_class_worker_dispatches_background_ocr_without_pending_uploads(env):
    from backend.app.material_orchestrator import MaterialOrchestrator
    from concurrent.futures import Future
    item=add(env,'Existing text source.')
    with env[0].transaction() as conn:
        conn.execute(text("INSERT INTO material_ocr_work(version_id,page_index,owner_id,source_revision,status,attempt,payload) VALUES(:v,1,'alice',:sha,'queued',0,'{}')"),
            {'v':item['versionId'],'sha':env[1].version('alice',item['versionId'],conn)['sha256']})
    class Executor:
        calls=[]
        def submit(self,func,*args):
            self.calls.append(func)
            return Future()
    executor=Executor();orchestrator=MaterialOrchestrator(env[0])
    assert orchestrator.tick(executor)>=1
    assert executor.calls and executor.calls[0].__name__=='process_one'
