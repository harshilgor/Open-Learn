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
        if os.getenv("AI_TUTOR_DEV_IDENTITY", "true").lower() not in {"1", "true", "yes"}:
            raise HTTPException(status_code=503, detail={"code": "authentication_required", "message": "Development identity is disabled; configure an authentication provider."})
        if (claimed or "local") != learner_id:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "X-Dev-Learner-Id must match the learner path."})

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
        tables = [name for name in inspect(store.engine).get_table_names() if name != "alembic_version"]
        records: dict[str, list[dict[str, Any]]] = {}
        with store.engine.connect() as connection:
            for table in tables:
                columns = [column["name"] for column in inspect(store.engine).get_columns(table)]
                rows = connection.execute(text(f"SELECT * FROM {_identifier(table)}")).mappings().all()
                records[table] = [{column: _json_value(row.get(column)) for column in columns} for row in rows]
        return {"format": "forma-local-export", "version": 1, "learner_id": learner_id, "tables": records}

    @router.delete("/learners/{learner_id}/data")
    def delete_data(
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> dict[str, Any]:
        authorize(learner_id, x_dev_learner_id)
        store = local_store()
        tables = [name for name in inspect(store.engine).get_table_names() if name != "alembic_version"]
        deleted: dict[str, int] = {}
        lecture_objects: list[tuple[str, str, str]] = []
        with store.engine.begin() as connection:
            object_keys = [row[0] for row in connection.execute(text("SELECT object_key FROM material_versions WHERE object_key IS NOT NULL"))]
            if {"lecture_recordings", "lecture_audio_chunks"}.issubset(tables):
                lecture_objects = [tuple(row) for row in connection.execute(text("""
                    SELECT r.learner_id,c.recording_id,c.storage_key FROM lecture_audio_chunks c
                    JOIN lecture_recordings r ON r.id=c.recording_id
                """))]
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            for table in tables:
                result = connection.execute(text(f"DELETE FROM {_identifier(table)}"))
                deleted[table] = int(result.rowcount or 0)
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        material_root = FilePath(os.getenv("AI_TUTOR_MATERIAL_DIR", str(FilePath(__file__).resolve().parents[1] / "data" / "materials"))).resolve()
        for key in object_keys:
            if isinstance(key, str) and key.isidentifier():
                (material_root / key).unlink(missing_ok=True)
        objects = LectureObjectStore()
        for owner, recording_id, storage_key in lecture_objects:
            objects.delete(owner, recording_id, storage_key)
        return {"deleted": deleted, "total": sum(deleted.values())}

    return router
