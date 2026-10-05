from fastapi import APIRouter, Depends, Query, HTTPException
from .material_routes import material_owner
from .in_class_service import InClassService
from .in_class_models import ClassCreate, ClassCommand
from .lecture_service import LectureError

def build_in_class_router(get_store,provider_getter):
    router=APIRouter(prefix='/v1/class-sessions',tags=['in-class'])
    def service(db=Depends(get_store)):return InClassService(db,provider_getter())
    @router.post('')
    def create(body:ClassCreate,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.create(owner,body)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}')
    def snapshot(identifier:str,cursor:int=Query(0,ge=0),owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.snapshot(owner,identifier,cursor)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}/events')
    def events(identifier:str,cursor:int=Query(0,ge=0),owner=Depends(material_owner),svc=Depends(service)):return snapshot(identifier,cursor,owner,svc)
    @router.post('/{identifier}/commands')
    def command(identifier:str,body:ClassCommand,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.command(owner,identifier,body)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    return router
