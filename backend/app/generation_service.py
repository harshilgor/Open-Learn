"""Shared durable generation orchestrator and bounded live event buffer."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from .generation_models import GenerationEvent, GenerationRequest
from .generation_store import GenerationStore, TERMINAL
from .context_provenance import block_decision, provider_input_fingerprint
from .journey_service import JourneyService
from .model_provider import ModelProviderError, OpenRouterLessonProvider, usage_metrics
from .teaching_output_limits import teaching_output_limit
from .streaming_lesson import ProgressiveLessonParser

ERRORS = {"VALIDATION_FAILED", "CONTEXT_FAILED", "PROVIDER_TIMEOUT", "PROVIDER_ERROR", "VISION_UNSUPPORTED", "STREAM_INTERRUPTED", "REPLAY_EXPIRED", "CANCELLED", "PERSISTENCE_FAILED", "REVISION_CONFLICT"}


def error_code(exc: Exception) -> str:
    text = str(exc)
    if text in ERRORS:
        return text
    if "revision" in text.lower():
        return "REVISION_CONFLICT"
    if isinstance(exc, ModelProviderError):
        return "PROVIDER_ERROR"
    return "CONTEXT_FAILED"


@dataclass
class _Channel:
    events: deque[GenerationEvent] = field(default_factory=lambda: deque(maxlen=int(os.getenv("GENERATION_STREAM_REPLAY_EVENT_LIMIT", "800"))))
    sequence: int = 0
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class ReplayEventStore(Protocol):
    async def append(self, generation_id: str, event_type: str, data: dict | None = None) -> GenerationEvent: ...
    def get_after_sequence(self, generation_id: str, after: int) -> list[GenerationEvent]: ...
    def subscribe(self, generation_id: str, after: int, terminal: bool) -> AsyncIterator[GenerationEvent]: ...
    def expire(self, generation_id: str) -> None: ...
    def has_channel(self, generation_id: str) -> bool: ...


class InMemoryReplayEventStore:
    """In-process replay implementation; replaceable by a shared deployment store."""
    def __init__(self):
        self.channels: dict[str, _Channel] = {}

    def channel(self, generation_id: str) -> _Channel:
        return self.channels.setdefault(generation_id, _Channel())

    async def append(self, generation_id: str, event_type: str, data: dict | None = None) -> GenerationEvent:
        channel = self.channel(generation_id)
        async with channel.condition:
            channel.sequence += 1
            event = GenerationEvent(generation_id=generation_id, sequence=channel.sequence, type=event_type, data=data or {})
            channel.events.append(event)
            channel.condition.notify_all()
            return event

    def get_after_sequence(self, generation_id: str, after: int) -> list[GenerationEvent]:
        channel = self.channels.get(generation_id)
        return [event for event in channel.events if event.sequence > after] if channel else []

    def has_channel(self, generation_id: str) -> bool:
        return generation_id in self.channels

    def expire(self, generation_id: str) -> None:
        self.channels.pop(generation_id, None)

    async def subscribe(self, generation_id: str, after: int, terminal: bool) -> AsyncIterator[GenerationEvent]:
        channel = self.channel(generation_id)
        while True:
            async with channel.condition:
                replay = [event for event in channel.events if event.sequence > after]
                if replay:
                    pass
                elif terminal:
                    return
                else:
                    try:
                        await asyncio.wait_for(channel.condition.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        yield GenerationEvent(generation_id=generation_id, sequence=after, type="generation.context_ready", data={"heartbeat": True})
                    continue
            for event in replay:
                after = event.sequence
                yield event
                if event.type in {"generation.completed", "generation.cancelled", "generation.error"}:
                    return

    publish = append
    observe = subscribe


EventBuffer = InMemoryReplayEventStore


class DurableReplayEventStore:
    """Database backed replay, with polling so another worker can serve reconnects."""
    def __init__(self, records: GenerationStore):
        self.records = records
        self.conditions: dict[str, asyncio.Condition] = {}

    async def append(self, generation_id: str, event_type: str, data: dict | None = None) -> GenerationEvent:
        event = await asyncio.to_thread(self.records.append_event, generation_id, event_type, data)
        condition = self.conditions.get(generation_id)
        if condition:
            async with condition:
                condition.notify_all()
        return event

    def get_after_sequence(self, generation_id: str, after: int) -> list[GenerationEvent]:
        return self.records.events_after(generation_id, after)

    def has_channel(self, generation_id: str) -> bool:
        return True

    def expire(self, generation_id: str) -> None:
        self.conditions.pop(generation_id, None)

    async def subscribe(self, generation_id: str, after: int, terminal: bool) -> AsyncIterator[GenerationEvent]:
        condition = self.conditions.setdefault(generation_id, asyncio.Condition())
        last_heartbeat = time.monotonic()
        while True:
            events = await asyncio.to_thread(self.records.events_after, generation_id, after)
            for event in events:
                after = event.sequence
                yield event
                if event.type in {"generation.completed", "generation.cancelled", "generation.error"}:
                    return
            if terminal:
                return
            # Observe status changes from another worker or a process restart.
            with self.records.store.engine.connect() as conn:
                from sqlalchemy import text
                row = conn.execute(text("SELECT status FROM generation_records WHERE id=:id"), {"id": generation_id}).first()
            if row and row[0] in TERMINAL:
                terminal = True
                continue
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
            if time.monotonic() - last_heartbeat >= 15:
                last_heartbeat = time.monotonic()
                yield GenerationEvent(generation_id=generation_id, sequence=after, type="generation.context_ready", data={"heartbeat": True})


class GenerationManager:
    def __init__(self, store, provider, provider_getter=None):
        self.store = store
        self.provider = provider
        self.provider_getter = provider_getter
        self.records = GenerationStore(store)
        self.buffer: ReplayEventStore = DurableReplayEventStore(self.records)
        self.tasks: dict[str, asyncio.Task] = {}
        self.observers: dict[str, int] = {}
        self.disconnect_handles: dict[str, asyncio.TimerHandle] = {}
        self.disconnect_grace_seconds = float(os.getenv("GENERATION_STREAM_DISCONNECT_GRACE_SECONDS", "30"))
        self.flush_characters = int(os.getenv("GENERATION_STREAM_FLUSH_CHARACTERS", "120"))
        self.flush_seconds = int(os.getenv("GENERATION_STREAM_FLUSH_MS", "80")) / 1000

    def create(self, owner: str, session_id: str, request: GenerationRequest, key: str) -> dict:
        provider = self.provider_getter() if self.provider_getter else self.provider
        if not provider:
            raise ModelProviderError("Connect a model provider before starting a generation.")
        self.provider = provider
        from .material_service import MaterialService
        MaterialService(self.store).session(owner, session_id)
        journey_service = JourneyService(self.store, provider)
        record = self.records.create(owner, session_id, request.model_dump(mode="json", by_alias=True), key,
            getattr(provider, "provider_name", "unknown"), getattr(provider, "model", "unknown"),
            on_create=lambda conn, generation_id: journey_service.submit_stream_turn(conn, owner, session_id, request, generation_id))
        if record["status"] == "queued" and record["id"] not in self.tasks:
            self.tasks[record["id"]] = asyncio.create_task(self._run(record["id"], owner, request, provider), name=record["id"])
        return record

    async def _run(self, generation_id: str, owner: str, request: GenerationRequest, active_provider=None) -> None:
        sequence = 0
        visual_task = None
        started_at = time.time()
        chosen_provider = active_provider if active_provider is not None else self.provider
        provider = copy.copy(chosen_provider) if isinstance(chosen_provider, OpenRouterLessonProvider) else chosen_provider
        try:
            try:
                self.records.transition(generation_id, "preparing")
            except RuntimeError:
                # An idempotent retry in another worker may have claimed this
                # generation already. Its owner continues the stream.
                if self.records.get(owner, generation_id)["status"] == "cancel_requested":
                    await self._cancel(generation_id)
                return
            self.records.update_metrics(generation_id, {"startedAt": started_at, "queueSeconds": max(0, started_at - self.records.get(owner, generation_id)["createdAt"])})
            await self.buffer.append(generation_id, "generation.started", {"mode": request.mode, "gear": request.gear.value})
            loop = asyncio.get_running_loop()
            emitted_futures = []

            def emit_event(event_type: str, data: dict | None = None):
                emitted_futures.append(asyncio.run_coroutine_threadsafe(
                    self.buffer.append(generation_id, event_type, data),
                    loop,
                ))

            prepared = await asyncio.to_thread(
                JourneyService(self.store, provider).prepare_stream,
                owner,
                request_session_id := self.records.get(owner, generation_id)["session"],
                request,
                lambda: self.records.cancelled(generation_id),
                emit_event,
                generation_id,
            )
            prepared["visualType"] = request.visual_type
            for future in emitted_futures:
                await asyncio.wrap_future(future)
            context_ready_at = time.time()
            self.records.update_metrics(generation_id, {"contextReadyAt": context_ready_at, "contextBuildSeconds": context_ready_at - started_at})
            await self.buffer.append(generation_id, "generation.context_ready", {"sourceCount": len(prepared["sources"]), "actionId": prepared["actionId"], "decision": prepared.get("decision")})
            for source in prepared["sources"]:
                await self.buffer.append(generation_id, "source.added", {"spanId": source.get("spanId"), "title": source.get("title")})
            if self.records.cancelled(generation_id):
                await self._cancel(generation_id)
                return
            self.records.transition(generation_id, "streaming")
            from .visualization_planner import has_visual_simulation_update, plan_visualizations, should_reserve_visual
            visual_question = request.message or prepared["question"]
            visual_reserved = should_reserve_visual(visual_question) or request.visual_type != "auto" or has_visual_simulation_update(prepared, visual_question)
            if visual_reserved:
                await self.buffer.append(generation_id, "visualization.planning", {"blockIndex": 0, "afterParagraph": 0})
            if visual_reserved:
                visual_task = asyncio.create_task(asyncio.to_thread(
                    plan_visualizations, copy.copy(provider), prepared, visual_question
                ))
            visualizations = []
            visual_published = False
            parser = ProgressiveLessonParser(generation_id, prepared["title"])
            chunks: list[str] = []
            first_delta_at = None
            provider_started_at = time.time()
            self.records.update_metrics(generation_id, {"providerStartedAt": provider_started_at})
            provider_input = prepared["generationContext"] if getattr(provider, "supports_generation_context", False) else prepared["prompt"]
            context = prepared["generationContext"]
            output_limit = teaching_output_limit(request.gear, provider, context)
            block_decisions = [block_decision(block) for block in context.blocks]
            wire_payload = provider.streaming_payload(provider_input, output_limit, prepared.get("images")) if hasattr(provider, "streaming_payload") else provider_input
            # Hash the exact provider-facing payload together with the model and
            # provider identity. Persist only this digest and safe decisions;
            # the payload can contain learner text, note excerpts, or images.
            provider_name = getattr(provider, "provider_name", "unknown")
            model_name = getattr(provider, "model", "unknown")
            wire_digest = provider_input_fingerprint(provider_name, model_name, wire_payload)
            self.records.update_metrics(generation_id, {
                "contextVersion": wire_digest,
                "contextSchemaVersion": 3,
                "providerInputFingerprintKind": "provider_model_and_serialized_payload_sha256",
                "providerInputSerialization": "canonical_json_utf8_v1",
                "contextDecisions": json.dumps(block_decisions, ensure_ascii=False),
                "contextOmissionReasons": json.dumps(context.omission_reasons, ensure_ascii=False),
                "providerInputSha256": wire_digest,
                "estimatedInputTokens": context.estimated_input_tokens,
                "contextBudgetTokens": context.budget_tokens,
                "requestedOutputTokens": output_limit,
                "recentMessageCount": len(context.recent_messages),
                "contextBlockCount": len(context.blocks),
                "contextOmittedCount": len(context.omitted),
                "contextIncluded": ",".join(block.kind for block in context.blocks),
                "contextOmitted": ",".join(context.omitted),
                "contextTokensByBlock": json.dumps({block.kind: block.estimated_tokens for block in context.blocks}, sort_keys=True),
                "recentEstimatedTokens": sum(max(1, len(message["content"].encode("utf-8")) // 3) for message in context.recent_messages),
                "conversationStateVersion": prepared.get("conversationStateVersion", 0),
                "summaryUsed": any(block.kind == "conversationState" for block in context.blocks),
                "compactionTriggered": prepared.get("compactionTriggered", False),
                "automaticNoteCount": prepared.get("automaticNoteCount", 0),
                "retrievalUsed": any(block.kind == "sources" for block in context.blocks) or prepared.get("webRetrievalOccurred", False),
                "noteContextUsed": any(block.kind in {"learnerNotes", "automaticNotes"} for block in context.blocks),
                "learnerContextUsed": any(block.kind == "evidence" for block in context.blocks),
                "courseContextUsed": any(block.kind == "course" for block in context.blocks),
            })
            provider_stream = provider.stream_text(provider_input, output_limit, images=prepared.get("images")) if prepared.get("images") else provider.stream_text(provider_input, output_limit)
            async for delta in provider_stream:
                if self.records.cancelled(generation_id):
                    await self._cancel(generation_id)
                    return
                chunks.append(delta)
                if first_delta_at is None:
                    first_delta_at = time.time()
                    self.records.update_metrics(generation_id, {"firstDeltaAt": first_delta_at, "providerTtftSeconds": first_delta_at - provider_started_at, "applicationTtftSeconds": first_delta_at - started_at})
                for operation in parser.feed(delta):
                    event = await self._publish_lesson_operation(generation_id, operation)
                    sequence = event.sequence
                if visual_task and visual_task.done() and not visual_published and parser.block_id:
                    try:
                        visualizations = visual_task.result()
                    except Exception:
                        visualizations = []
                    for spec in visualizations:
                        event = await self.buffer.append(generation_id, "visualization.ready", {"spec": spec.model_dump(mode="json", by_alias=True)})
                        sequence = event.sequence
                    if visual_reserved and not visualizations:
                        await self.buffer.append(generation_id, "visualization.skipped")
                    visual_published = True
            for operation in parser.finish():
                event = await self._publish_lesson_operation(generation_id, operation)
                sequence = event.sequence
            body = "".join(chunks).strip()
            if not body:
                raise ModelProviderError("PROVIDER_ERROR")
            self.records.transition(generation_id, "finalizing", sequence=sequence)
            if not visual_published:
                try:
                    visualizations = await asyncio.wait_for(visual_task, timeout=10) if visual_task else []
                except Exception:
                    visualizations = []
                for spec in visualizations:
                    event = await self.buffer.append(generation_id, "visualization.ready", {"spec": spec.model_dump(mode="json", by_alias=True)})
                    sequence = event.sequence
                if visual_reserved and not visualizations:
                    await self.buffer.append(generation_id, "visualization.skipped")
            with self.store.transaction() as connection:
                from sqlalchemy import text
                cancelled = connection.execute(text("SELECT cancellation_requested FROM generation_records WHERE id=:id AND owner_id=:owner"), {"id": generation_id, "owner": owner}).scalar_one()
                if cancelled:
                    raise asyncio.CancelledError()
                artifact, journey = JourneyService(self.store, provider).commit_stream(connection, owner, prepared, request, body, visualizations)
                result = {"lessonId": artifact.id, "revision": journey["revision"] + 1, "sessionId": journey["sessionId"]}
                completed_at = time.time(); elapsed = max(completed_at - (first_delta_at or provider_started_at), .001)
                exact_usage = getattr(provider, "last_usage", None)
                provider_label = str(getattr(provider, "provider_name", "unknown") or "unknown").split("/")[0].lower()
                if provider_label not in {"openrouter", "openai"}:
                    provider_label = "openrouter" if not bool(getattr(provider, "is_openai", False)) else "openai"
                final_metrics: dict = {"completedAt": completed_at, "completionSeconds": completed_at - started_at,
                    "outputCharacters": len(body), "estimatedOutputTokens": max(1, len(body) // 4), "estimatedTokensPerSecond": (len(body) / 4) / elapsed}
                exact_fragment = usage_metrics(exact_usage, provider=provider_label) if exact_usage is not None else {}
                if exact_fragment:
                    final_metrics.update(exact_fragment)
                else:
                    final_metrics["usageSource"] = "estimated"
                    final_metrics["usageProvider"] = provider_label
                self.records.update_metrics(generation_id, final_metrics, connection)
                self.records.transition(generation_id, "completed", sequence=sequence, result=result, connection=connection)
                usage_event = {"result": result, "usage": {
                    "totalTokens": final_metrics.get("totalTokens", final_metrics.get("estimatedOutputTokens", 0)),
                    "promptTokens": final_metrics.get("promptTokens"),
                    "completionTokens": final_metrics.get("completionTokens"),
                    "usageSource": final_metrics.get("usageSource", "estimated"),
                    "provider": getattr(provider, "provider_name", "unknown"),
                    "model": getattr(provider, "model", "unknown"),
                }}
                self.records.append_event(generation_id, "generation.completed", usage_event, connection)
        except asyncio.CancelledError:
            self.records.update_metrics(generation_id, {"cancelled": True, "completedAt": time.time()})
            await self._cancel(generation_id)
            raise
        except Exception as exc:
            logging.getLogger(__name__).exception("Generation %s failed", generation_id)
            code = error_code(exc)
            record = self.records.get(owner, generation_id)
            if record["status"] not in TERMINAL:
                with self.store.transaction() as connection:
                    self.records.update_metrics(generation_id, {"errorCode": code, "completedAt": time.time()}, connection)
                    self.records.transition(generation_id, "failed", error_code=code, sequence=sequence, connection=connection)
                    JourneyService(self.store, provider).finish_stream_turn(owner, record["session"], generation_id, "failed", code, connection)
                    detail = str(exc).strip() if isinstance(exc, ModelProviderError) else ""
                    message = detail if detail and detail not in ERRORS else "The generation could not be completed. Please try again."
                    self.records.append_event(generation_id, "generation.error", {"code": code, "message": message}, connection)
        finally:
            if visual_task and not visual_task.done():
                visual_task.cancel()
            self.tasks.pop(generation_id, None)

    async def _publish_lesson_operation(self, generation_id, operation):
        if operation.action == "start":
            return await self.buffer.append(generation_id, "lesson.block_started", {"block": {"id": operation.block_id, "kind": operation.kind, "heading": operation.heading}})
        if operation.action == "complete":
            return await self.buffer.append(generation_id, "lesson.block_completed", {"blockId": operation.block_id})
        return await self.buffer.append(generation_id, "text.delta", {"blockId": operation.block_id, "text": operation.text})

    @staticmethod
    def _plan_visualizations(provider, prepared, body):
        """Compatibility wrapper for existing planner callers."""
        from .visualization_planner import plan_visualizations
        return plan_visualizations(provider, prepared, body)

    async def _cancel(self, generation_id: str) -> None:
        # Cancellation is set durably before this method; do not publish a terminal
        # event until the provider iterator has been closed by the caller.
        try:
            with self.store.transaction() as connection:
                record = self.records.transition(generation_id, "cancelled", error_code="CANCELLED", connection=connection)
                JourneyService(self.store, self.provider).finish_stream_turn(record["owner"], record["session"], generation_id, "cancelled", "CANCELLED", connection)
                self.records.append_event(generation_id, "generation.cancelled", {"code": "CANCELLED"}, connection)
        except RuntimeError:
            return

    def cancel(self, owner: str, generation_id: str) -> dict:
        record = self.records.request_cancel(owner, generation_id)
        task = self.tasks.get(generation_id)
        if task and record["status"] == "cancel_requested":
            # Cancelling the task closes the async provider iterator/context at
            # once. The task emits the terminal event after the connection ends.
            task.cancel()
        return record

    def _attach(self, generation_id: str) -> None:
        self.observers[generation_id] = self.observers.get(generation_id, 0) + 1
        handle = self.disconnect_handles.pop(generation_id, None)
        if handle:
            handle.cancel()

    def _detach(self, owner: str, generation_id: str) -> None:
        count = max(0, self.observers.get(generation_id, 1) - 1)
        self.observers[generation_id] = count
        if count or generation_id not in self.tasks:
            return
        loop = asyncio.get_running_loop()
        self.disconnect_handles[generation_id] = loop.call_later(
            self.disconnect_grace_seconds,
            lambda: asyncio.create_task(self._cancel_after_disconnect(owner, generation_id)),
        )

    async def _cancel_after_disconnect(self, owner: str, generation_id: str) -> None:
        if self.observers.get(generation_id, 0) == 0 and generation_id in self.tasks:
            self.cancel(owner, generation_id)

    async def events(self, owner: str, generation_id: str, after: int) -> AsyncIterator[GenerationEvent]:
        record = self.records.get(owner, generation_id)
        self._attach(generation_id)
        try:
            async for event in self.buffer.subscribe(generation_id, after, record["status"] in TERMINAL):
                yield event
        finally:
            self._detach(owner, generation_id)
