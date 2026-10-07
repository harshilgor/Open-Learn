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


def build_agent_router(store_getter, provider_getter=lambda: None):
    router=APIRouter(prefix='/v1/assistant',tags=['agent execution'])
    from .responsibility_routes import build_responsibility_router
    # Child router already includes the same prefix; mount its routes directly.
    router.routes.extend(build_responsibility_router(store_getter).routes)

    @router.get('/execution-capabilities')
    def available():owner();return capabilities(store_getter())

    @router.post('/messages',status_code=202)
    def message(body:Message,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        try:
            learner = owner()
            # Reject credential memories before persisting the admission payload.
            import re
            if re.match(r'^(?:please\s+)?remember that\s+', body.text, re.I) and re.search(r'(?:password|api[ _-]?key|access[ _-]?token|private key)\s*(?:is\b|=|:)|(?:my|our)\s+secret\b', body.text, re.I):
                fail('sensitive_memory_denied','Credentials cannot be saved as companion memories.',422)
            result = Coordinator(store_getter()).admit(learner,body,idempotency_key)
            if result.get('status') == 'requires_action' and result.get('directive', {}).get('kind') == 'reminder':
                from ..reminder_routes import execute_chat_command, ChatCommand
                from ..reminder_service import ReminderService
                receipt = execute_chat_command(ChatCommand(message=body.text, timezone=body.timezone, sessionId=body.session_id, courseId=body.course_id), learner, ReminderService(store_getter()), result['messageId'], provider_getter)
                result = {**result, 'status':'accepted', 'message':receipt.get('message'), 'directive':None, 'domainReceipt':receipt.get('reminder')}
                with Repository(store_getter()).transaction() as conn:
                    conn.execute(text('UPDATE agent_messages SET response=:response WHERE id=:id AND owner_id=:owner'), {'id':result['messageId'],'owner':learner,'response':json.dumps(result)})
            if result.get('status') == 'requires_action' and result.get('directive', {}).get('kind') == 'memory':
                import re
                from ..source_memory import SourceMemory
                from .repository import digest
                statement = re.sub(r'^(?:please\s+)?remember that\s+', '', body.text, flags=re.I).strip()
                if re.search(r'(?:password|api[ _-]?key|access[ _-]?token|private key)\s*(?:is\b|=|:)|(?:my|our)\s+secret\b',statement,re.I):
                    fail('sensitive_memory_denied','Credentials cannot be saved as companion memories.',422)
                if len(statement) > 2000: fail('invalid_input','Keep a saved preference under 2,000 characters.',422)
                scope = body.course_id if re.search(r'\b(?:this|current) course\b',statement,re.I) else None
                if re.match(r'^for\s+', statement, re.I) and scope is None:
                    with store_getter().engine.connect() as conn:
                        courses = conn.execute(text('SELECT id,name FROM courses WHERE owner_id=:owner AND archived_at IS NULL'), {'owner':learner}).all()
                    matches = [course for course in courses if statement.lower().startswith('for ' + course[1].lower())]
                    if len(matches) != 1: fail('memory_scope_required','Choose the course this preference should apply to before saving it.',422)
                    scope = matches[0][0]
                if scope:
                    from ..browser_assistant.policy import require_course
                    with store_getter().engine.connect() as conn: require_course(conn,learner,scope)
                source_id = 'preference_source_' + digest([learner, result['messageId']])[:32]
                store = store_getter()
                with store.engine.connect() as conn:
                    exists = conn.execute(text('SELECT revision,deleted FROM memory_sources WHERE owner_id=:owner AND id=:id'), {'owner':learner,'id':source_id}).first()
                if exists and exists[1]: fail('memory_removed','This preference was already removed; it will not be restored by a retry.',409)
                memory = SourceMemory(store)
                if not exists: memory.revise(learner,source_id,statement,kind='note',course_id=scope,metadata={'role':'explicit_preference','admissionId':result['messageId']})
                derived = memory.derive(learner,'preference',{'statement':statement},[{'sourceId':source_id,'revision':1}],scope=scope,explicit=True,identifier='preference_'+digest([learner,result['messageId']])[:32])
                result = {**result,'status':'accepted','directive':None,'message':'Saved this preference. You can inspect, edit, or forget it in Settings → Memory.','memorySourceId':source_id,'memoryId':derived['id']}
                with Repository(store).transaction() as conn:
                    conn.execute(text('UPDATE agent_messages SET response=:response WHERE id=:id AND owner_id=:owner'), {'id':result['messageId'],'owner':learner,'response':json.dumps(result)})
            return result
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
