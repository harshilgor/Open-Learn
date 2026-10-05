from pathlib import Path
from uuid import uuid4
import json
import pytest
from fastapi import HTTPException
from backend.app.storage import Store
from backend.app.models import TopicScope,utc_now
from backend.app.graph_generator import GraphGenerator
from backend.app.session_models import LearningSession
from backend.app.workspace_note_service import WorkspaceNoteService
from backend.app.workspace_note_models import WorkspaceNoteCreate
from backend.app.agent_execution.coordinator import Coordinator
from backend.app.agent_execution.contracts import Message,Command
from backend.app.agent_execution.repository import Repository as Agents
from backend.app.agent_execution.worker import AgentWorker
from backend.app.flashcards.contracts import FlashcardRequest,DeckCommand,ReviewCreate,ReviewCommand
from backend.app.flashcards.service import DeckService
from backend.app.flashcards.review import ReviewService
from backend.app.flashcards.repository import Repository

class Provider:
    def complete_json(self,prompt,tokens=4000):
        if prompt.startswith('FLASHCARD_AUTHOR'):
            data=json.loads(prompt.split('\n')[-1]);source=data['sources'][0]
            return {'cards':[{'type':'qa','prompt':'What encloses a cell?','answer':'The membrane.','explanation':'The cell boundary.','sourceIds':[source['id']],'supportQuote':'A cell has a membrane.'}]}
        data=json.loads(prompt.split('\n')[-1])
        return {'checks':[{'index':i,'supported':True,'clear':True} for i in range(len(data['cards']))]}

@pytest.fixture
def env(monkeypatch):
    path=Path('work')/('flashcard-tests-'+uuid4().hex);path.mkdir(parents=True)
    monkeypatch.setenv('OPENLEARN_AGENT_ADMISSION_ENABLED','true');monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(path/'notes'))
    db=Store(path/'test.sqlite')
    scope=TopicScope(id='scope',topic='biology',resolved_meaning='biology',objective='cells',depth='introductory',created_at=utc_now())
    db.save_scope(scope);graph=GraphGenerator().generate(scope);db.save_graph(graph)
    db.save_session(LearningSession(id='session',learner_id='alice',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    note=WorkspaceNoteService(db).create('alice',WorkspaceNoteCreate(title='Cells',body='A cell has a membrane.'))
    request=FlashcardRequest(sessionId='session',sourceRefs=[{'kind':'note','id':note.id,'revision':note.revision}],clientCommandId='create',requestedCount=1,cardTypes=['qa'])
    yield db,request
    db.close()

def draft(env):
    db,request=env;body=Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request)
    response=Coordinator(db).admit('alice',body,'create');assert Coordinator(db).admit('alice',body,'create')==response
    AgentWorker(db,provider_getter=Provider).tick()
    task=Agents(db).read('alice',response['references'][0]['id']);assert task['status']=='completed',task
    return DeckService(db).get('alice',task['deckId'])

def publish(db,deck):
    command=DeckCommand(commandId=uuid4().hex,expectedRevision=deck['revision'],action='publish',cardIds=[c['id'] for c in deck['cards']])
    result=DeckService(db).command('alice',deck['id'],command);assert DeckService(db).command('alice',deck['id'],command)==result
    return DeckService(db).get('alice',deck['id'])

def test_generation_publication_hidden_answer_and_exactly_once(env):
    db,_=env;deck=publish(db,draft(env));review=ReviewService(db)
    session=review.create('alice',ReviewCreate(commandId='review',deckId=deck['id']))
    assert 'answer' not in session['current'] and 'selection' not in session
    with pytest.raises(HTTPException):review.command('alice',session['id'],ReviewCommand(commandId='bad',expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='rate',rating='good'))
    session=review.command('alice',session['id'],ReviewCommand(commandId='reveal',expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='reveal',response='membrane'))
    assert session['current']['answer']=='The membrane.'
    command=ReviewCommand(commandId='rate',expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='rate',rating='good')
    result=review.command('alice',session['id'],command);assert result['status']=='completed';assert review.command('alice',session['id'],command)==result
    repo=Repository(db)
    with repo.transaction('alice') as conn:
        schedule=repo.get(conn,'alice','schedule',deck['cards'][0]['id']);assert schedule['reviewCount']==1
        assert not repo.rows(conn,'alice','attempts')[0]['evidenceQualified']

def test_owner_isolation_revision_conflicts_and_pinned_versions(env):
    db,_=env;deck=publish(db,draft(env));svc=DeckService(db);review=ReviewService(db)
    with pytest.raises(HTTPException):svc.get('bob',deck['id'])
    session=review.create('alice',ReviewCreate(commandId='review',deckId=deck['id']))
    content={k:v for k,v in deck['cards'][0]['content'].items() if k in {'type','prompt','answer','explanation','sourceIds','supportQuote','conceptIds'}};content['answer']='The cell membrane.'
    svc.command('alice',deck['id'],DeckCommand(commandId='edit',expectedRevision=deck['revision'],action='edit',cardId=deck['cards'][0]['id'],content=content))
    with pytest.raises(HTTPException):svc.command('alice',deck['id'],DeckCommand(commandId='stale',expectedRevision=deck['revision'],action='rename',title='changed'))
    session=review.command('alice',session['id'],ReviewCommand(commandId='reveal',expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='reveal'))
    assert session['current']['answer']=='The membrane.'

def test_independent_sessions_cannot_double_schedule(env):
    db,_=env;deck=publish(db,draft(env));review=ReviewService(db)
    sessions=[]
    for key in ['one','two']:
        s=review.create('alice',ReviewCreate(commandId=key,deckId=deck['id']))
        s=review.command('alice',s['id'],ReviewCommand(commandId=key+'reveal',expectedRevision=s['revision'],attemptId=s['current']['attemptId'],action='reveal'));sessions.append(s)
    for i,s in enumerate(sessions):
        body=ReviewCommand(commandId=str(i)+'rate',expectedRevision=s['revision'],attemptId=s['current']['attemptId'],action='rate',rating='good')
        if i:
            with pytest.raises(HTTPException) as exc:review.command('alice',s['id'],body)
            assert exc.value.detail['code']=='schedule_conflict'
        else:review.command('alice',s['id'],body)

def test_cancel_cannot_publish(env):
    db,request=env;response=Coordinator(db).admit('alice',Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request),'create')
    task=Agents(db).read('alice',response['references'][0]['id'])
    Coordinator(db).command('alice',task['id'],Command(commandId='cancel',expectedRevision=task['revision'],action='cancel'))
    AgentWorker(db,provider_getter=Provider).tick();assert not DeckService(db).listing('alice')['decks']

