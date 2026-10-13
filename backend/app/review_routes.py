"""HTTP surface for Review dashboard and sessions."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path

from .material_routes import material_owner
from .model_provider import ModelProviderError
from .review.concept_sync import ConceptSyncService
from .review.models import (
    ReviewAnswerCommand,
    ReviewAskTutorResponse,
    ReviewConceptHistory,
    ReviewConfidenceCommand,
    ReviewDashboard,
    ReviewRevisionCommand,
    ReviewSessionCreate,
    ReviewSessionPublic,
)
from .review.session_service import ReviewSessionService
from .workflow_store import WorkflowStore

log = logging.getLogger(__name__)


def _authorize(learner_id: str, claimed: str | None) -> None:
    from .identity import authorize_owner
    authorize_owner(learner_id)



from .usage.context import usage_job

@usage_job
def run_review_job(store, provider, job_id: str) -> None:
    records = WorkflowStore(store)
    job = records.claim(job_id)
    if not job:
        return
    owner, target, payload, kind = job["owner_id"], job["target_id"], job["payload"], job["kind"]
    service = ReviewSessionService(store, provider)
    sync = ConceptSyncService(store, provider)
    try:
        with store.transaction() as conn:
            if kind == "review_create":
                # Creation is sync in the route; job reserved for heavy prep if needed.
                result = {"sessionId": target}
            elif kind == "review_answer":
                graded = service.grade(owner, target, payload["itemId"], ReviewAnswerCommand.model_validate(payload["command"]))
                result = service.commit_grade(conn, owner, graded)
            elif kind == "concept_sync":
                result = sync.sync_from_text(owner, **payload)
            elif kind == "review_backfill":
                result = sync.backfill(owner)
            else:
                raise ValueError("Unsupported review job")
            records.finish(conn, job, result)
    except Exception as exc:
        log.warning("Review job %s failed (%s)", job["id"], type(exc).__name__)
        from fastapi import HTTPException
        message = str(exc) if isinstance(exc, ModelProviderError) else (
            exc.detail.get("message", "Please reload and try again.")
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
            else "This review operation could not be completed. Your previous work is saved."
        )
        try:
            with store.transaction() as conn:
                records.finish(conn, job, {"message": message}, "failed")
        except Exception:
            pass


def build_review_router(store_provider: Any, provider_getter: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["review"])

    def enqueue(tasks: BackgroundTasks, db, owner, target, kind, payload, key):
        job = WorkflowStore(db).enqueue(owner, target, kind, payload, key)
        tasks.add_task(run_review_job, db, provider_getter(), job["id"])
        return job

    @router.get("/learners/{learner_id}/review", response_model=ReviewDashboard)
    def dashboard(
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
        db=Depends(store_provider),
    ) -> ReviewDashboard:
        _authorize(learner_id, x_dev_learner_id)
        return ReviewSessionService(db, provider_getter()).dashboard(learner_id)

    @router.post("/learners/{learner_id}/review/backfill", status_code=202)
    def backfill(
        tasks: BackgroundTasks,
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
        db=Depends(store_provider),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        _authorize(learner_id, x_dev_learner_id)
        return enqueue(tasks, db, learner_id, learner_id, "review_backfill", {}, key)

    @router.get("/learners/{learner_id}/concepts/{concept_id}/review-history", response_model=ReviewConceptHistory)
    def concept_history(
        concept_id: str,
        learner_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
        db=Depends(store_provider),
    ) -> ReviewConceptHistory:
        _authorize(learner_id, x_dev_learner_id)
        return ReviewSessionService(db, provider_getter()).concept_history(learner_id, concept_id)

    @router.get("/learning-jobs/{job_id}")
    def get_review_job(job_id: str, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider)):
        job = WorkflowStore(db).job(owner, job_id)
        if job["status"] in {"queued", "running"}:
            tasks.add_task(run_review_job, db, provider_getter(), job_id)
        return job

    @router.post("/review/sessions", status_code=201)
    def create_session(
        command: ReviewSessionCreate,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ):
        result = ReviewSessionService(db, provider_getter()).create(owner, command)
        return result

    @router.get("/review/sessions/{session_id}", response_model=ReviewSessionPublic)
    def get_session(session_id: str, owner=Depends(material_owner), db=Depends(store_provider)) -> ReviewSessionPublic:
        return ReviewSessionService(db, provider_getter()).public(owner, session_id)

    @router.post("/review/sessions/{session_id}/items/{item_id}/answer", status_code=202)
    def answer(
        session_id: str,
        item_id: str,
        command: ReviewAnswerCommand,
        tasks: BackgroundTasks,
        owner=Depends(material_owner),
        db=Depends(store_provider),
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        WorkflowStore(db).read(owner, session_id, "review_session")
        WorkflowStore(db).read(owner, item_id, "review_item")
        return enqueue(tasks, db, owner, session_id, "review_answer", {"itemId": item_id, "command": command.model_dump(mode="json")}, key)

    @router.post("/review/sessions/{session_id}/items/{item_id}/confidence", response_model=ReviewSessionPublic)
    def confidence(
        session_id: str,
        item_id: str,
        command: ReviewConfidenceCommand,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ) -> ReviewSessionPublic:
        return ReviewSessionService(db, provider_getter()).record_confidence(owner, session_id, item_id, command)

    @router.post("/review/sessions/{session_id}/items/{item_id}/skip", response_model=ReviewSessionPublic)
    def skip(
        session_id: str,
        item_id: str,
        command: ReviewRevisionCommand,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ) -> ReviewSessionPublic:
        return ReviewSessionService(db, provider_getter()).skip(owner, session_id, item_id, command.expected_revision)

    @router.post("/review/sessions/{session_id}/items/{item_id}/remediate", response_model=ReviewSessionPublic)
    def remediate(
        session_id: str,
        item_id: str,
        command: ReviewRevisionCommand,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ) -> ReviewSessionPublic:
        return ReviewSessionService(db, provider_getter()).remediate(owner, session_id, item_id, command.expected_revision)

    @router.post("/review/sessions/{session_id}/complete", response_model=ReviewSessionPublic)
    def complete(
        session_id: str,
        command: ReviewRevisionCommand,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ) -> ReviewSessionPublic:
        return ReviewSessionService(db, provider_getter()).complete(owner, session_id, command.expected_revision)

    @router.post("/review/sessions/{session_id}/items/{item_id}/ask-tutor", response_model=ReviewAskTutorResponse)
    def ask_tutor(
        session_id: str,
        item_id: str,
        owner=Depends(material_owner),
        db=Depends(store_provider),
    ) -> ReviewAskTutorResponse:
        return ReviewSessionService(db, provider_getter()).ask_tutor(owner, session_id, item_id)

    return router
