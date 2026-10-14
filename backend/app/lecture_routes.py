"""Owner-scoped API for durable, chunked lecture recordings."""
from __future__ import annotations

from .execution import schedule_local
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path, Request
from fastapi.responses import FileResponse, Response

from .lecture_models import LectureCreate, LectureFinalize, LecturePreferences
from .lecture_pipeline import LectureWorker
from .lecture_service import LectureError, LectureService, MAX_CHUNK_BYTES
from .material_routes import material_owner
from .lecture_observations import LectureObservationService
from .live_transcription import configured_live_transcription_provider, live_transcription_enabled
from .in_class_models import ClassLiveTranscriptSegmentCreate, ClassLiveTranscriptInterimUpdate
from pydantic import BaseModel, Field
from typing import Literal
import os
import json
import hashlib
import hmac
from sqlalchemy import text

class TranscriptEdit(BaseModel):
    wording: str = Field(min_length=1, max_length=4000)
    revision: int = Field(ge=1)

class ObservationEdit(BaseModel):
    id: str | None = None
    kind: Literal['coverage','definition','example','emphasis','assignment','exam_statement','common_error','equation']
    segmentIds: list[str] = Field(min_length=1, max_length=30)
    quote: str = Field(min_length=1, max_length=4000)
    assertion: Literal['direct','inferred','tentative','negated']
    conceptId: str | None = None
    entityId: str | None = None


