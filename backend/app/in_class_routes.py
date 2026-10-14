import base64
import json
import math
import re
import asyncio
import time
from fastapi import APIRouter, Depends, Query, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from .material_routes import material_owner
from .in_class_service import InClassService
from .in_class_models import ClassCreate, ClassCommand, ClassMaterialAttach, ClassMaterialIntakeCreate
from .material_orchestrator import MaterialOrchestrator
from .material_service import MaterialService
from .resource_intents import (
    ConnectorRegistry,
    CourseResourcePreferencesUpdate,
    ResourceIntentService,
)
from .lecture_service import LectureError
from pydantic import BaseModel,Field

class VerificationReceiptInput(BaseModel):
    expectedRevision:int=Field(ge=1)
    externalRequestId:str=Field(min_length=1,max_length=160,pattern=r'^[A-Za-z0-9_-]+$')

class ClassTranscriptEditInput(BaseModel):
    expectedRevision:int=Field(ge=1)
    wording:str=Field(min_length=1,max_length=4000)
    speakerRole:str=Field(default='unknown',pattern=r'^(professor|student|unknown)$')

def parse_http_range(value:str|None,size:int):
    if value is None:return None
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value.strip())
    if not match or size<=0 or (not match.group(1) and not match.group(2)):
        raise HTTPException(416,{'code':'range_not_satisfiable','message':'The requested PDF byte range is invalid.'},headers={'Content-Range':f'bytes */{size}'})
    first,last=match.groups()
    try:
        if not first:
            suffix=int(last)
            if suffix<=0:raise ValueError()
            start=max(0,size-suffix);end=size-1
        else:
            start=int(first);end=min(int(last),size-1) if last else size-1
    except ValueError:
        raise HTTPException(416,{'code':'range_not_satisfiable','message':'The requested PDF byte range is invalid.'},headers={'Content-Range':f'bytes */{size}'}) from None
    if start<0 or start>=size or end<start:
        raise HTTPException(416,{'code':'range_not_satisfiable','message':'The requested PDF byte range is outside the document.'},headers={'Content-Range':f'bytes */{size}'})
    return start,end