def test_malformed_citations_rejected(env):
    db,request=env
    class Bad(Provider):
        def complete_json(self,prompt,tokens=4000):
            raw=super().complete_json(prompt,tokens)
            if 'cards' in raw:raw['cards'][0]['sourceIds']=['foreign']
            return raw
    response=Coordinator(db).admit('alice',Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request),'create')
    AgentWorker(db,provider_getter=Bad).tick()
    assert Agents(db).read('alice',response['references'][0]['id'])['status']=='failed'
    assert not DeckService(db).listing('alice')['decks']

def test_cloze_hidden_on_server_and_practice_skip_does_not_schedule(env):
    db,_=env;deck=draft(env);service=DeckService(db)
    source=deck['coverage']['sources'][0]['id']
    service.command('alice',deck['id'],DeckCommand(commandId='add-cloze',expectedRevision=deck['revision'],action='create',content={'type':'cloze','prompt':'A cell has a {{c1::membrane}}.','answer':'membrane','sourceIds':[source],'supportQuote':'A cell has a membrane.'}))
    deck=publish(db,service.get('alice',deck['id']));review=ReviewService(db)
    session=review.create('alice',ReviewCreate(commandId='practice',deckId=deck['id'],practice=True))
    while session['current']:
        assert '{{c1::' not in session['current']['prompt']
        session=review.command('alice',session['id'],ReviewCommand(commandId=uuid4().hex,expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='skip'))
    repo=Repository(db)
    with repo.transaction('alice') as conn:assert all(s['reviewCount']==0 for s in repo.rows(conn,'alice','schedule'))

def test_correction_marks_stale_and_preserves_user_edit(env):
    from backend.app.workspace_note_models import WorkspaceNoteUpdate
    db,request=env;deck=publish(db,draft(env));note_id=request.source_refs[0].id
    WorkspaceNoteService(db).update('alice',note_id,WorkspaceNoteUpdate(expected_revision=1,body='A cell has a protective membrane.'))
    current=DeckService(db).get('alice',deck['id']);assert current['cards'][0]['stale']
    assert current['cards'][0]['content']['answer']=='The membrane.'
    with pytest.raises(HTTPException):ReviewService(db).create('alice',ReviewCreate(commandId='review',deckId=deck['id']))

