"""Owner-scoped API for the local Markdown workspace vault."""

from __future__ import annotations

import os
from .local_identity import local_identity_enabled
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Response, status

from .workspace_note_models import (
    WorkspaceNoteCreate,
    WorkspaceNoteContextManifest,
    WorkspaceNoteExport,
    WorkspaceNoteLinkCreate,
    WorkspaceNoteLinkRecord,
    WorkspaceNoteLinksResponse,
    WorkspaceNoteRecord,
    WorkspaceNoteReindexResponse,
    WorkspaceNoteSearchResponse,
    WorkspaceNoteSummary,
    WorkspaceNoteUpdate,
)
from .session_models import NoteContextInput
from .workspace_note_context import WorkspaceNoteContextService
from .workspace_note_service import WorkspaceNoteError, WorkspaceNoteService


def build_workspace_note_router(store_provider: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["workspace-notes"])

    def learner_path() -> Any:
        return Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")

    def authorize(learner_id: str, claimed: str | None) -> None:
        if not local_identity_enabled():
            raise HTTPException(status_code=503, detail={"code": "authentication_required", "message": "Development identity is disabled; configure an authentication provider."})
        if (claimed or "local") != learner_id:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "X-Dev-Learner-Id must match the learner path."})

    def service() -> WorkspaceNoteService:
        return WorkspaceNoteService(store_provider())

    def context_service() -> WorkspaceNoteContextService:
        return WorkspaceNoteContextService(store_provider())

    def translate(operation):  # type: ignore[no-untyped-def]
        try:
            return operation()
        except WorkspaceNoteError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    @router.post("/learners/{learner_id}/workspace-notes", response_model=WorkspaceNoteRecord, status_code=status.HTTP_201_CREATED)
    def create_note(request: WorkspaceNoteCreate, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().create(learner_id, request))

    @router.get("/learners/{learner_id}/workspace-notes", response_model=list[WorkspaceNoteSummary])
    def list_notes(learner_id: str = learner_path(),
                   x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[WorkspaceNoteSummary]:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().list(learner_id))

    @router.post("/learners/{learner_id}/workspace-notes/refresh-titles")
    def refresh_titles(learner_id: str = learner_path(),
                       x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> dict[str, int]:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().refresh_generated_titles(learner_id))

    @router.get("/learners/{learner_id}/workspace-notes/search", response_model=WorkspaceNoteSearchResponse)
    def search_notes(query: str = Query(default="", max_length=240), limit: int = Query(default=30, ge=1, le=100),
                     learner_id: str = learner_path(),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteSearchResponse:
        authorize(learner_id, x_dev_learner_id)
        return WorkspaceNoteSearchResponse(notes=translate(lambda: service().search(learner_id, query, limit)))

    @router.post("/learners/{learner_id}/workspace-notes/reindex", response_model=WorkspaceNoteReindexResponse)
    def reindex_notes(learner_id: str = learner_path(),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteReindexResponse:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().reindex(learner_id))

    @router.post("/learners/{learner_id}/workspace-note-context", response_model=WorkspaceNoteContextManifest)
    def resolve_note_context(request: NoteContextInput, learner_id: str = learner_path(),
                             x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteContextManifest:
        """Return the exact selected note excerpts that may enter one tutor call."""
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: context_service().resolve(learner_id, request))

    @router.get("/learners/{learner_id}/workspace-notes/export", response_model=WorkspaceNoteExport)
    def export_notes(learner_id: str = learner_path(),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteExport:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().export(learner_id))

    @router.get("/learners/{learner_id}/workspace-notes/{note_id}", response_model=WorkspaceNoteRecord)
    def get_note(note_id: str, learner_id: str = learner_path(),
                 x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get(learner_id, note_id))

    @router.get("/learners/{learner_id}/workspace-notes/{note_id}/links", response_model=WorkspaceNoteLinksResponse)
    def note_links(note_id: str, learner_id: str = learner_path(),
                   x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteLinksResponse:
        authorize(learner_id, x_dev_learner_id)
        return WorkspaceNoteLinksResponse(links=translate(lambda: service().list_links(learner_id, note_id)))

    @router.post("/learners/{learner_id}/workspace-notes/{note_id}/links", response_model=WorkspaceNoteLinkRecord, status_code=status.HTTP_201_CREATED)
    def create_note_link(request: WorkspaceNoteLinkCreate, note_id: str, learner_id: str = learner_path(),
                         x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteLinkRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().add_link(learner_id, note_id, request))

    @router.delete("/learners/{learner_id}/workspace-notes/{note_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_note_link(note_id: str, link_id: str, expected_revision: int = Query(alias="expectedRevision", ge=1), learner_id: str = learner_path(),
                         x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> Response:
        authorize(learner_id, x_dev_learner_id)
        translate(lambda: service().remove_link(learner_id, note_id, link_id, expected_revision))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/learners/{learner_id}/workspace-note-links/backlinks/{target_type}/{target_id}", response_model=WorkspaceNoteLinksResponse)
    def backlinks(target_type: str, target_id: str, learner_id: str = learner_path(),
                  x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteLinksResponse:
        authorize(learner_id, x_dev_learner_id)
        return WorkspaceNoteLinksResponse(links=translate(lambda: service().list_backlinks(learner_id, target_type, target_id)))

    @router.patch("/learners/{learner_id}/workspace-notes/{note_id}", response_model=WorkspaceNoteRecord)
    def update_note(request: WorkspaceNoteUpdate, note_id: str, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> WorkspaceNoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().update(learner_id, note_id, request))

    @router.delete("/learners/{learner_id}/workspace-notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_note(note_id: str, expected_revision: int = Query(alias="expectedRevision", ge=1), learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> Response:
        authorize(learner_id, x_dev_learner_id)
        translate(lambda: service().delete(learner_id, note_id, expected_revision))
        from .class_recording_service import ClassRecordingService
        ClassRecordingService(store_provider()).delete(learner_id, note_id)
        from .lecture_service import LectureService
        LectureService(store_provider()).delete(learner_id, note_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
