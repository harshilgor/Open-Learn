"""Local backup and restore API; no cloud or credential access."""
from __future__ import annotations
import base64
import os
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .backup_service import BackupError, BackupService

class RestoreRequest(BaseModel):
    archive_base64: str = Field(alias="archiveBase64", min_length=1)
    confirm_replace: bool = Field(default=False, alias="confirmReplace")

def build_backup_router(store_provider: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["backup"])
    def service() -> BackupService:
        store = store_provider()
        if os.getenv("AI_TUTOR_ENV", "development").lower() not in {"development", "local", "test"} or store.engine.dialect.name != "sqlite":
            raise HTTPException(404, detail={"code":"local_only", "message":"Backup is available in local Forma only."})
        from sqlalchemy import text
        with store.engine.connect() as connection:
            if connection.execute(text('SELECT 1 FROM identity_accounts LIMIT 1')).first():
                raise HTTPException(409, detail={'code': 'account_backup_restricted', 'message': 'Whole-installation backup and restore are disabled after account linking. Use account export; restores must preserve deletion tombstones.'})
        return BackupService(store)
    def authorize(claimed: str | None) -> None:
        if os.getenv("AI_TUTOR_DEV_IDENTITY", "true").lower() not in {"1","true","yes"} or (claimed or "local") != "local":
            raise HTTPException(403, detail={"code":"learner_scope_mismatch", "message":"Backup is scoped to the local learner."})
    def translate(call):
        try: return call()
        except BackupError as exc: raise HTTPException(exc.status_code, detail={"code":exc.code,"message":exc.message}) from exc
    @router.get("/local-backup")
    def create(x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")):
        authorize(x_dev_learner_id)
        return {"format":"forma-local-backup", "archiveBase64": base64.b64encode(translate(lambda: service().create())).decode("ascii")}
    @router.post("/local-backup/preflight")
    def preflight(request: RestoreRequest, x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")):
        authorize(x_dev_learner_id)
        try: payload = base64.b64decode(request.archive_base64, validate=True)
        except Exception as exc: raise HTTPException(422, detail={"code":"invalid_archive","message":"Backup data is not valid base64."}) from exc
        return translate(lambda: service().preflight(payload))
    @router.post("/local-backup/restore")
    def restore(request: RestoreRequest, x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")):
        authorize(x_dev_learner_id)
        try: payload = base64.b64decode(request.archive_base64, validate=True)
        except Exception as exc: raise HTTPException(422, detail={"code":"invalid_archive","message":"Backup data is not valid base64."}) from exc
        return translate(lambda: service().restore(payload, confirm_replace=request.confirm_replace))
    return router