def build_lecture_router(store_provider, provider_getter, transcriber=None, live_transcriber=None):
    router = APIRouter(prefix="/v1/learners/{learner_id}/lecture-recordings", tags=["lecture-recordings"])

    def authorize(learner_id: str, owner: str):
        if learner_id != owner:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})

    def service(db=Depends(store_provider)):
        return LectureService(db)

    def worker(db=Depends(store_provider)):
        return LectureWorker(db, provider_getter, transcriber)

    def live_provider():
        return live_transcriber or configured_live_transcription_provider()

    def translate(operation):
        try:
            return operation()
        except LectureError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    @router.get("/live-transcription")
    def live_transcription_status(learner_id: str = Path(min_length=1, max_length=120), owner=Depends(material_owner)):
        authorize(learner_id, owner)
        configured = live_transcription_enabled() and bool(os.getenv("OPENAI_API_KEY"))
        try:
            from .class_streaming import configuration
            configuration()
            return {'available': True, 'provider': 'AssemblyAI'}
        except Exception:
            pass
        return {"available": configured, "provider": "OpenAI" if configured else None}

    @router.post("/{recording_id}/live-transcription-session")
    def create_live_transcription_session(recording_id: str, learner_id: str, response: Response,
            x_capture_capability: str | None = Header(default=None, alias="X-Capture-Capability", min_length=32, max_length=128),
            owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        if not live_transcription_enabled():
            raise HTTPException(503, {"code": "live_transcription_disabled", "message": "Live captions are not enabled on this server."})
        with svc.store.engine.connect() as conn:
            row = conn.execute(text("""SELECT c.payload,r.status,r.expected_chunk_count
                FROM class_sessions c JOIN lecture_recordings r ON r.id=c.recording_id
                WHERE c.recording_id=:recording AND c.owner_id=:owner"""),
                {"recording": recording_id, "owner": owner}).mappings().first()
        if not row:
            raise HTTPException(404, {"code": "class_not_found", "message": "Class session unavailable."})
        class_data = json.loads(row["payload"])
        stored_capability_hash = class_data.get("captureCapabilityHash")
        presented_capability_hash = hashlib.sha256(x_capture_capability.encode("utf-8")).hexdigest() if x_capture_capability else ""
        if not stored_capability_hash or not hmac.compare_digest(presented_capability_hash, stored_capability_hash):
            raise HTTPException(409, {"code": "capture_capability_mismatch", "message": "Live captions are unavailable for this capture."})
        if row["status"] != "recording" or row["expected_chunk_count"] is not None:
            raise HTTPException(409, {"code": "capture_not_active", "message": "Live captions are only available during active capture."})
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        try:
            return live_provider().create_client_secret(owner)
        except RuntimeError as exc:
            raise HTTPException(503, {"code": "live_transcription_unavailable", "message": str(exc)}) from exc

    @router.post("/{recording_id}/live-transcription-segments")
    def save_live_transcription_segment(recording_id: str, body: ClassLiveTranscriptSegmentCreate, learner_id: str, response: Response,
            x_capture_capability: str | None = Header(default=None, alias="X-Capture-Capability", min_length=32, max_length=128),
            owner=Depends(material_owner), svc=Depends(service)):
        from .in_class_service import InClassService
        authorize(learner_id, owner)
        if not live_transcription_enabled():
            raise HTTPException(503, {"code": "live_transcription_disabled", "message": "Live captions are not enabled on this server."})
        response.headers["Cache-Control"] = "private, no-store"
        result=InClassService(svc.store).append_live_transcript(owner,"class_"+recording_id,x_capture_capability,body)
        return result

    @router.post("/{recording_id}/live-transcription-interim")
    def save_live_transcription_interim(recording_id: str, body: ClassLiveTranscriptInterimUpdate, learner_id: str, response: Response,
            x_capture_capability: str | None = Header(default=None, alias="X-Capture-Capability", min_length=32, max_length=128),
            owner=Depends(material_owner), svc=Depends(service)):
        from .in_class_service import InClassService
        from .class_live_notes import ClassLiveNoteService
        authorize(learner_id, owner)
        if not live_transcription_enabled():
            raise HTTPException(503, {"code": "live_transcription_disabled", "message": "Live captions are not enabled on this server."})
        response.headers["Cache-Control"] = "private, no-store"
        return ClassLiveNoteService(InClassService(svc.store)).append_interim(owner, "class_"+recording_id, x_capture_capability, body)

    @router.post("", status_code=201)
    def create(command: LectureCreate, learner_id: str = Path(min_length=1, max_length=120), owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: svc.create(owner, command))

    @router.get("")
    def listing(learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"recordings": svc.list_recordings(owner)}

    @router.get("/{recording_id}")
    def status(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: svc.status(owner, recording_id))

    @router.delete("/{recording_id}/audio")
    def remove_audio(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: svc.remove_audio(owner, recording_id))

    @router.put("/{recording_id}/chunks/{sequence}")
    async def upload(recording_id: str, sequence: int, request: Request, tasks: BackgroundTasks, learner_id: str,
                     x_chunk_start_ms: int = Header(alias="X-Chunk-Start-Ms"), x_chunk_end_ms: int = Header(alias="X-Chunk-End-Ms"),
                     x_chunk_sha256: str = Header(alias="X-Chunk-Sha256", min_length=64, max_length=64),
                     owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        length = request.headers.get("content-length")
        import json
        from sqlalchemy import text
        with svc.store.engine.connect() as conn:
            class_setup=conn.execute(text('SELECT payload FROM class_sessions WHERE recording_id=:id AND owner_id=:owner'),{'id':recording_id,'owner':owner}).scalar_one_or_none()
        if class_setup:
            expected=json.loads(class_setup)
            if expected.get('activeRunId'):
                from .class_devices import ClassDeviceService,digest
                with svc.store.engine.connect() as conn:
                    run=ClassDeviceService(svc.store).run(conn,owner,expected['id'],request.headers.get('x-capture-run',''))
                capability=request.headers.get('x-capture-capability','')
                if (not hmac.compare_digest(run['payload']['capabilityHash'],digest(capability))
                        or request.headers.get('x-capture-device')!=run['device_id'] or request.headers.get('x-capture-epoch')!=str(run['epoch'])):
                    raise HTTPException(409,{'code':'capture_device_mismatch','message':'This upload is not authorized for its recording run.'})
                base=run['payload']['sequenceBase']
                if sequence<base or x_chunk_start_ms<run['payload']['startMs']:
                    raise HTTPException(422,{'code':'capture_range_mismatch','message':'This slice is outside its recording run.'})
                if run['state'] in {'stopped','interrupted'} and (sequence>=base+run['payload']['sealedChunkCount'] or x_chunk_end_ms>run['payload']['audioEndMs']):
                    raise HTTPException(422,{'code':'capture_range_mismatch','message':'This recovered audio exceeds its sealed recording manifest.'})
            elif request.headers.get('x-capture-device')!=expected['deviceId'] or request.headers.get('x-capture-epoch')!=str(expected['captureEpoch']):
                raise HTTPException(409,{'code':'capture_device_mismatch','message':'This class is recording on another device. Join its views instead.'})
        try:
            declared = int(length) if length else 0
        except ValueError:
            declared = 0
        if declared > MAX_CHUNK_BYTES:
            raise HTTPException(status_code=413, detail={"code": "chunk_too_large", "message": "An audio slice must be smaller than 4 MB."})
        content = bytearray()
        async for part in request.stream():
            content.extend(part)
            if len(content) > MAX_CHUNK_BYTES:
                raise HTTPException(status_code=413, detail={"code": "chunk_too_large", "message": "An audio slice must be smaller than 4 MB."})
        result = translate(lambda: svc.put_chunk(owner, recording_id, sequence, bytes(content), start_ms=x_chunk_start_ms,
                                                   end_ms=x_chunk_end_ms, media_type=request.headers.get("content-type", ""), checksum=x_chunk_sha256))
        if class_setup:
            capture_run=run['id'] if expected.get('activeRunId') else None
            epoch=run['epoch'] if capture_run else expected.get('captureEpoch',1)
            with svc.store.transaction() as conn:
                chunk=conn.execute(text('SELECT id FROM lecture_audio_chunks WHERE recording_id=:recording AND sequence_number=:sequence'),{'recording':recording_id,'sequence':sequence}).scalar_one()
                previous=conn.execute(text('SELECT run_id,epoch FROM class_audio_sources WHERE chunk_id=:id AND owner_id=:owner'),{'id':chunk,'owner':owner}).mappings().first()
                if previous and (previous['run_id']!=capture_run or previous['epoch']!=epoch):raise HTTPException(409,{'code':'capture_source_conflict','message':'This audio slice already belongs to another capture run.'})
                conn.execute(text("INSERT INTO class_audio_sources(chunk_id,owner_id,class_id,run_id,epoch,source_kind) VALUES(:chunk,:owner,:class,:run,:epoch,'recorded_audio') ON CONFLICT(chunk_id) DO NOTHING"),{'chunk':chunk,'owner':owner,'class':expected['id'],'run':capture_run,'epoch':epoch})
        schedule_local(tasks, runner.drain)
        return result

    @router.post("/{recording_id}/finalize")
    def finalize(recording_id: str, command: LectureFinalize, tasks: BackgroundTasks, learner_id: str,
                 owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        with svc.store.engine.connect() as conn:
            active=conn.execute(text('SELECT r.state,r.payload FROM class_capture_runs r JOIN class_sessions c ON c.id=r.class_id WHERE c.recording_id=:recording AND r.owner_id=:owner ORDER BY r.epoch DESC LIMIT 1'),{'recording':recording_id,'owner':owner}).mappings().first()
        if active and (active['state']!='stopped' or not json.loads(active['payload']).get('endClass')):
            raise HTTPException(409,{'code':'capture_stop_unacknowledged','message':'The recording device must confirm Stop before this class can finish.'})
        result = translate(lambda: svc.finalize(owner, recording_id, command))
        schedule_local(tasks, runner.drain)
        return result

    @router.get("/{recording_id}/chunks")
    def chunks(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"chunks": translate(lambda: svc.chunks(owner, recording_id))}

    @router.get("/{recording_id}/chunks/{sequence}/audio")
    def audio(recording_id: str, sequence: int, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        content, mime = translate(lambda: svc.chunk_audio(owner, recording_id, sequence))
        return Response(content, media_type=mime, headers={"Cache-Control": "private, no-store",'X-Content-Type-Options':'nosniff'})

    @router.get("/{recording_id}/transcript")
    def transcript(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"segments": translate(lambda: svc.transcript(owner, recording_id))}

    @router.get("/{recording_id}/sections")
    def sections(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"sections": translate(lambda: svc.sections(owner, recording_id))}

    @router.patch('/{recording_id}/transcript/{segment_id}')
    def edit(recording_id: str, segment_id: str, command: TranscriptEdit, learner_id: str, tasks: BackgroundTasks, owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: LectureObservationService(svc.store).correct_transcript(owner, recording_id, segment_id, command.wording, command.revision))
        schedule_local(tasks, runner.drain)
        return result

    @router.get('/{recording_id}/observations')
    def observations(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: LectureObservationService(svc.store).listing(owner, recording_id))

    @router.post('/{recording_id}/observations')
    def observation(recording_id: str, command: ObservationEdit, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: LectureObservationService(svc.store).observe(owner, recording_id, command.model_dump(exclude_none=True)))

    @router.get("/{recording_id}/representation")
    def representation(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: {"sections": svc.sections(owner, recording_id), "entities": svc.entities(owner, recording_id)})

    @router.get("/{recording_id}/notes")
    def notes(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return translate(lambda: svc.note_blocks(owner, recording_id))

    @router.post("/{recording_id}/chunks/{sequence}/retry", status_code=202)
    def retry_chunk(recording_id: str, sequence: int, tasks: BackgroundTasks, learner_id: str,
                    owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.retry_chunk(owner, recording_id, sequence))
        schedule_local(tasks, runner.drain)
        return result

    @router.post("/{recording_id}/retry", status_code=202)
    def retry_failed(recording_id: str, tasks: BackgroundTasks, learner_id: str,
                     owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.retry_failed(owner, recording_id))
        schedule_local(tasks, runner.drain)
        return result

    @router.post("/{recording_id}/regenerate", status_code=202)
    def regenerate(recording_id: str, preferences: LecturePreferences, tasks: BackgroundTasks, learner_id: str,
                   owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.regenerate(owner, recording_id, preferences))
        schedule_local(tasks, runner.drain)
        return result

    return router
