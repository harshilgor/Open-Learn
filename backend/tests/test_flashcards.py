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
