"""Local data portability and deletion endpoints for the desktop application."""

from __future__ import annotations

import base64
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Header
from sqlalchemy import inspect, text

from .lecture_storage import LectureObjectStore


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"encoding": "base64", "value": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, Decimal):
        return str(value)
    return value


def build_privacy_router(store_provider: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["privacy"])

    def authorize(learner_id: str, claimed: str | None) -> None:
        from .identity import authorize_owner
        authorize_owner(learner_id)

    def local_store():
        store = store_provider()
        if os.getenv("AI_TUTOR_ENV", "development").lower() not in {"development", "local", "test"} or store.engine.dialect.name != "sqlite":
            raise HTTPException(status_code=404, detail={"code": "local_only", "message": "Local data controls are available in the desktop application only."})
        return store

    @router.get("/learners/{learner_id}/export")
    def export_data(
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> dict[str, Any]:
        authorize(learner_id, x_dev_learner_id)
        store = local_store()
        from .identity_data import export_owner
        return export_owner(store, learner_id)

    @router.delete("/learners/{learner_id}/data")
    def delete_data(
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> dict[str, Any]:
        authorize(learner_id, x_dev_learner_id)
        store = local_store()
        from .identity_data import erase_owner
        return erase_owner(store, learner_id)

    return router