def test_quality_uncertainty_becomes_draft_candidate(env):
    db,request=env
    class Uncertain(Provider):
        def complete_json(self,prompt,tokens=4000):
            value=super().complete_json(prompt,tokens)
            if 'checks' in value:value['checks'][0]['supported']=False
            return value
    response=Coordinator(db).admit('alice',Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request),'create')
    AgentWorker(db,provider_getter=Uncertain).tick();task=Agents(db).read('alice',response['references'][0]['id'])
    deck=DeckService(db).get('alice',task['deckId']);assert not deck['cards'] and deck['candidates'][0]['reason']=='quality_uncertain'
    with pytest.raises(HTTPException):ReviewService(db).create('alice',ReviewCreate(commandId='review',deckId=deck['id']))

def test_source_revision_change_and_lease_loss_cannot_publish(env):
    from backend.app.workspace_note_models import WorkspaceNoteUpdate
    db,request=env
    class Correcting(Provider):
        def complete_json(self,prompt,tokens=4000):
            result=super().complete_json(prompt,tokens)
            if prompt.startswith('FLASHCARD_CHECK'):
                WorkspaceNoteService(db).update('alice',request.source_refs[0].id,WorkspaceNoteUpdate(expected_revision=1,body='A cell has a protective membrane.'))
            return result
    response=Coordinator(db).admit('alice',Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request),'create')
    AgentWorker(db,provider_getter=Correcting).tick()
    assert not DeckService(db).listing('alice')['decks']
    assert Agents(db).read('alice',response['references'][0]['id'])['status']=='failed'

def test_export_import_review_ids_and_no_generation_restart(env):
    from backend.app.identity_import import inventory,import_profile
    from backend.app.identity_data import owned_rows
    db,_=env;deck=publish(db,draft(env));review=ReviewService(db);session=review.create('alice',ReviewCreate(commandId='review',deckId=deck['id']))
    plan=inventory(db,'bob',profile='alice');import_profile(db,'bob',plan['checksum'],profile='alice')
    copied=DeckService(db).listing('bob')['decks'][0]
    assert copied['id']!=deck['id'] and copied['status']=='published'
    repo=Repository(db)
    with repo.transaction('bob') as conn:
        sessions=repo.rows(conn,'bob','sessions');assert sessions[0]['selection'][0]['attemptId']!=session['current']['attemptId']
        _,tables=owned_rows(conn,'bob');assert not tables.get('learning_jobs')
        assert len(tables['flashcard_versions'])==1

def test_reminders_are_opt_in_and_daily_idempotent(env):
    from backend.app.flashcards.maintenance import FlashcardMaintenance
    from sqlalchemy import text
    db,_=env;publish(db,draft(env));maintenance=FlashcardMaintenance(db);maintenance.tick()
    with db.engine.connect() as conn:assert not conn.execute(text("SELECT 1 FROM notification_deliveries WHERE id LIKE 'fc_notice_%'")).first()
    repo=Repository(db)
    with repo.transaction('alice') as conn:repo.put(conn,'alice','preferences',{'id':'fcp_alice','reminders':True,'proactiveDrafts':False,'timezone':'America/Los_Angeles'},new=True)
    maintenance.tick();maintenance.tick()
    with db.engine.connect() as conn:assert conn.execute(text("SELECT count(*) FROM notification_deliveries WHERE id LIKE 'fc_notice_%'")).scalar_one()==1

def test_visual_card_ownership_and_occlusion_contract(env):
    from backend.app.flashcards.contracts import CardContent
    from pydantic import ValidationError
    db,_=env;deck=draft(env);source=deck['coverage']['sources'][0]['id']
    base={'type':'image_occlusion','prompt':'Which structure is covered?','answer':'Membrane','sourceIds':[source],'supportQuote':'A cell has a membrane.','image':{'versionId':'foreign','altText':'Cell diagram with a hidden structure','rightsConfirmed':True,'masks':[{'x':.1,'y':.2,'width':.3,'height':.1}]}}
    with pytest.raises(HTTPException):DeckService(db).command('alice',deck['id'],DeckCommand(commandId='foreign-image',expectedRevision=deck['revision'],action='create',content=base))
    base['image']['masks'][0]['width']=1
    with pytest.raises(ValidationError):CardContent.model_validate(base)

