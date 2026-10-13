"""Durable learner-memory jobs, run by worker.tick (§7.1).

Enqueueing happens inside the transaction that commits the turn, so a job
exists exactly when its turn does. The job itself runs off the chat path.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from . import extraction, policy, store, validator

log = logging.getLogger(__name__)

KIND_EXTRACT = "memory_extract"
KIND_CONSOLIDATE = "memory_consolidate"
KIND_EPISODE = "memory_episode"


def enqueue_extraction(store_, conn, owner, *, session_id, generation_id, request):
    """Queue extraction for a committed learner message; never fails the turn."""
    try:
        if not policy.extraction_enabled() or not generation_id:
            return None
        message = getattr(request, "message", None)
        if getattr(request, "action", "message") != "message" or not isinstance(message, str) or not message.strip():
            return None
        if not store.get_settings(conn, owner)["learning_enabled"]:
            return None
        from ..workflow_store import WorkflowStore
        payload = {"sessionId": session_id, "generationId": generation_id,
                   "pastedRanges": [{"start": item.start, "end": item.end} for item in getattr(request, "pasted_ranges", None) or []],
                   "timezone": getattr(request, "client_timezone", None)}
        return WorkflowStore(store_).enqueue(owner, session_id, KIND_EXTRACT, payload, f"memory_extract:{generation_id}",
                                           connection=conn, queue="batch", max_attempts=3)
    except Exception as exc:
        log.warning("memory extraction was not queued (%s)", type(exc).__name__)
        return None


def _day_start(now: float) -> float:
    moment = datetime.fromtimestamp(now, timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _today(now: float, timezone_name: str | None):
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return datetime.fromtimestamp(now, zone).date()


def _turn(store_, owner, session_id, generation_id):
    from fastapi import HTTPException
    from ..workflow_store import WorkflowStore
    try:
        journey = WorkflowStore(store_).read(owner, f"journey_{session_id}", "journey")
    except HTTPException:
        return None, None
    for index, turn in enumerate((journey or {}).get("turns") or []):
        if turn.get("generationId") == generation_id:
            return index, turn
    return None, None


def extract_turn(store_, owner, payload, *, extractor=None, now=None):
    """Run one extraction; returns a content-free result summary."""
    now = now or time.time()
    mode = policy.extraction_mode()
    if not policy.extraction_enabled():
        return {"status": "skipped", "reason": "disabled"}
    with store_.engine.connect() as conn:
        if not store.get_settings(conn, owner)["learning_enabled"]:
            return {"status": "skipped", "reason": "learning_paused"}
        if store.extraction_jobs_since(conn, owner, _day_start(now)) > policy.MAX_EXTRACTIONS_PER_DAY:
            return {"status": "skipped", "reason": "daily_extraction_cap"}
    index, turn = _turn(store_, owner, payload["sessionId"], payload["generationId"])
    if turn is None or turn.get("status") not in {None, "completed"} or not isinstance(turn.get("question"), str):
        return {"status": "skipped", "reason": "turn_unavailable"}
    message = turn["question"]
    reply = "\n".join(str(block.get("body", "")) for block in (turn.get("lesson") or {}).get("blocks", []))
    from ..material_service import MaterialService
    session = MaterialService(store_).session(owner, payload["sessionId"])
    with store_.engine.connect() as conn:
        courses = [tuple(row) for row in conn.execute(text("SELECT id,name FROM courses WHERE owner_id=:owner AND archived_at IS NULL"), {"owner": owner})]
        existing = store.context_facts(conn, owner, message)
        remaining = policy.MAX_FACTS_PER_DAY - store.facts_written_since(conn, owner, _day_start(now))
    if remaining <= 0:
        return {"status": "skipped", "reason": "daily_fact_cap"}
    course_name = next((name for identifier, name in courses if identifier == session.course_id), None)
    today = _today(now, payload.get("timezone"))
    prompt = extraction.build_request(message=message, reply=reply, existing_facts=existing, today=today.isoformat(),
                                      timezone_name=payload.get("timezone"), course_name=course_name)
    candidates = extraction.extract(extractor or extraction.configured_extractor(), prompt)
    outcome = validator.validate(candidates, message=message, pasted_ranges=payload.get("pastedRanges") or (), today=today,
                                 courses=courses, known_fact_ids=[fact["id"] for fact in existing],
                                 remaining_today=remaining, shadow=mode == "shadow")
    turn_basis = {"type": "turn", "sessionId": payload["sessionId"], "turnIndex": index, "generationId": payload["generationId"]}
    actions = {"created": 0, "deduplicated": 0, "existing": 0}
    superseded = 0
    changed_ids = []
    with store_.transaction() as conn:
        for accepted in outcome.accepted:
            action, fact_id, replaced = store.write_extracted(conn, owner, accepted, turn_basis=turn_basis, now=now)
            actions[action] += 1
            superseded += len(replaced)
            if action == "created" and mode == "on":
                changed_ids.append(fact_id)
        store.delete_shadow_facts_before(conn, owner, now - policy.SHADOW_RETENTION_DAYS * 86400)
        if mode == "on" and (actions["created"] or superseded):
            from . import consolidation, profile
            profile.rebuild_if_enabled(conn, owner, now=now)
            consolidation.record_change(conn, owner, "learning", {"learned": actions["created"], "updated": superseded},
                                        fact_ids=changed_ids, now=now)
    rejected = {}
    for reason in outcome.rejected:
        rejected[reason] = rejected.get(reason, 0) + 1
    return {"status": "extracted", "mode": mode, "candidates": len(candidates) if isinstance(candidates, list) else 0,
            **actions, "superseded": superseded, "rejected": rejected, "promptVersion": policy.EXTRACTION_PROMPT_VERSION}


def run_memory_extract(store_, provider, job_id, *, extractor=None):
    """Worker entry point; follows the lease conventions of run_hypothesis."""
    from sqlalchemy.exc import IntegrityError
    from ..execution import LeaseHeartbeat, failure_policy, job_scope
    from ..performance import span
    from ..usage.context import usage_scope
    from ..workflow_store import WorkflowStore
    jobs = WorkflowStore(store_)
    job = jobs.claim(job_id)
    if not job:
        return
    heartbeat = LeaseHeartbeat(store_, job)
    try:
        with job_scope(job), usage_scope(store_, job["owner_id"], job["target_id"]):
            try:
                with span("memory_extract_job"):
                    result = extract_turn(store_, job["owner_id"], job["payload"], extractor=extractor)
            except extraction.ExtractionUnavailable:
                result = {"status": "skipped", "reason": "model_unavailable"}
            with store_.transaction() as conn:
                jobs.finish(conn, job, result)
    except IntegrityError:
        # A concurrent job won the one-active-fact-per-subject index (§11.2).
        # Retrying sees that fact and supersedes or deduplicates instead.
        log.warning("memory extraction raced another job; retrying")
        jobs.fail(job, "worker_failed", retryable=True)
    except Exception as exc:
        code, retry = failure_policy(exc)
        log.warning("memory extraction failed (%s)", type(exc).__name__)
        jobs.fail(job, code, retryable=retry)
    finally:
        heartbeat.close()


# --- Phase E: consolidation and episodes (§9.3) ----------------------------------

def note_activity(conn, owner):
    """At turn commit: mark the owner for consolidation. Never fails the turn."""
    if not policy.consolidation_enabled():
        return
    try:
        with conn.begin_nested():
            store.touch_activity(conn, owner)
    except Exception as exc:
        log.warning("memory activity was not recorded (%s)", type(exc).__name__)


def enqueue_consolidations(store_, *, now=None):
    """Queue today's consolidation for owners with recent memory activity (bounded)."""
    if not policy.consolidation_enabled():
        return 0
    from ..workflow_store import WorkflowStore
    now = now or time.time()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    with store_.transaction() as conn:
        owners = store.owners_due_for_consolidation(conn, since=now - policy.CONSOLIDATION_ACTIVITY_DAYS * 86400, day=day)
        for owner in owners:
            WorkflowStore(store_).enqueue(owner, owner, KIND_CONSOLIDATE, {"day": day}, f"memory_consolidate:{owner}:{day}",
                                         connection=conn, queue="batch", max_attempts=3)
    return len(owners)


