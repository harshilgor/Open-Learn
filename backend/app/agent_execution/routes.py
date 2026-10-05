import asyncio
import json
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import text
from ..identity import current_principal, fail
from .contracts import Message, Command
from .coordinator import Coordinator
from .repository import Repository
from .artifacts import Artifacts
from .config import capabilities


def owner():
    principal=current_principal()
    if principal.kind not in {'web','local','desktop'}:fail('device_scope_denied','Use your Open Learn account.',403)
    return principal.owner_id


def build_agent_router(store_getter):
    router=APIRouter(prefix='/v1/assistant',tags=['agent execution'])
    from .responsibility_routes import build_responsibility_router
    # Child router already includes the same prefix; mount its routes directly.
    router.routes.extend(build_responsibility_router(store_getter).routes)

    @router.get('/execution-capabilities')
    def available():owner();return capabilities(store_getter())

    @router.post('/messages',status_code=202)
    def message(body:Message,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        try:return Coordinator(store_getter()).admit(owner(),body,idempotency_key)
        except ValueError as exc:fail('invalid_input',str(exc),422)

    @router.get('/messages/{identifier}/admission')
    def admission(identifier:str):
        learner=owner()
        with store_getter().engine.connect() as conn:
            from ..identity import assert_owner_active
            assert_owner_active(conn,learner)
            row=conn.execute(text('SELECT response FROM agent_messages WHERE owner_id=:owner AND id=:id'),{'id':identifier,'owner':learner}).first()
            if not row:fail('not_found','Message unavailable.',404)
            return json.loads(row[0])

    @router.get('/tasks/{identifier}/commands/{command_id}')
    def acknowledgment(identifier:str,command_id:str):
        learner=owner();repo=Repository(store_getter());repo.read(learner,identifier)
        with repo.store.engine.connect() as conn:
            row=conn.execute(text('SELECT ack FROM agent_commands WHERE id=:id AND owner_id=:owner AND run_id=:run'),{'id':command_id,'owner':learner,'run':identifier}).first()
            if not row:fail('not_found','Command unavailable.',404)
            return json.loads(row[0])

    from .learning import ContinuationRequest, LearningContinuation

    @router.post('/tasks/{identifier}/continuations',status_code=202)
    def learning_request(identifier:str,body:ContinuationRequest,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        return LearningContinuation(store_getter()).request(owner(),identifier,body,idempotency_key)

    @router.get('/tasks/{identifier}/continuations')
    def learning_status(identifier:str):
        return LearningContinuation(store_getter()).listing(owner(),identifier)

    @router.get('/sessions/{session_id}/activity')
    def activity(session_id:str,after:int|None=Query(default=None,ge=0)):
        return Coordinator(store_getter()).snapshot(owner(),session_id,after)

    @router.get('/sessions/{session_id}/events')
    async def events(session_id:str,request:Request,after:int=Query(default=0,ge=0),stream:bool=False,last_event_id:str|None=Header(default=None,alias='Last-Event-ID')):
        learner=owner();svc=Coordinator(store_getter())
        if last_event_id:
            try:after=max(after,int(last_event_id))
            except ValueError:fail('invalid_input','Invalid activity cursor.',422)
        initial=svc.snapshot(learner,session_id,after)
        if not stream:return initial
        async def generate():
            cursor=after
            while not await request.is_disconnected():
                snapshot=svc.snapshot(learner,session_id,cursor)
                for item in snapshot['items']:
                    cursor=item['sequence'];yield f'id: {cursor}\nevent: activity\ndata: {json.dumps(item)}\n\n'
                yield ': keepalive\n\n';await asyncio.sleep(1)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @router.get('/artifacts/{identifier}')
    def artifact(identifier:str):
        record=Artifacts(store_getter()).read(owner(),identifier)
        return {k:record[k] for k in ('id','run_id','name','sha256','mediaType','size','lineage','inputRevision')}

    @router.get('/artifacts/{identifier}/download')
    def download(identifier:str):
        record,content=Artifacts(store_getter()).download(owner(),identifier)
        return Response(content,media_type=record['mediaType'],headers={'Content-Disposition':f'attachment; filename="{record["name"]}"','X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store'})

    return router
