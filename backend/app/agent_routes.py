"""HTTP boundary for bounded, learner-owned agent tasks."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse

from .agent_models import AgentDocument, AgentDocumentCreate, AgentTask, AgentTaskCreate, AgentTaskEvent
from .agent_service import AgentTaskError, AgentTaskService


def build_agent_router(store_provider: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["agent-tasks"])

    def learner_path() -> Any:
        return Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")

    def authorize(learner_id: str, claimed: str | None) -> None:
        if os.getenv("AI_TUTOR_DEV_IDENTITY", "true").lower() not in {"1", "true", "yes"}:
            raise HTTPException(status_code=503, detail={"code": "authentication_required", "message": "Development identity is disabled; configure an authentication provider."})
        if (claimed or "local") != learner_id:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "X-Dev-Learner-Id must match the learner path."})

    def service() -> AgentTaskService:
        return AgentTaskService(store_provider())

    def translate(operation):  # type: ignore[no-untyped-def]
        try:
            return operation()
        except AgentTaskError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    @router.post("/learners/{learner_id}/documents", response_model=AgentDocument, status_code=status.HTTP_201_CREATED)
    def create_document(request: AgentDocumentCreate, learner_id: str = learner_path(),
                        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> AgentDocument:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().create_document(learner_id, request))

    @router.get("/learners/{learner_id}/documents", response_model=list[AgentDocument])
    def list_documents(learner_id: str = learner_path(),
                       x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[AgentDocument]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_documents(learner_id)

    @router.get("/learners/{learner_id}/documents/{document_id}", response_model=AgentDocument)
    def get_document(document_id: str, learner_id: str = learner_path(),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> AgentDocument:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get_document(learner_id, document_id))

    @router.post("/learners/{learner_id}/agent-tasks", response_model=AgentTask, status_code=status.HTTP_202_ACCEPTED)
    def create_task(request: AgentTaskCreate, background_tasks: BackgroundTasks, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> AgentTask:
        authorize(learner_id, x_dev_learner_id)
        task = translate(lambda: service().create_task(learner_id, request, idempotency_key))
        # The command boundary returns the durable task immediately.  A worker
        # can replace this local background runner without changing the UI or
        # task/event contracts; clients simply observe the persisted stages.
        if task.status.value == "queued":
            background_tasks.add_task(AgentTaskService(store_provider()).run_task, learner_id, task.id)
        return task

    @router.get("/learners/{learner_id}/agent-tasks", response_model=list[AgentTask])
    def list_tasks(learner_id: str = learner_path(), limit: int = Query(default=50, ge=1, le=100),
                   x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[AgentTask]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_tasks(learner_id, limit)

    @router.get("/learners/{learner_id}/agent-tasks/{task_id}", response_model=AgentTask)
    def get_task(task_id: str, learner_id: str = learner_path(),
                 x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> AgentTask:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get_task(learner_id, task_id))

    @router.post("/learners/{learner_id}/agent-tasks/{task_id}/cancel", response_model=AgentTask)
    def cancel_task(task_id: str, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> AgentTask:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().cancel_task(learner_id, task_id))

    @router.get("/learners/{learner_id}/agent-tasks/{task_id}/events", response_model=list[AgentTaskEvent])
    def list_events(task_id: str, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[AgentTaskEvent]:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().list_events(learner_id, task_id))

    @router.get("/learners/{learner_id}/agent-tasks/{task_id}/events/stream")
    def stream_events(task_id: str, learner_id: str = learner_path(),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> StreamingResponse:
        authorize(learner_id, x_dev_learner_id)
        events = translate(lambda: service().list_events(learner_id, task_id))

        def stream():
            for event in events:
                yield f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(event.data, separators=(',', ':'))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
