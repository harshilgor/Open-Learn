from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from .class_buddy import ClassBuddyService
from .material_routes import material_owner


class DoubtInput(BaseModel):
    commandId: str = Field(min_length=1, max_length=160)
    anchorMs: int = Field(ge=0, le=86400000)
    question: str = Field(min_length=1, max_length=4000)


class DoubtUpdate(BaseModel):
    expectedRevision: int = Field(ge=1)
    resolution: Literal['open', 'resolved', 'review']


class DocumentEdit(BaseModel):
    expectedRevision: int = Field(ge=1)
    action: Literal['edit', 'accept_suggestion', 'dismiss_suggestion','move'] = 'edit'
    title: str = Field(default='', max_length=300)
    body: str = Field(default='', max_length=20000)
    topicId: str = Field(default='',max_length=160)
    position: float = Field(default=0,ge=-1e12,le=1e12,allow_inf_nan=False)


class TopicChange(BaseModel):
    expectedRevision: int = Field(ge=1)
    action: Literal['rename','merge','move']
    title: str = Field(default='',max_length=300)
    targetTopicId: str = Field(default='',max_length=160)
    targetRevision: int = Field(default=1,ge=1)
    position: float = Field(default=0,ge=-1e12,le=1e12,allow_inf_nan=False)


def build_class_study_router(get_store):
    router=APIRouter(prefix='/v1/class-sessions',tags=['class-study'])
    from .class_visuals import ClassVisualService, VisualRequest, VisualChange
    from .in_class_service import InClassService
    from .class_topics import ClassTopicService
    @router.get('/{class_id}/topics')
    def topics(class_id:str,cursor:str=Query('',max_length=160),owner=Depends(material_owner)):
        return ClassTopicService(InClassService(get_store())).listing(owner,class_id,cursor)
    @router.patch('/{class_id}/topics/{topic_id}')
    def topic_change(class_id:str,topic_id:str,body:TopicChange,owner=Depends(material_owner)):
        return ClassTopicService(InClassService(get_store())).change(owner,class_id,topic_id,body)
    @router.get('/{class_id}/buddy-history')
    def buddy_history(class_id:str,owner=Depends(material_owner)):
        return ClassBuddyService(get_store()).history(owner,class_id)
    @router.post('/{class_id}/visuals')
    def visual_create(class_id:str,body:VisualRequest,owner=Depends(material_owner)):
        return ClassVisualService(InClassService(get_store())).request(owner,class_id,body)
    @router.get('/{class_id}/visuals')
    def visuals(class_id:str,cursor:str=Query('',max_length=160),owner=Depends(material_owner)):
        return ClassVisualService(InClassService(get_store())).listing(owner,class_id,cursor)
    @router.patch('/{class_id}/visuals/{visual_id}')
    def visual_change(class_id:str,visual_id:str,body:VisualChange,owner=Depends(material_owner)):
        return ClassVisualService(InClassService(get_store())).change(owner,class_id,visual_id,body)
    @router.get('/{class_id}/document')
    def document(class_id:str,cursor:str=Query('',max_length=160),owner=Depends(material_owner)):
        from .class_document import ClassDocumentService
        return ClassDocumentService(get_store()).page(owner,class_id,cursor)
    @router.patch('/{class_id}/document/{block_id}')
    def document_edit(class_id:str,block_id:str,body:DocumentEdit,owner=Depends(material_owner)):
        from .class_document import ClassDocumentService
        return ClassDocumentService(get_store()).edit(owner,class_id,block_id,body)
    @router.get('/{class_id}/buddy-contexts/by-generation/{generation_id}')
    def generation_context(class_id:str,generation_id:str,owner=Depends(material_owner)):
        from fastapi import HTTPException
        data=ClassBuddyService(get_store()).for_generation(owner,generation_id)
        if not data or data['classId']!=class_id:raise HTTPException(404,{'code':'context_unavailable','message':'This class answer context is unavailable.'})
        return data
    @router.post('/{class_id}/doubts')
    def doubt(class_id:str,body:DoubtInput,owner=Depends(material_owner)):
        return ClassBuddyService(get_store()).doubt(owner,class_id,body)
    @router.get('/{class_id}/doubts')
    def doubts(class_id:str,cursor:str=Query('',max_length=160),owner=Depends(material_owner)):
        return ClassBuddyService(get_store()).doubts(owner,class_id,cursor)
    @router.patch('/{class_id}/doubts/{doubt_id}')
    def resolve(class_id:str,doubt_id:str,body:DoubtUpdate,owner=Depends(material_owner)):
        return ClassBuddyService(get_store()).resolve(owner,class_id,doubt_id,body)
    @router.get('/{class_id}/buddy-contexts/{context_id}')
    def context(class_id:str,context_id:str,owner=Depends(material_owner)):
        import json
        from sqlalchemy import text
        from fastapi import HTTPException
        store=get_store()
        with store.engine.connect() as conn:
            ClassBuddyService(store).classes.row(conn,owner,class_id)
            row=conn.execute(text('SELECT state,payload FROM class_buddy_contexts WHERE owner_id=:owner AND class_id=:class AND id=:id'),{'owner':owner,'class':class_id,'id':context_id}).mappings().first()
        if not row:raise HTTPException(404,{'code':'context_unavailable','message':'This class answer context is unavailable.'})
        return {**json.loads(row['payload']),'needsReview':row['state']=='stale'}
    return router
