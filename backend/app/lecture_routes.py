"""Owner-scoped API for durable, chunked lecture recordings."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path, Request
from fastapi.responses import FileResponse

from .lecture_models import LectureCreate, LectureFinalize, LecturePreferences
from .lecture_pipeline import LectureWorker
from .lecture_service import LectureError, LectureService, MAX_CHUNK_BYTES
from .material_routes import material_owner


def build_lecture_router(store_provider, provider_getter, transcriber=None):
    router = APIRouter(prefix="/v1/learners/{learner_id}/lecture-recordings", tags=["lecture-recordings"])

    def authorize(learner_id: str, owner: str):
        if learner_id != owner:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})

    def service(db=Depends(store_provider)):
        return LectureService(db)

    def worker(db=Depends(store_provider)):
        return LectureWorker(db, provider_getter, transcriber)

    def translate(operation):
        try:
            return operation()
        except LectureError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

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

    @router.put("/{recording_id}/chunks/{sequence}")
    async def upload(recording_id: str, sequence: int, request: Request, tasks: BackgroundTasks, learner_id: str,
                     x_chunk_start_ms: int = Header(alias="X-Chunk-Start-Ms"), x_chunk_end_ms: int = Header(alias="X-Chunk-End-Ms"),
                     x_chunk_sha256: str = Header(alias="X-Chunk-Sha256", min_length=64, max_length=64),
                     owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        length = request.headers.get("content-length")
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
        tasks.add_task(runner.drain)
        return result

    @router.post("/{recording_id}/finalize")
    def finalize(recording_id: str, command: LectureFinalize, tasks: BackgroundTasks, learner_id: str,
                 owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.finalize(owner, recording_id, command))
        tasks.add_task(runner.drain)
        return result

    @router.get("/{recording_id}/chunks")
    def chunks(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"chunks": translate(lambda: svc.chunks(owner, recording_id))}

    @router.get("/{recording_id}/chunks/{sequence}/audio")
    def audio(recording_id: str, sequence: int, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        path, mime = translate(lambda: svc.chunk_audio_path(owner, recording_id, sequence))
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, no-store"})

    @router.get("/{recording_id}/transcript")
    def transcript(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"segments": translate(lambda: svc.transcript(owner, recording_id))}

    @router.get("/{recording_id}/sections")
    def sections(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        authorize(learner_id, owner)
        return {"sections": translate(lambda: svc.sections(owner, recording_id))}

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
        tasks.add_task(runner.drain)
        return result

    @router.post("/{recording_id}/retry", status_code=202)
    def retry_failed(recording_id: str, tasks: BackgroundTasks, learner_id: str,
                     owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.retry_failed(owner, recording_id))
        tasks.add_task(runner.drain)
        return result

    @router.post("/{recording_id}/regenerate", status_code=202)
    def regenerate(recording_id: str, preferences: LecturePreferences, tasks: BackgroundTasks, learner_id: str,
                   owner=Depends(material_owner), svc=Depends(service), runner=Depends(worker)):
        authorize(learner_id, owner)
        result = translate(lambda: svc.regenerate(owner, recording_id, preferences))
        tasks.add_task(runner.drain)
        return result

    return router