def _run(store_, job_id, body, stage):
    from ..execution import LeaseHeartbeat, failure_policy, job_scope
    from ..performance import span
    from ..workflow_store import WorkflowStore
    jobs = WorkflowStore(store_)
    job = jobs.claim(job_id)
    if not job:
        return
    heartbeat = LeaseHeartbeat(store_, job)
    try:
        with job_scope(job):
            with span(stage):
                result = body(job)
            with store_.transaction() as conn:
                jobs.finish(conn, job, result)
    except Exception as exc:
        code, retry = failure_policy(exc)
        log.warning("%s failed (%s)", job["kind"], type(exc).__name__)
        jobs.fail(job, code, retryable=retry)
    finally:
        heartbeat.close()


def run_memory_consolidate(store_, provider, job_id):
    from . import consolidation

    def body(job):
        if not policy.consolidation_enabled():
            return {"status": "skipped", "reason": "disabled"}
        return consolidation.consolidate(store_, job["owner_id"])
    _run(store_, job_id, body, "memory_consolidate_job")


def run_memory_episode(store_, provider, job_id):
    from . import consolidation

    def body(job):
        if not policy.consolidation_enabled():
            return {"status": "skipped", "reason": "disabled"}
        return consolidation.write_episode(store_, job["owner_id"], job["payload"])
    _run(store_, job_id, body, "memory_consolidate_job")
