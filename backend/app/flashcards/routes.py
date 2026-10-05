from fastapi import APIRouter,Depends,Query
from .contracts import FlashcardRequest,DeckCommand,ReviewCreate,ReviewCommand,Preferences,RefreshCommand
from .service import DeckService
from .review import ReviewService
from .repository import Repository
from ..material_routes import material_owner
from ..agent_execution.coordinator import Coordinator
from ..agent_execution.contracts import Message

def build_flashcard_router(get_store):
    router=APIRouter(prefix='/v1',tags=['flashcards'])
    @router.post('/flashcard-generations',status_code=202)
    def create(body:FlashcardRequest,owner=Depends(material_owner)):
        return Coordinator(get_store()).admit(owner,Message(clientMessageId=body.client_command_id,sessionId=body.session_id,text=body.objective,capability='flashcards',flashcardSpec=body),body.client_command_id)
    @router.post('/flashcard-generations/{task_id}/retry',status_code=202)
    def retry(task_id:str,body:RefreshCommand,owner=Depends(material_owner)):
        from ..agent_execution.repository import Repository as AgentRepository
        from ..identity import fail
        repo=AgentRepository(get_store());receipts=Repository(get_store())
        with receipts.transaction(owner) as conn:
            cached=receipts.replay(conn,owner,task_id,body)
            if cached is not None:return cached
        with repo.transaction() as conn:
            run=repo.run(conn,owner,task_id)
            if run['kind']!='flashcards' or run['status'] not in {'failed','cancelled','completed_partial'}:fail('invalid_state','Retry a failed, stopped or partial flashcard task.',409)
            if run['revision']!=body.expected_revision:fail('revision_conflict','Task changed.',409)
            spec={**run['constraints']['flashcardRequest'],'clientCommandId':body.command_id}
            if run.get('deckId'):
                deck=Repository(get_store()).get(conn,owner,'decks',run['deckId'])
                spec.update(targetDeckId=deck['id'],expectedDeckRevision=deck['revision'])
        result=create(FlashcardRequest.model_validate(spec),owner)
        with receipts.transaction(owner) as conn:
            cached=receipts.replay(conn,owner,task_id,body)
            if cached is not None:return cached
            receipts.receipt(conn,owner,task_id,body,result)
        return result
    @router.get('/flashcard-decks')
    def listing(course_id:str|None=None,status:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),owner=Depends(material_owner)):
        return DeckService(get_store()).listing(owner,course_id,status,offset,limit)
    @router.post('/flashcard-decks/{identifier}/revalidate',status_code=202)
    def revalidate(identifier:str,body:RefreshCommand,owner=Depends(material_owner)):
        from ..identity import fail
        from ..workflow_store import uid
        from sqlalchemy import text
        repo=Repository(get_store())
        with repo.transaction(owner) as conn:
            cached=repo.replay(conn,owner,identifier,body)
            if cached is not None:return cached
            deck=repo.get(conn,owner,'decks',identifier)
            if deck['revision']!=body.expected_revision:fail('revision_conflict','Refresh the deck before revalidation.',409)
            refs=[]
            for source in deck['coverage']['sources'][:20]:
                ref={k:v for k,v in source['ref'].items() if k in {'kind','id','revision','startOffset','endOffset','spanId','recordingId'}}
                if ref['kind'] in {'note','lesson'}:
                    from ..workspace_note_service import WorkspaceNoteService
                    note=WorkspaceNoteService(get_store())._read_file(owner,ref['id']);ref['revision']=note.revision
                    # Full revised note is safer than stale offsets after insertion/deletion.
                    ref.pop('startOffset',None);ref.pop('endOffset',None)
                elif ref['kind']=='lecture':
                    ref['revision']=conn.execute(text('SELECT normalization_version FROM lecture_transcript_segments WHERE id=:id'),{'id':ref['id']}).scalar_one()
                refs.append(ref)
        request=FlashcardRequest(sessionId=deck['sessionId'],courseId=deck.get('courseId'),origin='review',sourceRefs=refs,targetDeckId=identifier,expectedDeckRevision=body.expected_revision,clientCommandId=body.command_id)
        result=create(request,owner)
        with repo.transaction(owner) as conn:
            cached=repo.replay(conn,owner,identifier,body)
            if cached is not None:return cached
            repo.receipt(conn,owner,identifier,body,result)
        return result
    @router.get('/flashcard-decks/{identifier}')
    def deck(identifier:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),owner=Depends(material_owner)):
        return DeckService(get_store()).get(owner,identifier,offset,limit)
    @router.post('/flashcard-decks/{identifier}/commands')
    def command(identifier:str,body:DeckCommand,owner=Depends(material_owner)):
        return DeckService(get_store()).command(owner,identifier,body)
    @router.patch('/flashcard-decks/{identifier}')
    def patch(identifier:str,body:DeckCommand,owner=Depends(material_owner)):
        return DeckService(get_store()).command(owner,identifier,body)
    @router.post('/flashcard-decks/{identifier}/publish')
    def publish(identifier:str,body:DeckCommand,owner=Depends(material_owner)):
        from ..identity import fail
        if body.action!='publish':fail('invalid_input','Use the publish action.',422)
        return DeckService(get_store()).command(owner,identifier,body)
    @router.get('/flashcard-due-summary')
    def summary(owner=Depends(material_owner)):return ReviewService(get_store()).summary(owner)
    @router.post('/flashcard-review-sessions')
    def review(body:ReviewCreate,owner=Depends(material_owner)):return ReviewService(get_store()).create(owner,body)
    @router.get('/flashcard-review-sessions/{identifier}')
    def session(identifier:str,owner=Depends(material_owner)):return ReviewService(get_store()).get(owner,identifier)
    @router.post('/flashcard-review-sessions/{identifier}/commands')
    def rating(identifier:str,body:ReviewCommand,owner=Depends(material_owner)):return ReviewService(get_store()).command(owner,identifier,body)
    @router.get('/flashcard-images/{version_id}')
    def image(version_id:str,owner=Depends(material_owner)):
        from fastapi.responses import Response
        from ..material_service import MaterialService
        from ..identity import fail
        svc=MaterialService(get_store());version=svc.version(owner,version_id)
        if version['media_type'] not in {'image/png','image/jpeg','image/webp'} or version['byte_count']>20000000:fail('unsupported_image','Image unavailable.',422)
        return Response(svc.objects.read(version['object_key']),media_type=version['media_type'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    @router.get('/flashcard-notifications')
    def notifications(owner=Depends(material_owner)):
        import json
        from sqlalchemy import text
        with Repository(get_store()).transaction(owner) as conn:
            rows=conn.execute(text("SELECT id,status,payload FROM notification_deliveries WHERE owner_id=:owner AND channel='inbox' AND id LIKE 'fc_notice_%' ORDER BY created_at DESC LIMIT 30"),{'owner':owner}).mappings()
            return {'notifications':[{'id':r['id'],'status':r['status'],**json.loads(r['payload'])} for r in rows]}
    @router.get('/flashcard-preferences')
    def preferences(owner=Depends(material_owner)):
        repo=Repository(get_store())
        with repo.transaction(owner) as conn:
            values=repo.rows(conn,owner,'preferences')
            return values[0] if values else Preferences().model_dump(by_alias=True)
    @router.put('/flashcard-preferences')
    def save_preferences(body:Preferences,owner=Depends(material_owner)):
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        from ..identity import fail
        try:ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:fail('invalid_timezone','Choose a valid timezone.',422)
        repo=Repository(get_store())
        with repo.transaction(owner) as conn:
            values=repo.rows(conn,owner,'preferences');value={**body.model_dump(by_alias=True),'id':values[0]['id'] if values else 'fcp_'+owner}
            if values:value['revision']=values[0]['revision']
            return repo.put(conn,owner,'preferences',value,new=not values)
    return router