def test_api_lifecycle_and_foreign_deck_access(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.flashcards.routes import build_flashcard_router
    from backend.app.material_routes import material_owner
    db,request=env;app=FastAPI();app.include_router(build_flashcard_router(lambda:db));app.dependency_overrides[material_owner]=lambda:'alice';client=TestClient(app)
    response=client.post('/v1/flashcard-generations',json=request.model_dump(by_alias=True));assert response.status_code==202,response.text
    AgentWorker(db,provider_getter=Provider).tick();task=Agents(db).read('alice',response.json()['references'][0]['id'])
    deck=client.get('/v1/flashcard-decks/'+task['deckId']).json()
    assert client.post('/v1/flashcard-decks/'+deck['id']+'/publish',json={'commandId':'publish-api','expectedRevision':deck['revision'],'action':'publish','cardIds':[deck['cards'][0]['id']]}).status_code==200
    session=client.post('/v1/flashcard-review-sessions',json={'commandId':'review-api','deckId':deck['id']}).json()
    assert 'answer' not in session['current']
    revealed=client.post('/v1/flashcard-review-sessions/'+session['id']+'/commands',json={'commandId':'reveal-api','expectedRevision':session['revision'],'attemptId':session['current']['attemptId'],'action':'reveal'}).json()
    assert revealed['current']['answer']=='The membrane.'
    app.dependency_overrides[material_owner]=lambda:'bob'
    assert client.get('/v1/flashcard-decks/'+deck['id']).status_code==404
    assert client.get('/v1/flashcard-review-sessions/'+session['id']).status_code==404

def test_owned_visual_asset_rendering_and_hidden_occlusion(env):
    import base64
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    db,_=env;deck=draft(env);svc=MaterialService(db);image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=')
    material=svc.create('alice',UploadRequest(title='Cell diagram',media_type='image/png',byte_count=len(image),role='reference'))
    svc.upload('alice',material['materialId'],material['versionId'],image)
    content={'type':'image_occlusion','prompt':'Which structure is concealed?','answer':'Membrane','sourceIds':[deck['coverage']['sources'][0]['id']],'supportQuote':'A cell has a membrane.','image':{'versionId':material['versionId'],'altText':'A cell diagram with one hidden label','rightsConfirmed':True,'masks':[{'x':.1,'y':.1,'width':.2,'height':.2}]}}
    DeckService(db).command('alice',deck['id'],DeckCommand(commandId='add-image',expectedRevision=deck['revision'],action='create',content=content));deck=publish(db,DeckService(db).get('alice',deck['id']))
    review=ReviewService(db);session=review.create('alice',ReviewCreate(commandId='image-review',deckId=deck['id']))
    while session['current'] and session['current']['type']!='image_occlusion':session=review.command('alice',session['id'],ReviewCommand(commandId=uuid4().hex,expectedRevision=session['revision'],attemptId=session['current']['attemptId'],action='skip'))
    assert session['current']['image']['versionId']==material['versionId'] and 'answer' not in session['current']
    svc.delete('alice',material['materialId'])
    changed=DeckService(db).get('alice',deck['id'])
    assert next(card for card in changed['cards'] if card['content']['type']=='image_occlusion')['publishedStale']
    assert ReviewService(db).summary('alice')['dueCount']==1


def test_material_source_requires_attachment_and_frozen_revision(env,monkeypatch):
    from backend.app.material_service import MaterialService
    from backend.app.material_models import UploadRequest
    from backend.app.flashcards.sources import resolve
    db,request=env
    monkeypatch.setenv('AI_TUTOR_MATERIAL_DIR',str(Path('work')/('fc-material-'+uuid4().hex)))
    service=MaterialService(db);raw=b'A cell has a membrane.'
    item=service.create('alice',UploadRequest(title='Cells reference',media_type='text/plain',byte_count=len(raw)))
    service.upload('alice',item['materialId'],item['versionId'],raw);service.process_one()
    details=service.details('alice',item['materialId']);assert details['revision']==1
    from backend.app.flashcards.contracts import SourceRef
    request=request.model_copy(update={'source_refs':[SourceRef(kind='material',id=item['versionId'],revision=1)]})
    with Repository(db).transaction('alice') as conn:
        with pytest.raises(HTTPException) as error:resolve(db,conn,'alice',request)
        assert error.value.detail['code']=='source_scope_mismatch'
    service.attach('alice','session',item['versionId'])
    with Repository(db).transaction('alice') as conn:
        manifest=resolve(db,conn,'alice',request)
        assert manifest['sources'][0]['text']=='A cell has a membrane.'
        assert manifest['sources'][0]['ref']['revision']==1


def test_assessment_preparation_is_opt_in_draft_only_and_idempotent(env):
    from datetime import datetime,timezone
    from sqlalchemy import text
    from backend.app.course_service import CourseService
    from backend.app.course_models import CourseCreate
    from backend.app.flashcards.maintenance import FlashcardMaintenance
    db,_=env;course=CourseService(db).create_course('alice',CourseCreate(name='Biology'))
    session=db.get_session('session');session.course_id=course.id;db.save_session(session)
    WorkspaceNoteService(db).create('alice',WorkspaceNoteCreate(title='Course cells',body='A cell has a membrane.',frontmatter={'course_id':course.id}))
    assessment={'id':'exam','kind':'assessment','courseId':course.id,'revision':1,'facts':{'due':{'value':datetime.now(timezone.utc).isoformat()},'title':{'value':'Cells exam'}}}
    with db.transaction() as conn:conn.execute(text('INSERT INTO academic_entities(id,owner_id,course_id,revision,payload,created_at) VALUES(:id,:owner,:course,1,:payload,0)'),{'id':'exam','owner':'alice','course':course.id,'payload':json.dumps(assessment)})
    repo=Repository(db);maintenance=FlashcardMaintenance(db)
    with repo.transaction('alice') as conn:repo.put(conn,'alice','preferences',{'id':'fcp_alice','reminders':False,'proactiveDrafts':False,'timezone':'UTC'},new=True)
    maintenance.tick()
    with db.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==0
    with repo.transaction('alice') as conn:
        prefs=repo.get(conn,'alice','preferences','fcp_alice');prefs['proactiveDrafts']=True;repo.put(conn,'alice','preferences',prefs)
    maintenance.tick();maintenance.tick()
    with db.engine.connect() as conn:assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==1
    AgentWorker(db,provider_getter=Provider).tick()
    decks=DeckService(db).listing('alice')['decks'];assert len(decks)==1;assert decks[0]['status']=='draft'
    assert ReviewService(db).summary('alice')['dueCount']==0


def test_api_retry_receipt_replays_after_retry_completion(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.flashcards.routes import build_flashcard_router
    from backend.app.material_routes import material_owner
    db,request=env;coordinator=Coordinator(db)
    original=coordinator.admit('alice',Message(clientMessageId='create',sessionId='session',text='Make cards',capability='flashcards',flashcardSpec=request),'create')
    task=Agents(db).read('alice',original['references'][0]['id'])
    coordinator.command('alice',task['id'],Command(commandId='cancel-for-retry',expectedRevision=task['revision'],action='cancel'))
    task=Agents(db).read('alice',task['id']);app=FastAPI();app.include_router(build_flashcard_router(lambda:db));app.dependency_overrides[material_owner]=lambda:'alice';client=TestClient(app)
    body={'commandId':'retry-api','expectedRevision':task['revision']}
    first=client.post('/v1/flashcard-generations/'+task['id']+'/retry',json=body);assert first.status_code==202,first.text
    AgentWorker(db,provider_getter=Provider).tick()
    second=client.post('/v1/flashcard-generations/'+task['id']+'/retry',json=body);assert second.json()==first.json()
    with db.engine.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text('SELECT count(*) FROM assistant_runs')).scalar_one()==2


def test_deleting_note_stops_due_review_without_erasing_history(env):
    db,request=env;deck=publish(db,draft(env))
    assert ReviewService(db).summary('alice')['dueCount']==1
    source=request.source_refs[0];WorkspaceNoteService(db).delete('alice',source.id,source.revision)
    changed=DeckService(db).get('alice',deck['id']);assert changed['cards'][0]['publishedStale']
    assert ReviewService(db).summary('alice')['dueCount']==0
    assert changed['cards'][0]['content']['answer']=='The membrane.'
