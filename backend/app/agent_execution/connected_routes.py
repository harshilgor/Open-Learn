"""Authenticated review controls; OAuth callback uses one-use owner-bound state."""
from fastapi import APIRouter, Header, HTTPException, Query
from .routes import owner
from .connected_actions import ConnectedActions
from .connected_contracts import Draft, Decision, OAuthStart, ChildRequest, StandingGrant, ConnectorError
from .google_connector import GoogleConnections, GoogleAdapter, enabled
from .delegation import Delegation, delegation_enabled

def safe(call):
    try:return call()
    except ConnectorError as exc:raise HTTPException(409,detail={'code':exc.code,'message':exc.code.replace('_',' ')}) from None

def build_connected_router(get_store):
    import logging
    class OAuthAccessRedaction(logging.Filter):
        def filter(self,record):
            if isinstance(record.args,tuple) and len(record.args)>=3 and isinstance(record.args[2],str) and record.args[2].startswith('/oauth/google/callback?'):
                values=list(record.args);values[2]='/oauth/google/callback?[redacted]';record.args=tuple(values)
            return True
    logger=logging.getLogger('uvicorn.access')
    if not any(type(item).__name__=='OAuthAccessRedaction' for item in logger.filters):logger.addFilter(OAuthAccessRedaction())
    router=APIRouter(tags=['connected actions'])
    @router.get('/v1/assistant/app-connections')
    def connections():
        return {'items':GoogleConnections(get_store()).list(owner()),'enabled':enabled(),'delegationEnabled':delegation_enabled(),'standingWritesEnabled':False}
    @router.post('/v1/assistant/app-connections/google/authorize')
    def authorize(body:OAuthStart):return safe(lambda:GoogleConnections(get_store()).start(owner(),body.capabilities))
    @router.get('/oauth/google/callback')
    def callback(state:str=Query(min_length=20,max_length=200),code:str=Query(min_length=1,max_length=4096)):
        return safe(lambda:GoogleConnections(get_store()).callback(state,code))
    @router.delete('/v1/assistant/app-connections/{identifier}',status_code=204)
    def disconnect(identifier:str):safe(lambda:GoogleConnections(get_store()).disconnect(owner(),identifier))
    @router.get('/v1/assistant/app-connections/{identifier}/sources')
    def read(identifier:str,kind:str=Query(pattern='^(drive|gmail)$'),sourceId:str|None=Query(default=None,max_length=300),pageToken:str|None=Query(default=None,max_length=2000)):
        return safe(lambda:GoogleAdapter(GoogleConnections(get_store())).read(owner(),identifier,kind,sourceId,pageToken))
    @router.post('/v1/assistant/app-connections/{identifier}/drive/{source_id}/import')
    def intake(identifier:str,source_id:str,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        learner=owner();store=get_store()
        def apply():
            from .connector_intake import ConnectorIntake
            return ConnectorIntake(store).drive(learner,identifier,source_id,idempotency_key)
        return safe(apply)
    @router.get('/v1/assistant/tasks/{task_id}/actions')
    def actions(task_id:str):return {'items':ConnectedActions(get_store()).list(owner(),task_id)}
    @router.post('/v1/assistant/tasks/{task_id}/actions',status_code=201)
    def draft(task_id:str,body:Draft,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        return safe(lambda:ConnectedActions(get_store()).draft(owner(),task_id,body,idempotency_key))
    @router.post('/v1/assistant/approvals/{identifier}/decision',status_code=202)
    def decide(identifier:str,body:Decision,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        return safe(lambda:ConnectedActions(get_store()).decide(owner(),identifier,body,idempotency_key))
    @router.post('/v1/assistant/approvals/{identifier}/reconcile')
    def reconcile(identifier:str):return safe(lambda:ConnectedActions(get_store()).reconcile(owner(),identifier))
    @router.get('/v1/assistant/tasks/{task_id}/children')
    def children(task_id:str):return Delegation(get_store()).list(owner(),task_id)
    @router.post('/v1/assistant/tasks/{task_id}/children',status_code=201)
    def child(task_id:str,body:ChildRequest,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        return Delegation(get_store()).create(owner(),task_id,body,idempotency_key)
    @router.post('/v1/assistant/standing-authorizations',status_code=201)
    def proposed_grant(body:StandingGrant):
        from sqlalchemy import text
        from ..workflow_store import encoded,uid
        import time
        learner=owner();service=ConnectedActions(get_store());identifier=uid('standing')
        def persist():
            with service.repo.transaction() as conn:
                service._connection(conn,learner,body.connectionId,body.kind)
                conn.execute(text("INSERT INTO agent_standing_grants(id,owner_id,created_at,status,payload) VALUES(:id,:owner,:now,'disabled',:payload)"),{'id':identifier,'owner':learner,'now':time.time(),'payload':encoded(body.model_dump(mode='json'))})
            return {'id':identifier,'status':'disabled','reasonCode':'unattended_writes_not_enabled'}
        return safe(persist)
    return router