def build_in_class_router(get_store,provider_getter):
    router=APIRouter(prefix='/v1/class-sessions',tags=['in-class'])
    def service(db=Depends(get_store)):return InClassService(db,provider_getter())
    @router.get('/{identifier}/verification-requests')
    def verification_requests(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        from .class_verification import ClassVerificationService
        return ClassVerificationService(svc.store).listing(owner,identifier)
    @router.post('/{identifier}/verification-requests/{request_id}/retry')
    def retry_verification(identifier:str,request_id:str,revision:int=Query(ge=1),owner=Depends(material_owner),svc=Depends(service)):
        from .class_verification import ClassVerificationService
        from .lecture_provider import TranscriptionFailure
        try:return ClassVerificationService(svc.store).retry(owner,identifier,request_id,revision)
        except TranscriptionFailure as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':str(exc)}) from None
    @router.post('/{identifier}/verification-requests/{request_id}/receipt')
    def verification_receipt(identifier:str,request_id:str,body:VerificationReceiptInput,owner=Depends(material_owner),svc=Depends(service)):
        from .class_verification import ClassVerificationService
        from .lecture_provider import TranscriptionFailure
        try:return ClassVerificationService(svc.store).associate_receipt(owner,identifier,request_id,body.expectedRevision,body.externalRequestId)
        except TranscriptionFailure as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':str(exc)}) from None
    @router.get('/{identifier}/transcript/{segment_id}/evidence')
    def transcript_evidence(identifier:str,segment_id:str,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            row=conn.execute(text('SELECT w.payload FROM class_evidence_words w JOIN lecture_transcript_segments s ON s.id=w.segment_id WHERE w.owner_id=:owner AND w.segment_id=:segment AND s.recording_id=:recording'),{'owner':owner,'segment':segment_id,'recording':item['recordingId']}).scalar_one_or_none()
        return json.loads(row) if row else {'words':[],'settlement':'legacy','confidence':None}
    @router.patch('/{identifier}/transcript/{segment_id}')
    def class_transcript_edit(identifier:str,segment_id:str,body:ClassTranscriptEditInput,owner=Depends(material_owner),svc=Depends(service)):
        from .lecture_observations import LectureObservationService
        with svc.store.engine.connect() as conn:item=svc.row(conn,owner,identifier)
        try:return LectureObservationService(svc.store).correct_transcript(owner,item['recordingId'],segment_id,body.wording,body.expectedRevision,body.speakerRole)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from None
    @router.post('/{identifier}/transcript/{segment_id}/undo')
    def class_transcript_undo(identifier:str,segment_id:str,revision:int=Query(ge=1),owner=Depends(material_owner),svc=Depends(service)):
        from .lecture_observations import LectureObservationService
        with svc.store.engine.connect() as conn:item=svc.row(conn,owner,identifier)
        try:return LectureObservationService(svc.store).undo_transcript(owner,item['recordingId'],segment_id,revision)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from None
    @router.get('/{identifier}/transcript/{segment_id}/audio-info')
    def class_transcript_audio_info(identifier:str,segment_id:str,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            row=conn.execute(text('SELECT c.start_ms,s.start_ms AS segment_start,s.end_ms AS segment_end FROM lecture_transcript_segments s JOIN lecture_audio_chunks c ON c.id=s.chunk_id WHERE s.id=:id AND s.recording_id=:recording'),{'id':segment_id,'recording':item['recordingId']}).mappings().first()
        if not row:raise HTTPException(404,{'code':'segment_unavailable','message':'This passage is unavailable.'})
        return {'startSeconds':max(0,(row['segment_start']-row['start_ms'])/1000),'endSeconds':max(0,(row['segment_end']-row['start_ms'])/1000)}
    @router.get('/{identifier}/transcript/{segment_id}/audio')
    def class_transcript_audio(identifier:str,segment_id:str,owner=Depends(material_owner),svc=Depends(service)):
        from .lecture_service import LectureService
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            sequence=conn.execute(text('SELECT c.sequence_number FROM lecture_transcript_segments s JOIN lecture_audio_chunks c ON c.id=s.chunk_id WHERE s.id=:id AND s.recording_id=:recording'),{'id':segment_id,'recording':item['recordingId']}).scalar_one_or_none()
        if sequence is None:raise HTTPException(404,{'code':'segment_unavailable','message':'This passage is unavailable.'})
        try:content,mime=LectureService(svc.store).chunk_audio(owner,item['recordingId'],sequence)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from None
        return Response(content,media_type=mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    @router.get('')
    def class_summaries(response:Response,limit:int=Query(20,ge=1,le=50),cursor:str|None=Query(None,max_length=512),owner=Depends(material_owner),svc=Depends(service)):
        # This compact, owner-filtered index is for selecting a class on mobile.
        # The full snapshot endpoint remains authoritative for class content.
        response.headers['Cache-Control']='private, no-store'
        cursor_values=None
        if cursor:
            try:
                raw=base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4))
                value=json.loads(raw)
                cursor_values=(float(value['createdAt']),str(value['id']))
                if not cursor_values[1] or not math.isfinite(cursor_values[0]):raise ValueError()
            except (ValueError,TypeError,KeyError,json.JSONDecodeError):
                raise HTTPException(422,{'code':'invalid_cursor','message':'This class history cursor is invalid. Reload recent classes.'}) from None
        query='''
                SELECT c.id,c.session_id,c.created_at,c.payload,r.status AS recording_status
                FROM class_sessions c
                JOIN lecture_recordings r ON r.id=c.recording_id AND r.learner_id=c.owner_id
                WHERE c.owner_id=:owner
                {cursor_clause}
                ORDER BY c.created_at DESC,c.id DESC
                LIMIT :limit
            '''
        params={'owner':owner,'limit':limit+1}
        cursor_clause='AND (c.created_at<:created_at OR (c.created_at=:created_at AND c.id<:class_id))' if cursor_values else ''
        if cursor_values:params.update({'created_at':cursor_values[0],'class_id':cursor_values[1]})
        with svc.store.engine.connect() as conn:
            rows=conn.execute(text(query.format(cursor_clause=cursor_clause)),params).mappings().all()
        has_more=len(rows)>limit
        page_rows=rows[:limit]
        items=[]
        for row in page_rows:
            payload=json.loads(row['payload'])
            items.append({
                'id':row['id'],
                'sessionId':row['session_id'],
                'title':str(payload.get('title') or 'Class session')[:200],
                'courseId':payload.get('courseId'),
                'createdAt':row['created_at'],
                'processing':payload.get('processing','waiting-for-audio'),
                'recordingStatus':row['recording_status'],
                'capturing':row['recording_status']=='recording',
            })
        next_cursor=None
        if has_more and page_rows:
            last=page_rows[-1]
            encoded=base64.urlsafe_b64encode(json.dumps({'createdAt':last['created_at'],'id':last['id']},separators=(',',':')).encode()).decode().rstrip('=')
            next_cursor=encoded
        return {'items':items,'nextCursor':next_cursor}
    @router.post('')
    def create(body:ClassCreate,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.create(owner,body)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}')
    def snapshot(identifier:str,cursor:int=Query(0,ge=0),initialized:bool=False,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.snapshot(owner,identifier,cursor,initialized)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}/transcript')
    def transcript_page(identifier:str,response:Response,cursor:str|None=Query(default=None,max_length=120),segment_ids:list[str]|None=Query(default=None,alias='segmentId'),owner=Depends(material_owner),svc=Depends(service)):
        response.headers['Cache-Control']='private, no-store'
        if segment_ids is not None and len(segment_ids)>100:raise HTTPException(422,{'code':'too_many_transcript_segments','message':'Request at most 100 transcript passages at a time.'})
        return svc.transcript_page(owner,identifier,cursor,segment_ids)
    @router.get('/{identifier}/outputs')
    def output_page(identifier:str,response:Response,cursor:str=Query(min_length=1,max_length=180),owner=Depends(material_owner),svc=Depends(service)):
        response.headers['Cache-Control']='private, no-store'
        try:return svc.output_page(owner,identifier,cursor)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}/metrics')
    def metrics(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.metrics(owner,identifier)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.get('/{identifier}/reference-lookup')
    def reference_lookup(identifier:str,response:Response,query:str=Query('',max_length=200),
            kind:str|None=Query(None,max_length=32),value:str|None=Query(None,max_length=100),
            owner=Depends(material_owner),svc=Depends(service)):
        from .material_index import MaterialIndexService,CUE_KINDS
        if (kind is None)!=(value is None) or (kind is not None and kind not in CUE_KINDS):
            raise HTTPException(422,{'code':'invalid_reference_cue','message':'Choose a supported reference cue and value.'})
        with svc.store.engine.connect() as conn:item=svc.row(conn,owner,identifier)
        response.headers['Cache-Control']='private, no-store'
        return MaterialIndexService(svc.store).lookup(owner,item.get('courseId'),query,
            {'kind':kind,'value':value} if kind else None,session_id=item['sessionId'],limit=8)
    @router.post('/{identifier}/provisional-notes/{note_id}/retry')
    def retry_provisional_note(identifier:str,note_id:str,revision:int=Query(ge=1),owner=Depends(material_owner),svc=Depends(service)):
        from .class_live_notes import ClassLiveNoteService
        return ClassLiveNoteService(svc).retry(owner,identifier,note_id,revision)
    @router.get('/{identifier}/resource-connectors')
    def resource_connectors(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.engine.connect() as conn:
            svc.row(conn,owner,identifier)
        return {'items':ConnectorRegistry.list(),'externalWritesEnabled':False}
    @router.get('/{identifier}/resource-intents')
    def resource_intents(identifier:str,cursor:str|None=Query(None,max_length=160),owner=Depends(material_owner),svc=Depends(service)):
        return ResourceIntentService(svc.store).list_for_class(owner,identifier,cursor)
    @router.get('/{identifier}/needs')
    def need_info_page(identifier:str,cursor:str|None=Query(None,max_length=160),owner=Depends(material_owner),svc=Depends(service)):
        from .class_metadata import list_needs
        with svc.store.engine.connect() as conn:
            svc.row(conn,owner,identifier)
            return list_needs(conn,owner,identifier,after=cursor)
    @router.get('/{identifier}/resource-preferences')
    def resource_preferences(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            value=ResourceIntentService.get_preferences(conn,owner,item.get('courseId'))
        return value.model_dump(mode='json',by_alias=True)
    @router.put('/{identifier}/resource-preferences')
    def update_resource_preferences(identifier:str,body:CourseResourcePreferencesUpdate,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.transaction() as conn:
            item=svc.row(conn,owner,identifier,True)
            if not item.get('courseId'):
                raise HTTPException(409,{'code':'course_required','message':'Add this class session to a course before saving resource preferences.'})
            value=ResourceIntentService.put_preferences(conn,owner,item['courseId'],body)
        return value.model_dump(mode='json',by_alias=True)
    @router.get('/{identifier}/materials/{version_id}/manifest')
    def material_pdf_manifest(identifier:str,version_id:str,owner=Depends(material_owner),svc=Depends(service)):
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            materials=MaterialService(svc.store)
            version=materials.version(owner,version_id,conn)
            if not svc.material_version_visible(conn,item,version_id,version) or version['media_type']!='application/pdf':
                raise HTTPException(404,{'code':'material_not_found','message':'This class reference is not available.'})
        return materials.pdf_manifest(owner,version_id,version)
    @router.get('/{identifier}/materials/{version_id}/file')
    def material_file(identifier:str,version_id:str,request:Request,owner=Depends(material_owner),svc=Depends(service)):
        # Original documents are served only through a class that already has
        # the version in its owner-scoped reference set. Never expose object
        # keys or accept arbitrary storage paths from the client.
        with svc.store.engine.connect() as conn:
            item=svc.row(conn,owner,identifier)
            materials=MaterialService(svc.store)
            version=materials.version(owner,version_id,conn)
            if not svc.material_version_visible(conn,item,version_id,version) or version['media_type']!='application/pdf':
                raise HTTPException(404,{'code':'material_not_found','message':'This class reference is not available.'})
            # Keep the inline filename safe for Content-Disposition while
            # retaining the uploaded title in the RFC 5987 parameter.
            from urllib.parse import quote
            title=str(version['title'] or 'class-reference')
            safe=''.join(char if char.isascii() and (char.isalnum() or char in '._-') else '_' for char in title).strip('._')[:100] or 'class-reference'
            filename=safe if safe.lower().endswith('.pdf') else safe+'.pdf'
            encoded=quote(filename,safe='')
            byte_count=version['byte_count']
            byte_range=parse_http_range(request.headers.get('range'),byte_count)
            if byte_range:
                start,end=byte_range
                content=materials.objects.iter_range(version['object_key'],start,end)
                content_range=f'bytes {start}-{end}/{byte_count}'
            else:
                content=materials.objects.iter_bytes(version['object_key'])
                content_range=None
        headers={
            'Content-Disposition':f"inline; filename=\"{filename}\"; filename*=UTF-8''{encoded}",
            'Content-Length':str((byte_range[1]-byte_range[0]+1) if byte_range else byte_count),
            'Accept-Ranges':'bytes',
            'Cache-Control':'private, no-store',
            'X-Content-Type-Options':'nosniff',
            'Cross-Origin-Resource-Policy':'same-origin',
        }
        status_code=200
        if content_range:
            headers['Content-Range']=content_range
            status_code=206
        return StreamingResponse(content,media_type='application/pdf',status_code=status_code,headers=headers)
    @router.get('/{identifier}/events')
    def events(identifier:str,cursor:int=Query(0,ge=0),initialized:bool=False,last_event_id:str|None=Header(default=None,alias='Last-Event-ID'),owner=Depends(material_owner),svc=Depends(service)):
        if last_event_id is not None:
            prefix=identifier+':event:'
            try:
                if not last_event_id.startswith(prefix):raise ValueError('Event belongs to another class.')
                cursor=int(last_event_id[len(prefix):])
                if cursor<1:raise ValueError('Event cursor must be positive.')
            except ValueError:
                # An invalid/foreign event token requests authoritative snapshot recovery.
                cursor=0
            initialized=True
        return snapshot(identifier,cursor,initialized,owner,svc)
    @router.get('/{identifier}/stream')
    async def event_stream(identifier:str,request:Request,cursor:int=Query(0,ge=0),initialized:bool=False,last_event_id:str|None=Header(default=None,alias='Last-Event-ID'),owner=Depends(material_owner),svc=Depends(service)):
        if last_event_id is not None:
            prefix=identifier+':event:'
            try:
                if not last_event_id.startswith(prefix):raise ValueError('Event belongs to another class.')
                cursor=int(last_event_id[len(prefix):])
                if cursor<1:raise ValueError('Event cursor must be positive.')
            except ValueError:
                cursor=0
            initialized=True

        async def stream():
            current=cursor
            ready=initialized
            heartbeat_at=time.monotonic()
            while not await request.is_disconnected():
                latest=await run_in_threadpool(svc.latest_event_cursor,owner,identifier)
                if not ready or latest!=current:
                    state=await run_in_threadpool(svc.snapshot,owner,identifier,current,ready)
                    ready=True
                    current=max(current,int(state['cursor'])) if state.get('delta') else int(state['cursor'])
                    event_id=state['events'][-1]['id'] if state.get('events') else (f'{identifier}:event:{current}' if current else None)
                    if event_id:
                        yield f'id: {event_id}\n'
                    yield 'event: class.snapshot\n'
                    yield 'data: '+json.dumps(state,separators=(',',':'),ensure_ascii=False)+'\n\n'
                    heartbeat_at=time.monotonic()
                    if state.get('hasMore'):
                        continue
                now=time.monotonic()
                if now-heartbeat_at>=15:
                    yield ': keepalive\n\n'
                    heartbeat_at=now
                await asyncio.sleep(0.75)

        return StreamingResponse(stream(),media_type='text/event-stream',headers={
            'Cache-Control':'private, no-store, no-transform',
            'Connection':'keep-alive',
            'X-Accel-Buffering':'no',
        })
    @router.post('/{identifier}/commands')
    def command(identifier:str,body:ClassCommand,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.command(owner,identifier,body)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.post('/{identifier}/materials')
    def attach_material(identifier:str,body:ClassMaterialAttach,owner=Depends(material_owner),svc=Depends(service)):
        try:return svc.attach_material(owner,identifier,body)
        except LectureError as exc:raise HTTPException(exc.status_code,{'code':exc.code,'message':exc.message}) from exc
    @router.post('/{identifier}/needs/{need_id}/intakes',status_code=202)
    def start_material_intake(identifier:str,need_id:str,body:ClassMaterialIntakeCreate,owner=Depends(material_owner),svc=Depends(service)):
        return MaterialOrchestrator(svc.store).start(owner,identifier,need_id,body)
    @router.get('/{identifier}/material-intakes/{intake_id}')
    def material_intake(identifier:str,intake_id:str,owner=Depends(material_owner),svc=Depends(service)):
        return MaterialOrchestrator(svc.store).get(owner,identifier,intake_id)
    @router.get('/{identifier}/material-intakes')
    def list_material_intakes(identifier:str,need_id:str|None=Query(default=None,alias='needId',max_length=160),owner=Depends(material_owner),svc=Depends(service)):
        return MaterialOrchestrator(svc.store).list_for_class(owner,identifier,need_id)
    @router.get('/{identifier}/canvas-sources')
    def canvas_material_sources(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        return MaterialOrchestrator(svc.store).canvas_sources(owner,identifier)
    @router.put('/{identifier}/material-intakes/{intake_id}/content')
    async def upload_material_intake(identifier:str,intake_id:str,request:Request,owner=Depends(material_owner),svc=Depends(service)):
        orchestrator=MaterialOrchestrator(svc.store)
        row=orchestrator.upload_context(owner,identifier,intake_id)
        version=orchestrator.materials.version(owner,row['versionId'])
        from .material_models import MAX_DIRECT_MATERIAL_BYTES
        if version['byte_count']>MAX_DIRECT_MATERIAL_BYTES:
            raise HTTPException(413,{'code':'resumable_upload_required','message':'Files above 50 MiB must use the resumable upload flow.'})
        from .material_upload_stream import request_upload_file
        async with request_upload_file(request,version['byte_count']) as (path,_size):
            return orchestrator.upload_file(owner,identifier,intake_id,path)

    @router.post('/{identifier}/material-intakes/{intake_id}/uploads',status_code=201)
    def start_material_upload(identifier:str,intake_id:str,owner=Depends(material_owner),svc=Depends(service)):
        orchestrator=MaterialOrchestrator(svc.store)
        row=orchestrator.upload_context(owner,identifier,intake_id)
        session=orchestrator.materials.create_upload_session(
            owner,row['material_id'],row['version_id'],class_context=(identifier,intake_id)
        )
        return {**session,'sessionUrl':f"/v1/class-sessions/{identifier}/material-intakes/{intake_id}/uploads/{session['uploadId']}"}

    @router.put('/{identifier}/material-intakes/{intake_id}/uploads/{upload_id}/parts/{part_index}')
    async def upload_material_part(identifier:str,intake_id:str,upload_id:str,part_index:int,request:Request,owner=Depends(material_owner),svc=Depends(service)):
        orchestrator=MaterialOrchestrator(svc.store)
        orchestrator.upload_context(owner,identifier,intake_id,upload_id)
        materials=orchestrator.materials
        expected=materials.expected_upload_part_bytes(owner,upload_id,part_index)
        from .material_upload_stream import request_upload_file
        async with request_upload_file(request,expected) as (path,_size):
            orchestrator.upload_context(owner,identifier,intake_id,upload_id)
            return materials.upload_part(owner,upload_id,part_index,path,class_context=(identifier,intake_id))

    @router.post('/{identifier}/material-intakes/{intake_id}/uploads/{upload_id}/complete')
    def complete_material_upload(identifier:str,intake_id:str,upload_id:str,owner=Depends(material_owner),svc=Depends(service)):
        orchestrator=MaterialOrchestrator(svc.store)
        intake=orchestrator.get(owner,identifier,intake_id)
        session=orchestrator.materials.upload_session(owner,upload_id)
        if session['versionId'] != intake.get('versionId'):
            raise HTTPException(404,{'code':'upload_not_found','message':'This upload is unavailable.'})
        if session['status']=='completed':
            return intake
        orchestrator.upload_context(owner,identifier,intake_id,upload_id)
        return orchestrator.materials.complete_upload(
            owner,upload_id,
            completion=lambda _session,path: orchestrator.upload_file(owner,identifier,intake_id,path),
            class_context=(identifier,intake_id),
        )
    return router
