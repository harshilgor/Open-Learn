from fastapi import APIRouter, Depends, Header
from pydantic import Field
from .material_routes import material_owner
from .session_models import ApiModel
from .buddy_service import BuddyService, BuddyInput, BuddyUpdate
from typing import Literal

class Mode(ApiModel):
    mode: Literal['conversation','ask','learn','quiz']

class Assignment(ApiModel):
    buddy_id: str | None = None
class Navigation(ApiModel):
    session_id:str=Field(max_length=160)
class ReadReminders(ApiModel):
    reminder_ids:list[str]=Field(max_length=1000)
class Archive(ApiModel):
    replacement_id: str
    expected_revision: int = Field(ge=1)

def build_buddy_router(store_provider):
    router=APIRouter(prefix='/v1/buddies',tags=['buddies'])
    def service(db=Depends(store_provider)): return BuddyService(db)
    @router.get('')
    def snapshot(owner=Depends(material_owner),svc=Depends(service)): return svc.snapshot(owner)
    @router.post('')
    def create(body:BuddyInput,owner=Depends(material_owner),svc=Depends(service),idempotency_key:str|None=Header(default=None,max_length=200)): return svc.create(owner,body,idempotency_key)
    @router.get('/reminders')
    def reminders(owner=Depends(material_owner),svc=Depends(service)):return svc.reminders(owner)
    @router.get('/today')
    def today(owner=Depends(material_owner),svc=Depends(service)):return svc.today(owner)
    @router.post('/reminders/read')
    def read_reminders(body:ReadReminders,owner=Depends(material_owner),svc=Depends(service)):return svc.read_reminders(owner,body.reminder_ids)
    @router.put('/chats/{session_id}/mode')
    def mode(session_id:str,body:Mode,owner=Depends(material_owner),svc=Depends(service)):return svc.mode(owner,session_id,body.mode)
    @router.patch('/{buddy_id}')
    def update(buddy_id:str,body:BuddyUpdate,owner=Depends(material_owner),svc=Depends(service)): return svc.update(owner,buddy_id,body)
    @router.put('/courses/{course_id}')
    def assign(course_id:str,body:Assignment,owner=Depends(material_owner),svc=Depends(service)): return svc.assign(owner,course_id,body.buddy_id)
    @router.post('/{buddy_id}/default')
    def default(buddy_id:str,owner=Depends(material_owner),svc=Depends(service)): return svc.make_default(owner,buddy_id)
    @router.put('/{buddy_id}/navigation')
    def navigation(buddy_id:str,body:Navigation,owner=Depends(material_owner),svc=Depends(service)):return svc.remember_chat(owner,buddy_id,body.session_id)
    @router.post('/{buddy_id}/archive')
    def archive(buddy_id:str,body:Archive,owner=Depends(material_owner),svc=Depends(service)): return svc.archive(owner,buddy_id,body.replacement_id,body.expected_revision)
    return router
