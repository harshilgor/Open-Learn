"""Owner-scoped class recording upload and processing endpoints."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import text

from .class_recording_service import ClassRecordingError, ClassRecordingService, MAX_AUDIO_BYTES
from .material_routes import material_owner
from .workflow_store import WorkflowStore


def build_class_recording_router(store_provider, provider_getter):
    router = APIRouter(prefix="/v1", tags=["class-recordings"])

    def service(db=Depends(store_provider)):
        return ClassRecordingService(db, provider_getter())

    def translate(action):
        try:
            return action()
        except ClassRecordingError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    @router.put("/learners/{learner_id}/workspace-notes/{note_id}/class-recording")
    async def upload(note_id: str, request: Request, tasks: BackgroundTasks,
                     learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        if learner_id != owner:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})
        length = request.headers.get("content-length")
        try:
            declared_length = int(length) if length else 0
        except ValueError:
            declared_length = 0
        if declared_length > MAX_AUDIO_BYTES:
            from fastapi import HTTPException
            raise HTTPException(status_code=413, detail={"code": "recording_too_large", "message": "This recording exceeds the 24 MB processing limit."})
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_AUDIO_BYTES:
                from fastapi import HTTPException
                raise HTTPException(status_code=413, detail={"code": "recording_too_large", "message": "This recording exceeds the 24 MB processing limit."})
        media_type = request.headers.get("content-type", "application/octet-stream")
        try:
            duration = int(request.headers.get("x-recording-duration-ms", "0"))
        except ValueError:
            duration = 0
        try:
            markers = [int(value) for value in request.headers.get("x-recording-markers-ms", "").split(",") if value.strip()][:500]
        except ValueError:
            markers = []
        record = translate(lambda: svc.upload(owner, note_id, bytes(data), media_type, min(max(duration, 0), 24 * 60 * 60 * 1000), markers))
        WorkflowStore(svc.store).enqueue(owner, record["id"], "class_recording", {}, "class-recording:" + record["id"])
        return record

    @router.get("/learners/{learner_id}/workspace-notes/{note_id}/class-recording")
    def get(note_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        if learner_id != owner:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})
        with svc.store.engine.connect() as conn:
            row = conn.execute(text("SELECT id FROM class_recordings WHERE learner_id=:owner AND note_id=:note ORDER BY created_at DESC LIMIT 1"), {"owner": owner, "note": note_id}).first()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail={"code": "recording_not_found", "message": "Class recording not found."})
        return translate(lambda: svc.get(owner, row[0]))

    @router.get("/learners/{learner_id}/class-recordings/{recording_id}/audio")
    def audio(recording_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        if learner_id != owner:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})
        record = translate(lambda: svc.get(owner, recording_id))
        path = svc._path(owner, recording_id)
        return FileResponse(path, media_type=record["mediaType"], filename="class-recording")

    @router.post("/learners/{learner_id}/workspace-notes/{note_id}/class-recording/retry", status_code=202)
    def retry(note_id: str, learner_id: str, tasks: BackgroundTasks, owner=Depends(material_owner), svc=Depends(service)):
        if learner_id != owner:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})
        record, should_run = translate(lambda: svc.retry(owner, note_id))
        if should_run:
            jobs = WorkflowStore(svc.store)
            job = jobs.enqueue(owner, record["id"], "class_recording", {}, "class-recording:" + record["id"])
            with svc.store.transaction() as conn:
                conn.execute(text("UPDATE learning_jobs SET status='queued',attempt_count=0,next_retry_at=0,error_code=NULL WHERE id=:id AND status='failed'"), {"id": job["id"]})
        return record

    @router.delete("/learners/{learner_id}/workspace-notes/{note_id}/class-recording", status_code=204)
    def delete(note_id: str, learner_id: str, owner=Depends(material_owner), svc=Depends(service)):
        if learner_id != owner:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "Learner scope mismatch."})
        svc.delete(owner, note_id)
        return Response(status_code=204)

    return router
