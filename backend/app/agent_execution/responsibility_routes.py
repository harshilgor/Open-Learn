from typing import Literal
import json
from fastapi import APIRouter,Header,Query
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import text
from .responsibilities import Responsibilities,ResponsibilitySpec,occurrences
from .routes import owner
from ..identity import assert_owner_active
import time

class Control(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['pause','disable','stop_all','resume','edit']
    expectedRevision:int=Field(ge=1)
    spec:ResponsibilitySpec|None=None

class Note(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=4000)
    id:str|None=Field(default=None,max_length=160)
    expectedRevision:int|None=None

class ExpoToken(BaseModel):
    token:str=Field(pattern=r'^(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]$',max_length=200)

def build_responsibility_router(get_store):
    router=APIRouter(prefix='/v1/assistant',tags=['responsibilities'])
    @router.post('/responsibilities/preview')
    def preview(body:ResponsibilitySpec):
        owner();return {'nextOccurrences':occurrences(body,time.time())}
    @router.get('/responsibilities')
    def listing():return {'responsibilities':Responsibilities(get_store()).listing(owner())}
    @router.post('/responsibilities',status_code=201)
    def create(body:ResponsibilitySpec,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
        return Responsibilities(get_store()).create(owner(),body,idempotency_key)
    @router.post('/responsibilities/{identifier}/commands')
    def command(identifier:str,body:Control):
        from ..identity import fail
        if body.action=='edit' and body.spec is None:fail('invalid_input','Editing requires the full specification.',422)
        if body.action!='edit' and body.spec is not None:fail('invalid_input','Use edit to change the specification.',422)
        return Responsibilities(get_store()).control(owner(),identifier,body.expectedRevision,body.action,body.spec)
    @router.get('/responsibilities/{identifier}/notes')
    def notes(identifier:str):return {'notes':Responsibilities(get_store()).notes(owner(),identifier)}
    @router.post('/responsibilities/{identifier}/notes')
    def note(identifier:str,body:Note):return {'notes':Responsibilities(get_store()).note(owner(),identifier,body.text,body.id,body.expectedRevision)}
    @router.delete('/responsibilities/{identifier}/notes/{note_id}')
    def delete_note(identifier:str,note_id:str,expectedRevision:int=Query(ge=1)):
        return Responsibilities(get_store()).delete_note(owner(),identifier,note_id,expectedRevision)
    @router.get('/responsibility-notifications')
    def notices():
        learner=owner();store=get_store()
        with store.transaction() as conn:
            assert_owner_active(conn,learner)
            rows=conn.execute(text("SELECT * FROM notification_deliveries WHERE owner_id=:owner AND channel='inbox' AND id LIKE 'responsibility_notice_%' ORDER BY created_at DESC LIMIT 100"),{'owner':learner}).mappings().all()
            deliveries=conn.execute(text("SELECT reminder_id,status FROM notification_deliveries WHERE owner_id=:owner AND channel='expo'"),{'owner':learner}).mappings().all()
            delivery={r['reminder_id']:r['status'] for r in deliveries}
            return {'notifications':[{'id':r['id'],'status':r['status'],'pushStatus':delivery.get(r['reminder_id'],'disabled'),**json.loads(r['payload'])} for r in rows]}
    @router.post('/responsibility-push-token')
    def push_token(body:ExpoToken):
        from .repository import digest
        from ..workflow_store import encoded
        learner=owner();key=digest(body.token)
        with get_store().transaction() as conn:
            assert_owner_active(conn,learner)
            conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE endpoint_hash=:hash AND owner_id<>:owner'),{'hash':key,'owner':learner})
            conn.execute(text("INSERT INTO notification_subscriptions(id,owner_id,endpoint_hash,active,payload) VALUES(:id,:owner,:hash,true,:payload) ON CONFLICT(owner_id,endpoint_hash) DO UPDATE SET active=true,payload=excluded.payload"),{'id':'expo_'+digest([learner,key])[:32],'owner':learner,'hash':key,'payload':encoded({'kind':'expo','token':body.token})})
        return {'status':'registered'}
    return router
