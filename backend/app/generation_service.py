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
from .generation_observability import purge_expired_outbox_snapshots
from .generation_store import GenerationStore, StaleGenerationWrite, TERMINAL
from .context_provenance import block_decision, provider_input_fingerprint
from .conversation_branching import ConversationBranchStore, classify_relation
from .journey_service import JourneyService
from .model_provider import ModelProviderError, OpenRouterLessonProvider, usage_metrics
from .teaching_output_limits import conversation_output_limit, teaching_output_limit
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
    async def append(self, generation_id: str, event_type: str, data: dict | None = None,
                     *, allow_cancelled_checkpoint: bool = False) -> GenerationEvent: ...
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

    async def append(self, generation_id: str, event_type: str, data: dict | None = None,
                     *, allow_cancelled_checkpoint: bool = False) -> GenerationEvent:
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
                if event.type in {"generation.completed", "generation.cancelled", "generation.interrupted", "generation.error"}:
                    return

    publish = append
    observe = subscribe


EventBuffer = InMemoryReplayEventStore


class DurableReplayEventStore:
    """Database backed replay, with polling so another worker can serve reconnects."""
    def __init__(self, records: GenerationStore):
        self.records = records
        self.conditions: dict[str, asyncio.Condition] = {}
        self.metadata: dict[str, dict] = {}
        self.owner_tokens: dict[str, str] = {}

    def bind_generation(self, generation_id: str, record: dict) -> None:
        self.metadata[generation_id] = {
            "branchId": record.get("branchId"),
            "contextRevision": record.get("contextRevision"),
        }
        token = record.get("ownerToken")
        if token:
            self.owner_tokens[generation_id] = token

    async def append(self, generation_id: str, event_type: str, data: dict | None = None,
                     *, allow_cancelled_checkpoint: bool = False) -> GenerationEvent:
        enriched = dict(data or {})
        for key, value in self.metadata.get(generation_id, {}).items():
            if value is not None:
                enriched.setdefault(key, value)
        owner_token = self.owner_tokens.get(generation_id)
        event = await asyncio.to_thread(
            self.records.append_event, generation_id, event_type, enriched, None, owner_token,
            allow_cancelled_checkpoint=allow_cancelled_checkpoint)
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
        self.branching = ConversationBranchStore(store)
        purge_expired_outbox_snapshots(store)
        self.buffer: ReplayEventStore = DurableReplayEventStore(self.records)
        self.tasks: dict[str, asyncio.Task] = {}
        self.observers: dict[str, int] = {}
        self.flush_characters = int(os.getenv("GENERATION_STREAM_FLUSH_CHARACTERS", "120"))
        self.flush_seconds = int(os.getenv("GENERATION_STREAM_FLUSH_MS", "300")) / 1000
        self.live_branching_enabled = os.getenv("LIVE_BRANCHING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        self.conversation_limit = max(1, min(4, int(os.getenv("GENERATION_PER_CONVERSATION_ACTIVE_LIMIT", "2"))))
        self.global_limit = max(1, int(os.getenv("GENERATION_GLOBAL_ACTIVE_LIMIT", "16")))
        self.lease_seconds = max(30.0, float(os.getenv("GENERATION_OWNER_LEASE_SECONDS", "90")))
        # Recovery is lease-based: an active execution owned by another live
        # worker is never interrupted just because this process started.
        self.records.interrupt_expired_leases()
        # Rows created before owner leases were introduced cannot be fenced.
        # Close only those legacy rows; all current workers claim a durable lease.
        self.records.interrupt_unowned_legacy()

    async def recovery_loop(self) -> None:
        """Reconcile expired owners and admit durable queued generations."""
        interval = max(2.0, min(15.0, self.lease_seconds / 4))
        while True:
            try:
                await asyncio.to_thread(self.records.interrupt_expired_leases)
                await asyncio.to_thread(self.records.interrupt_unowned_legacy)
                await asyncio.to_thread(purge_expired_outbox_snapshots, self.store)
                self._schedule_queued(provider=self.provider_getter() if self.provider_getter else self.provider)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("Generation recovery pass failed")
            await asyncio.sleep(interval)

    def create(self, owner: str, session_id: str, request: GenerationRequest, key: str) -> dict:
        provider = self.provider_getter() if self.provider_getter else self.provider
        if provider is not None:
            self.provider = provider
        from .material_service import MaterialService
        MaterialService(self.store).session(owner, session_id)
        if request.action == "message" and classify_relation(request.message, has_previous=True) == "cancel":
            record = self.records.accept_cancel_message(
                owner, session_id, request.model_dump(mode="json", by_alias=True), key,
                getattr(provider, "provider_name", "unknown"), getattr(provider, "model", "unknown"))
            target_id = record.get("cancelTargetGenerationId")
            task = self.tasks.get(target_id) if target_id else None
            if task and record.get("cancelTargetStatus") == "cancel_requested":
                task.cancel()
            return record
        journey_service = JourneyService(self.store, provider)
        record = self.records.create(owner, session_id, request.model_dump(mode="json", by_alias=True), key,
            getattr(provider, "provider_name", "pending"), getattr(provider, "model", "pending"),
            on_create=lambda conn, generation_id, submission: journey_service.submit_stream_turn(
                conn, owner, session_id, request, generation_id, submission),
            # A full slot queues durable accepted work. The feature flag controls
            # whether more than one generation may run at once, not acceptance.
            reject_if_active=False)
        created_now = bool(record.get("createdNow"))
        self.buffer.bind_generation(record["id"], record)
        if record.get("createdNow") and provider is not None:
            claimed = self._schedule_record(record, owner, request, provider)
            if claimed:
                record = claimed
                record["createdNow"] = created_now
        elif record["status"] == "queued" and provider is not None:
            self._schedule_queued(owner, session_id, provider)
        states = self.records.active_for_session(owner, session_id)
        record["scheduledGenerationIds"] = [item["id"] for item in states if item["status"] == "queued"]
        record["activeGenerationIds"] = [item["id"] for item in states if item["status"] != "queued"]
        return record

    def retry(self, owner: str, source_generation_id: str, key: str) -> dict:
        provider = self.provider_getter() if self.provider_getter else self.provider
        if provider is not None:
            self.provider = provider
        source = self.records.get(owner, source_generation_id)
        request = GenerationRequest.model_validate(source.get("request") or {})
        from .journey_service import JourneyService
        journey_service = JourneyService(self.store, provider)
        record = self.records.retry(owner, source_generation_id, key,
            provider=getattr(provider, "provider_name", source["provider"]),
            model=getattr(provider, "model", source["model"]),
            on_create=lambda connection, generation_id, submission: journey_service.submit_stream_turn(
                connection, owner, source["session"], request, generation_id, submission),
        )
        self.buffer.bind_generation(record["id"], record)
        created_now = bool(record.get("createdNow"))
        if created_now and provider is not None:
            claimed = self._schedule_record(record, owner, request, provider)
            if claimed:
                record = claimed
                record["createdNow"] = True
        elif record["status"] == "queued" and provider is not None:
            self._schedule_queued(owner, record["session"], provider)
        states = self.records.active_for_session(owner, record["session"])
        record["scheduledGenerationIds"] = [item["id"] for item in states if item["status"] == "queued"]
        record["activeGenerationIds"] = [item["id"] for item in states if item["status"] != "queued"]
        return record

    def _schedule_record(self, record: dict, owner: str, request: GenerationRequest, provider) -> dict | None:
        if provider is None:
            return None
        conversation_limit = self.conversation_limit if self.live_branching_enabled else 1
        global_limit = self.global_limit if self.live_branching_enabled else max(1, self.global_limit)
        claimed = self.records.claim_capacity(record["id"], conversation_limit=conversation_limit,
                                              global_limit=global_limit, lease_seconds=self.lease_seconds,
                                              provider=getattr(provider, "provider_name", "unknown"),
                                              model=getattr(provider, "model", "unknown"))
        if not claimed:
            return None
        self.buffer.bind_generation(claimed["id"], claimed)
        self.tasks[claimed["id"]] = asyncio.create_task(
            self._run(claimed["id"], owner, request, provider, claimed["ownerToken"]),
            name=claimed["id"])
        return claimed

    def _schedule_queued(self, owner: str | None = None, session_id: str | None = None, provider=None) -> None:
        chosen_provider = provider or (self.provider_getter() if self.provider_getter else self.provider)
        if not chosen_provider:
            return
        records = self.records.queued_global() if owner is None or session_id is None else self.records.queued_for_session(owner, session_id)
        for record in records:
            if record["id"] in self.tasks:
                continue
            conversation_limit = self.conversation_limit if self.live_branching_enabled else 1
            claimed = self.records.claim_capacity(record["id"], conversation_limit=conversation_limit,
                                                  global_limit=self.global_limit, lease_seconds=self.lease_seconds,
                                                  provider=getattr(chosen_provider, "provider_name", "unknown"),
                                                  model=getattr(chosen_provider, "model", "unknown"))
            if not claimed:
                continue
            request = GenerationRequest.model_validate(claimed["request"])
            self.buffer.bind_generation(claimed["id"], claimed)
            self.tasks[claimed["id"]] = asyncio.create_task(
                self._run(claimed["id"], claimed["owner"], request, chosen_provider, claimed["ownerToken"]),
                name=claimed["id"])

    async def _renew_owner_lease(self, generation_id: str, owner_token: str) -> None:
        interval = max(2.0, min(5.0, self.lease_seconds / 3))
        while generation_id in self.tasks:
            await asyncio.sleep(interval)
            if not self.records.renew_lease(generation_id, owner_token, self.lease_seconds):
                task = self.tasks.get(generation_id)
                if task and task is not asyncio.current_task():
                    task.cancel()
                return

    async def _run(self, generation_id: str, owner: str, request: GenerationRequest,
                   active_provider=None, owner_token: str | None = None) -> None:
        """Run under a durable owner/conversation usage scope, including recovered work."""
        record = self.records.get(owner, generation_id)
        from .usage.context import usage_scope

        # A request-created task happens to inherit request ContextVars, but a
        # queued task admitted by another worker does not. Bind the verified
        # owner explicitly so usage admission, reconciliation, and the
        # conversation spend ceiling apply on every execution path.
        with usage_scope(self.store, owner, record["session"]):
            await self._run_generation(generation_id, owner, request, active_provider, owner_token)

    async def _run_generation(self, generation_id: str, owner: str, request: GenerationRequest,
                   active_provider=None, owner_token: str | None = None) -> None:
        sequence = 0
        visual_task = None
        started_at = time.time()
        pending_text: list[str] = []
        pending_block_id = ""
        pending_text_started = 0.0
        pending_text_length = 0
        chosen_provider = active_provider if active_provider is not None else self.provider
        provider = copy.copy(chosen_provider) if isinstance(chosen_provider, OpenRouterLessonProvider) else chosen_provider
        heartbeat = asyncio.create_task(self._renew_owner_lease(generation_id, owner_token)) if owner_token else None

        async def flush_text(*, final_cancelled_checkpoint: bool = False) -> None:
            nonlocal sequence, pending_block_id, pending_text_started, pending_text_length
            if not pending_text:
                return
            body = "".join(pending_text)
            event = await self.buffer.append(generation_id, "text.delta",
                {"blockId": pending_block_id, "text": body},
                allow_cancelled_checkpoint=final_cancelled_checkpoint)
            sequence = event.sequence
            pending_text.clear()
            pending_block_id = ""
            pending_text_started = 0.0
            pending_text_length = 0
            if not final_cancelled_checkpoint:
                record = self.records.get(owner, generation_id)
                checkpoint = await self.buffer.append(generation_id, "generation.checkpoint", {
                    "outputSequence": record["outputSeq"],
                    "persistedLength": len(record["partialOutput"] or ""),
                })
                sequence = checkpoint.sequence

        async def publish_stream_operation(operation) -> None:
            nonlocal pending_block_id, pending_text_started, pending_text_length, sequence
            if operation.action == "delta":
                if pending_text and pending_block_id != operation.block_id:
                    await flush_text()
                if not pending_text:
                    pending_block_id = operation.block_id
                    pending_text_started = time.monotonic()
                pending_text.append(operation.text)
                pending_text_length += len(operation.text)
                if (pending_text_length >= self.flush_characters or
                        time.monotonic() - pending_text_started >= self.flush_seconds):
                    await flush_text()
                return
            await flush_text()
            event = await self._publish_lesson_operation(generation_id, operation)
            sequence = event.sequence

        try:
            record = self.records.get(owner, generation_id)
            if record.get("ownerToken") != owner_token or record["status"] != "preparing":
                return
            self.records.update_metrics(generation_id, {"startedAt": started_at, "queueSeconds": max(0, started_at - record["createdAt"])}, owner_token=owner_token)
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
                self.branching.context_snapshot(owner, generation_id),
            )
            prepared["visualType"] = request.visual_type
            for future in emitted_futures:
                await asyncio.wrap_future(future)
            if prepared.get("responseKind") == "social":
                context_ready_at = time.time()
                self.records.update_metrics(generation_id, {
                    "contextReadyAt": context_ready_at,
                    "contextBuildSeconds": context_ready_at - started_at,
                    "responseRoute": "social",
                    "modelInvoked": False,
                }, owner_token=owner_token)
                event = await self.buffer.append(generation_id, "generation.context_ready", {
                    "sourceCount": 0,
                    "actionId": prepared["actionId"],
                    "decision": "social_reply",
                })
                sequence = event.sequence
                if self.records.cancelled(generation_id):
                    await self._cancel(generation_id, owner_token)
                    return
                self.records.transition(generation_id, "streaming", owner_token=owner_token)
                block_id = f"social_{generation_id}"
                event = await self.buffer.append(generation_id, "lesson.block_started", {
                    "block": {"id": block_id, "kind": "explanation", "heading": ""},
                })
                sequence = event.sequence
                event = await self.buffer.append(generation_id, "text.delta", {
                    "blockId": block_id,
                    "text": prepared["directReply"],
                })
                sequence = event.sequence
                await self.buffer.append(generation_id, "generation.checkpoint", {
                    "outputSequence": self.records.get(owner, generation_id)["outputSeq"],
                    "persistedLength": len(prepared["directReply"]),
                })
                event = await self.buffer.append(generation_id, "lesson.block_completed", {"blockId": block_id})
                sequence = event.sequence
                self.records.transition(generation_id, "finalizing", sequence=sequence, owner_token=owner_token)
                with self.store.transaction() as connection:
                    from sqlalchemy import text
                    self.records.validate_owner(connection, generation_id, owner_token)
                    cancelled = connection.execute(text("SELECT cancellation_requested FROM generation_records WHERE id=:id AND owner_id=:owner"), {"id": generation_id, "owner": owner}).scalar_one()
                    if cancelled:
                        raise asyncio.CancelledError()
                    artifact, journey = JourneyService(self.store, provider).commit_stream(
                        connection, owner, prepared, request, prepared["directReply"], [],
                    )
                    result = {"lessonId": artifact.id, "revision": journey["revision"] + 1, "sessionId": journey["sessionId"]}
                    completed_at = time.time()
                    final_metrics = {
                        "completedAt": completed_at,
                        "completionSeconds": completed_at - started_at,
                        "outputCharacters": len(prepared["directReply"]),
                        "estimatedOutputTokens": 0,
                        "totalTokens": 0,
                        "promptTokens": 0,
                        "completionTokens": 0,
                        "usageSource": "estimated",
                        "responseRoute": "social",
                        "modelInvoked": False,
                    }
                    self.records.update_metrics(generation_id, final_metrics, connection, owner_token)
                    self.records.transition(generation_id, "completed", sequence=sequence, result=result,
                                            owner_token=owner_token, connection=connection)
                    self.records.append_event(generation_id, "generation.completed", {
                        "result": result,
                        "usage": {
                            "totalTokens": 0,
                            "promptTokens": 0,
                            "completionTokens": 0,
                            "usageSource": "estimated",
                            "provider": getattr(provider, "provider_name", "unknown"),
                            "model": getattr(provider, "model", "unknown"),
                        },
                    }, connection, owner_token)
                return
            context_ready_at = time.time()
            self.records.update_metrics(generation_id, {"contextReadyAt": context_ready_at, "contextBuildSeconds": context_ready_at - started_at}, owner_token=owner_token)
            await self.buffer.append(generation_id, "generation.context_ready", {"sourceCount": len(prepared["sources"]), "actionId": prepared["actionId"], "decision": prepared.get("decision")})
            for source in prepared["sources"]:
                await self.buffer.append(generation_id, "source.added", {"spanId": source.get("spanId"), "title": source.get("title")})
            if self.records.cancelled(generation_id):
                await self._cancel(generation_id, owner_token)
                return
            self.records.transition(generation_id, "streaming", owner_token=owner_token)
            from .visualization_planner import has_visual_simulation_update, plan_visualizations, should_reserve_visual
            from .openintelligentui import enabled as generated_visuals_enabled
            use_generated_visuals = generated_visuals_enabled()
            visual_question = request.message or prepared["question"]
            visual_reserved = use_generated_visuals or should_reserve_visual(visual_question) or request.visual_type != "auto" or has_visual_simulation_update(prepared, visual_question)
            if visual_reserved:
                await self.buffer.append(generation_id, "visualization.planning", {"blockIndex": 0, "afterParagraph": 0})
            if visual_reserved and not use_generated_visuals:
                visual_task = asyncio.create_task(asyncio.to_thread(
                    plan_visualizations, copy.copy(provider), prepared, visual_question
                ))
            visualizations = []
            visual_published = use_generated_visuals
            parser = ProgressiveLessonParser(generation_id, prepared["title"])
            chunks: list[str] = []
            first_delta_at = None
            provider_started_at = time.time()
            self.records.update_metrics(generation_id, {"providerStartedAt": provider_started_at}, owner_token=owner_token)
            provider_input = prepared["generationContext"] if getattr(provider, "supports_generation_context", False) else prepared["prompt"]
            context = prepared["generationContext"]
            output_limit = conversation_output_limit(request.gear, provider, context) if prepared.get("responseKind") == "conversation" else teaching_output_limit(request.gear, provider, context)
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
                "responseRoute": prepared.get("responseKind", "teaching"),
                "modelInvoked": True,
                "conversationStateVersion": prepared.get("conversationStateVersion", 0),
                "summaryUsed": any(block.kind == "conversationState" for block in context.blocks),
                "compactionTriggered": prepared.get("compactionTriggered", False),
                "automaticNoteCount": prepared.get("automaticNoteCount", 0),
                "retrievalUsed": any(block.kind == "sources" for block in context.blocks) or prepared.get("webRetrievalOccurred", False),
                "noteContextUsed": any(block.kind in {"learnerNotes", "automaticNotes"} for block in context.blocks),
                "learnerContextUsed": any(block.kind == "evidence" for block in context.blocks),
                "courseContextUsed": any(block.kind == "course" for block in context.blocks),
            }, owner_token=owner_token)
            provider_stream = provider.stream_text(provider_input, output_limit, images=prepared.get("images")) if prepared.get("images") else provider.stream_text(provider_input, output_limit)
            async for delta in provider_stream:
                if self.records.cancelled(generation_id):
                    await flush_text(final_cancelled_checkpoint=True)
                    await self._cancel(generation_id, owner_token)
                    return
                chunks.append(delta)
                if first_delta_at is None:
                    first_delta_at = time.time()
                    self.records.update_metrics(generation_id, {"firstDeltaAt": first_delta_at, "providerTtftSeconds": first_delta_at - provider_started_at, "applicationTtftSeconds": first_delta_at - started_at}, owner_token=owner_token)
                for operation in parser.feed(delta):
                    await publish_stream_operation(operation)
                if visual_task and visual_task.done() and not visual_published and parser.block_id:
                    try:
                        visualizations = visual_task.result()
                    except Exception:
                        visualizations = []
                        if use_generated_visuals:
                            await self.buffer.append(generation_id, "visualization.error", {"code": "VISUAL_UNAVAILABLE", "message": "The interactive visual could not be completed. Your explanation is still available."})
                    for spec in visualizations:
                        event = await self.buffer.append(generation_id, "visualization.ready", {"spec": spec.model_dump(mode="json", by_alias=True)})
                        sequence = event.sequence
                    if visual_reserved and not visualizations:
                        await self.buffer.append(generation_id, "visualization.skipped")
                    visual_published = True
            for operation in parser.finish():
                await publish_stream_operation(operation)
            await flush_text()
            body = "".join(chunks).strip()
            if not body:
                raise ModelProviderError("PROVIDER_ERROR")
            self.records.transition(generation_id, "finalizing", sequence=sequence, owner_token=owner_token)
            if not visual_published:
                try:
                    visualizations = await asyncio.wait_for(visual_task, timeout=180 if use_generated_visuals else 10) if visual_task else []
                except Exception:
                    visualizations = []
                    if use_generated_visuals:
                        await self.buffer.append(generation_id, "visualization.error", {"code": "VISUAL_UNAVAILABLE", "message": "The interactive visual could not be completed. Your explanation is still available."})
                for spec in visualizations:
                    event = await self.buffer.append(generation_id, "visualization.ready", {"spec": spec.model_dump(mode="json", by_alias=True)})
                    sequence = event.sequence
                if visual_reserved and not visualizations:
                    await self.buffer.append(generation_id, "visualization.skipped")
            with self.store.transaction() as connection:
                from sqlalchemy import text
                self.records.validate_owner(connection, generation_id, owner_token)
                cancelled = connection.execute(text("SELECT cancellation_requested FROM generation_records WHERE id=:id AND owner_id=:owner"), {"id": generation_id, "owner": owner}).scalar_one()
                if cancelled:
                    raise asyncio.CancelledError()
                artifact, journey = JourneyService(self.store, provider).commit_stream(connection, owner, prepared, request, body, visualizations)
                if use_generated_visuals:
                    from .visual_runs import VisualRuns
                    visual_run = VisualRuns(self.store).admit(connection, owner, artifact.session_id, artifact.id,
                        prepared, visual_question, generation_id + ':visual')
                    self.records.append_event(generation_id, 'visualization.queued', {'runId': visual_run['id'], 'lessonId': artifact.id}, connection, owner_token)
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
                self.records.update_metrics(generation_id, final_metrics, connection, owner_token)
                self.records.transition(generation_id, "completed", sequence=sequence, result=result,
                                        owner_token=owner_token, connection=connection)
                usage_event = {"result": result, "usage": {
                    "totalTokens": final_metrics.get("totalTokens", final_metrics.get("estimatedOutputTokens", 0)),
                    "promptTokens": final_metrics.get("promptTokens"),
                    "completionTokens": final_metrics.get("completionTokens"),
                    "usageSource": final_metrics.get("usageSource", "estimated"),
                    "provider": getattr(provider, "provider_name", "unknown"),
                    "model": getattr(provider, "model", "unknown"),
                }}
                self.records.append_event(generation_id, "generation.completed", usage_event, connection, owner_token)
        except asyncio.CancelledError:
            try:
                if self.records.cancelled(generation_id):
                    await flush_text(final_cancelled_checkpoint=True)
                    self.records.update_metrics(generation_id, {"cancelled": True, "completedAt": time.time()}, owner_token=owner_token)
                    await self._cancel(generation_id, owner_token)
                else:
                    await flush_text()
                    # A process shutdown or lost lease is not a learner Stop.
                    # Leave the checkpoint under its lease for the recovery loop.
                    logging.getLogger(__name__).info("Generation %s stopped with its worker; recovery will reconcile its lease", generation_id)
            except RuntimeError:
                pass
            raise
        except Exception as exc:
            # A user Stop can race a buffered checkpoint or provider failure.
            # Cancellation has priority over failure once it is durably recorded.
            try:
                if self.records.cancelled(generation_id):
                    await flush_text(final_cancelled_checkpoint=True)
                    self.records.update_metrics(generation_id, {
                        "cancelled": True,
                        "completedAt": time.time(),
                    }, owner_token=owner_token)
                    await self._cancel(generation_id, owner_token)
                    return
            except RuntimeError:
                pass
            try:
                await flush_text()
            except Exception:
                logging.getLogger(__name__).info("Generation %s could not flush its final text batch", generation_id)
            if isinstance(exc, StaleGenerationWrite) and not getattr(exc, "metric_recorded", False):
                self.records.record_stale_write()
                exc.metric_recorded = True
            logging.getLogger(__name__).exception("Generation %s failed", generation_id)
            code = error_code(exc)
            try:
                record = self.records.get(owner, generation_id)
                if record["status"] not in TERMINAL:
                    with self.store.transaction() as connection:
                        self.records.validate_owner(connection, generation_id, owner_token)
                        self.records.update_metrics(generation_id, {"errorCode": code, "completedAt": time.time()}, connection, owner_token)
                        self.records.transition(generation_id, "failed", error_code=code, sequence=sequence,
                                                owner_token=owner_token, connection=connection)
                        JourneyService(self.store, provider).finish_stream_turn(owner, record["session"], generation_id, "failed", code, connection)
                        detail = str(exc).strip() if isinstance(exc, ModelProviderError) else ""
                        message = detail if detail and detail not in ERRORS else "The generation could not be completed. Please try again."
                        self.records.append_event(generation_id, "generation.error", {"code": code, "message": message}, connection, owner_token)
            except RuntimeError:
                if self.records.cancelled(generation_id):
                    await self._cancel(generation_id, owner_token)
                    return
                # A fenced or expired owner may not publish or commit anything.
                logging.getLogger(__name__).info("Generation %s lost its execution lease", generation_id)
        finally:
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if visual_task and not visual_task.done():
                visual_task.cancel()
            self.tasks.pop(generation_id, None)
            self._schedule_queued(provider=provider)

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

    async def _cancel(self, generation_id: str, owner_token: str | None = None) -> None:
        # Cancellation is set durably before this method; do not publish a terminal
        # event until the provider iterator has been closed by the caller.
        try:
            with self.store.transaction() as connection:
                if owner_token is not None:
                    self.records.validate_owner(connection, generation_id, owner_token)
                record = self.records.transition(generation_id, "cancelled", error_code="CANCELLED",
                                                owner_token=owner_token, connection=connection)
                JourneyService(self.store, self.provider).finish_stream_turn(record["owner"], record["session"], generation_id, "cancelled", "CANCELLED", connection)
                self.records.append_event(generation_id, "generation.cancelled", {"code": "CANCELLED"}, connection, owner_token)
        except RuntimeError:
            return

    def cancel(self, owner: str, generation_id: str) -> dict:
        record = self.records.request_cancel(owner, generation_id)
        task = self.tasks.get(generation_id)
        if task and record["status"] == "cancel_requested":
            # Cancelling the task closes the async provider iterator/context at
            # once. The task emits the terminal event after the connection ends.
            task.cancel()
        elif record["status"] == "cancel_requested" and not record.get("capacityReserved"):
            # No worker owns a durable execution lease (typically a queued
            # item); it is safe to confirm cancellation here. If another
            # process owns the lease, leave this as a request until that owner
            # confirms it stopped or lease recovery fences it.
            try:
                with self.store.transaction() as connection:
                    cancelled = self.records.transition(generation_id, "cancelled", error_code="CANCELLED", connection=connection)
                    JourneyService(self.store, self.provider).finish_stream_turn(
                        owner, cancelled["session"], generation_id, "cancelled", "CANCELLED", connection)
                    self.records.append_event(generation_id, "generation.cancelled", {"code": "CANCELLED"}, connection)
            except RuntimeError:
                pass
        return record

    def _attach(self, generation_id: str) -> None:
        self.observers[generation_id] = self.observers.get(generation_id, 0) + 1

    def _detach(self, owner: str, generation_id: str) -> None:
        count = max(0, self.observers.get(generation_id, 1) - 1)
        self.observers[generation_id] = count
        # The durable execution outlives a tab or network reconnect. Learners
        # use the explicit Stop action when they want to cancel provider work.

    async def events(self, owner: str, generation_id: str, after: int) -> AsyncIterator[GenerationEvent]:
        record = self.records.get(owner, generation_id)
        self._attach(generation_id)
        try:
            async for event in self.buffer.subscribe(generation_id, after, record["status"] in TERMINAL):
                yield event
        finally:
            self._detach(owner, generation_id)
