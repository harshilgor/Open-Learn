"""Source lifecycle and context APIs use verified identity."""
import json
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import text
from .identity import current_principal,assert_owner_active,fail
from .source_memory import SourceMemory
from .context_compiler import ContextCompiler,ContextCompileRequest

class RevisionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content:str=Field(max_length=10_000_000)
    expected_revision:int=Field(ge=0)
    kind:Literal['note','document','transcript','conversation']='note'
    course_id:str|None=None
    metadata:dict=Field(default_factory=dict)

class PreferenceInput(BaseModel):
    statement:str=Field(min_length=1,max_length=2000)
    course_id:str|None=None
    confirmed:Literal[True]

def build_memory_router(store_provider):
    router=APIRouter(prefix='/v1/memory',tags=['memory'])
    @router.get('/sources')
    def sources():
        owner=current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn,owner)
            rows=conn.execute(text('SELECT id,kind,course_id,revision,deleted,updated_at FROM memory_sources WHERE owner_id=:owner ORDER BY updated_at DESC'),{'owner':owner}).mappings().all()
        return {'sources':[dict(row) for row in rows]}
    @router.put('/sources/{source_id}')
    def revise(source_id:str,body:RevisionInput):
        return SourceMemory(store_provider()).revise(current_principal().owner_id,source_id,body.content,kind=body.kind,course_id=body.course_id,expected_revision=body.expected_revision,metadata=body.metadata)
    @router.delete('/sources/{source_id}')
    def remove(source_id:str,expected_revision:int):
        return SourceMemory(store_provider()).remove(current_principal().owner_id,source_id,expected_revision)
    @router.get('/sources/{source_id}/revisions/{revision}')
    def revision(source_id:str,revision:int):
        owner=current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text('SELECT payload,sha256,created_at FROM memory_revisions WHERE owner_id=:owner AND source_id=:id AND revision=:revision'),{'owner':owner,'id':source_id,'revision':revision}).mappings().first()
            if not row: fail('source_not_found','This source revision is unavailable.',404)
        return {**json.loads(row['payload']),'sha256':row['sha256'],'createdAt':row['created_at']}
    @router.post('/compile')
    def compile_context(body:ContextCompileRequest):
        return ContextCompiler(store_provider()).compile(current_principal().owner_id,body.session_id,body.purpose,body.request,course_id=body.course_id,required_source_ids=body.required_source_ids,token_budget=body.token_budget,quiz_scope=body.quiz_scope,target_concept_ids=body.target_concept_ids,reserve_output_tokens=body.reserve_output_tokens,expected_revisions=body.expected_revisions)
    @router.post('/sources/{source_id}/summary')
    def summary(source_id:str,expected_revision:int):
        return SourceMemory(store_provider()).summarize(current_principal().owner_id,source_id,expected_revision)
    @router.post('/preferences')
    def remember_preference(body:PreferenceInput):
        owner=current_principal().owner_id;store=store_provider()
        if body.course_id:
            with store.engine.connect() as conn:
                if not conn.execute(text('SELECT 1 FROM courses WHERE owner_id=:owner AND id=:course AND archived_at IS NULL'),{'owner':owner,'course':body.course_id}).first(): fail('course_not_found','The selected course is unavailable.',404)
        identifier='preference_source_'+uuid4().hex
        memory=SourceMemory(store)
        memory.revise(owner,identifier,body.statement,kind='note',course_id=body.course_id,metadata={'role':'explicit_preference'})
        return memory.derive(owner,'preference',{'statement':body.statement},[{'sourceId':identifier,'revision':1}],scope=body.course_id,explicit=True)
    @router.delete('/derived/{derived_id}')
    def dismiss(derived_id:str):
        owner=current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn,owner)
            conn.execute(text('UPDATE memory_derived SET valid=false WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':derived_id})
        return {'status':'dismissed'}
    @router.get('/derived')
    def derived():
        owner=current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn,owner)
            rows=conn.execute(text('SELECT * FROM memory_derived WHERE owner_id=:owner'),{'owner':owner}).mappings().all()
        return {'items':[{**dict(row),'payload':json.loads(row['payload'])} for row in rows]}
    @router.get('/contexts/{context_id}')
    def context_trace(context_id:str):
        owner=current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn,owner)
            value=conn.execute(text('SELECT payload FROM context_manifests WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':context_id}).scalar_one_or_none()
            if value is None: fail('context_not_found','This decision context is unavailable.',404)
        return json.loads(value)
    return router
