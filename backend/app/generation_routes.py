"""SSE observation endpoints for the shared Ask/Learn generation manager."""
from __future__ import annotations

import json
import hmac
import logging
import os
import asyncio
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from .generation_models import BranchSelectionRequest, GenerationRequest, OutboxMetricsRequest
from .generation_service import GenerationManager
from .generation_store import GenerationStore
from .generation_observability import live_branching_metrics, record_client_outbox_snapshot
from .conversation_branching import ConversationBranchStore
from .material_routes import material_owner
from .material_service import MaterialService, problem
from .visualization_service import VisualChange, VisualizationService

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _frame(event) -> str:
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {json.dumps(event.model_dump(mode='json', by_alias=True), ensure_ascii=False)}\n\n"


def build_generation_router(store_provider, provider_getter):
    router = APIRouter(prefix="/v1")
    manager = GenerationManager(store_provider(), provider_getter(), provider_getter)
    recovery_task: asyncio.Task | None = None

    @router.on_event("startup")
    async def start_generation_recovery():
        nonlocal recovery_task
        if recovery_task is None or recovery_task.done():
            manager._schedule_queued(provider=provider_getter())
            recovery_task = asyncio.create_task(manager.recovery_loop(), name="generation-recovery")

    @router.on_event("shutdown")
    async def stop_generation_recovery():
        nonlocal recovery_task
        if recovery_task and not recovery_task.done():
            recovery_task.cancel()
            await asyncio.gather(recovery_task, return_exceptions=True)
        recovery_task = None

    @router.post("/sessions/{sid}/generations", status_code=202)
    async def create(sid: str, command: GenerationRequest, key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200), owner=Depends(material_owner)):
        started = time.perf_counter()
        record = manager.create(owner, sid, command, key)
        if record.get("createdNow") and record.get("id"):
            latency_ms = (time.perf_counter() - started) * 1000
            try:
                manager.records.record_acceptance_latency(record["id"], latency_ms)
            except Exception:
                # Metrics are best-effort; they must never turn a durable
                # acceptance into a failed HTTP submission.
                logging.getLogger(__name__).exception("Could not persist generation acceptance latency")
            record["metrics"] = {**(record.get("metrics") or {}), "acceptanceLatencyMs": latency_ms}
        return GenerationStore.descriptor(record)

    @router.get("/operations/live-branching/metrics")
    def live_branching_operations_metrics(
        hours: int = Query(default=24, ge=1, le=720),
        token: str | None = Header(default=None, alias="X-OpenLearn-Metrics-Token"),
    ):
        expected = os.getenv("LIVE_BRANCHING_METRICS_TOKEN", "")
        if not expected:
            raise HTTPException(status_code=404, detail="Not found")
        if not token or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return live_branching_metrics(manager.store, hours)

    @router.get("/sessions/{sid}/branches")
    def branches(sid: str, owner=Depends(material_owner)):
        MaterialService(manager.store).session(owner, sid)
        return ConversationBranchStore(manager.store).list_branches(owner, sid)

    @router.put("/sessions/{sid}/outbox-metrics", status_code=204)
    def record_outbox_metrics(sid: str, command: OutboxMetricsRequest, owner=Depends(material_owner)):
        if sum((command.queued_count, command.sending_count, command.accepted_count,
                command.failed_count, command.choice_count)) > 30:
            raise HTTPException(status_code=422, detail="Outbox snapshot exceeds the supported queue size")
        MaterialService(manager.store).session(owner, sid)
        record_client_outbox_snapshot(manager.store, owner, sid, command)
        return Response(status_code=204)

    @router.post("/sessions/{sid}/branches/{branch_id}/select")
    def select_branch(sid: str, branch_id: str, command: BranchSelectionRequest,
                      owner=Depends(material_owner)):
        MaterialService(manager.store).session(owner, sid)
        return ConversationBranchStore(manager.store).select_branch(
            owner, sid, branch_id, command.expected_branch_revision)

    @router.get("/generations/{generation_id}")
    def get(generation_id: str, owner=Depends(material_owner)):
        return GenerationStore.descriptor(manager.records.get(owner, generation_id))

    @router.post("/generations/{generation_id}/retry", status_code=202)
    async def retry_generation(
        generation_id: str,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
        owner=Depends(material_owner),
    ):
        started = time.perf_counter()
        record = manager.retry(owner, generation_id, key)
        if record.get("createdNow") and record.get("id"):
            latency_ms = (time.perf_counter() - started) * 1000
            try:
                manager.records.record_acceptance_latency(record["id"], latency_ms)
            except Exception:
                logging.getLogger(__name__).exception("Could not persist retry acceptance metric")
            record["metrics"] = {**(record.get("metrics") or {}), "acceptanceLatencyMs": latency_ms}
        return GenerationStore.descriptor(record)

    @router.get("/lessons/{lesson_id}/visualizations/{visualization_id}")
    def get_lesson_visualization(lesson_id: str, visualization_id: str, owner=Depends(material_owner)):
        artifact = manager.store.get_artifact(lesson_id)
        if artifact is None:
            problem("not_found", "This lesson is not available.", 404)
        MaterialService(manager.store).session(owner, artifact.session_id)
        for block in artifact.blocks:
            for value in block.visualizations:
                if value.get("id") == visualization_id:
                    return value
        problem("not_found", "This visualization is not available.", 404)

    @router.patch("/lessons/{lesson_id}/visualizations/{visualization_id}")
    def change_lesson_visualization(lesson_id: str, visualization_id: str, command: VisualChange, owner=Depends(material_owner)):
        return VisualizationService(manager.store).change(owner, lesson_id, visualization_id, command)

    @router.get("/generations/{generation_id}/context")
    def context_inspector(generation_id: str, owner=Depends(material_owner)):
        if os.getenv("AI_TUTOR_DEV_CONTEXT_INSPECTOR") != "1":
            raise HTTPException(status_code=404, detail="Context inspector is disabled")
        record = manager.records.get(owner, generation_id)
        session = MaterialService(manager.store).session(owner, record["session"])
        metrics = record.get("metrics") or {}
        try:
            by_block = json.loads(metrics.get("contextTokensByBlock") or "{}")
        except (TypeError, ValueError):
            by_block = {}
        def parsed_metric(name, fallback):
            try:
                return json.loads(metrics.get(name) or "")
            except (TypeError, ValueError):
                return fallback
        return {
            "generationId": record["id"], "conversationId": record["session"],
            "courseId": session.course_id,
            "mode": record["mode"], "provider": record["provider"], "model": record["model"],
            "contextVersion": metrics.get("contextVersion"),
            "contextSchemaVersion": metrics.get("contextSchemaVersion"),
            "providerInputFingerprintKind": metrics.get("providerInputFingerprintKind"),
            "providerInputSerialization": metrics.get("providerInputSerialization"),
            "providerInputSha256": metrics.get("providerInputSha256"),
            "providerInputStored": False,
            "blockDecisions": parsed_metric("contextDecisions", []),
            "omissionReasons": parsed_metric("contextOmissionReasons", []),
            "conversationStateVersion": metrics.get("conversationStateVersion"),
            "included": (metrics.get("contextIncluded") or "").split(",") if metrics.get("contextIncluded") else [],
            "omitted": (metrics.get("contextOmitted") or "").split(",") if metrics.get("contextOmitted") else [],
            "estimatedTokensByBlock": by_block,
            "recentMessageCount": metrics.get("recentMessageCount"),
            "recentEstimatedTokens": metrics.get("recentEstimatedTokens"),
            "estimatedInputTokens": metrics.get("estimatedInputTokens"),
            "inputBudgetTokens": metrics.get("contextBudgetTokens"),
            "summaryUsed": metrics.get("summaryUsed"),
            "compactionTriggered": metrics.get("compactionTriggered"),
            "exactPromptTokens": metrics.get("promptTokens") if metrics.get("usageSource") == "exact" else None,
        }

    @router.get("/generations/{generation_id}/events")
    async def events(generation_id: str, after: int = 0, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), owner=Depends(material_owner)):
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))
        async def stream():
            async for event in manager.events(owner, generation_id, after):
                if event.data.get("heartbeat"):
                    yield ": heartbeat\n\n"
                else:
                    yield _frame(event)
        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    @router.post("/generations/{generation_id}/cancel", status_code=202)
    def cancel(generation_id: str, owner=Depends(material_owner)):
        return GenerationStore.descriptor(manager.cancel(owner, generation_id))

    return router
