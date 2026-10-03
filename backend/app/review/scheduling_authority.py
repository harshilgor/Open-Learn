"""Single scheduling authority for memory next_review_at and review_schedules.due_at."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..models import utc_now
from . import memory as memory_store
from .memory import snapshot_from_memory
from .scheduler import SCHEDULER_VERSION, ScheduleDecision, schedule_after_outcome, schedule_initial

Outcome = Literal["correct", "partial", "incorrect", "skip"]
Confidence = Literal["guessing", "somewhat", "confident", "very"] | None
Condition = Literal["independent", "assisted"]


def decide_timing(
    *,
    outcome: Outcome | str,
    confidence: Confidence = None,
    condition: Condition | str = "independent",
    memory: dict[str, Any] | None,
    now: datetime | None = None,
) -> ScheduleDecision:
    moment = now or utc_now()
    if outcome in {"correct", "partial", "incorrect", "skip"}:
        return schedule_after_outcome(
            outcome=outcome,  # type: ignore[arg-type]
            confidence=confidence,
            condition=condition,  # type: ignore[arg-type]
            memory=snapshot_from_memory(memory),
            now=moment,
        )
    return schedule_initial(now=moment)


def apply_timing(
    connection: Connection,
    *,
    learner_id: str,
    concept_id: str,
    decision: ScheduleDecision,
    outcome: str | None,
    confidence: str | None = None,
    score: float | None = None,
    question_type: str | None = None,
    evidence_id: str | None = None,
    activity_type: str | None = None,
    apply_memory: bool = True,
    mirror_schedule: bool = True,
    schedule_status: str = "scheduled",
    now: datetime | None = None,
    source: Literal["memory", "evidence"] = "memory",
) -> ScheduleDecision:
    """Write memory next_review_at and mirror review_schedules in one authority path."""
    # Once the concept has canonical observations, confidence and same-session
    # retries must not independently extend another scheduler's intervals.
    canonical = connection.execute(text("SELECT 1 FROM capability_projections WHERE owner_id=:owner AND concept_id=:concept"), {"owner": learner_id, "concept": concept_id}).first()
    if canonical:
        return decision
    moment = now or utc_now()
    interval = max(1, int(round(decision.interval_days)))
    if apply_memory and memory_store.get_memory(connection, learner_id, concept_id):
        memory_store.apply_schedule_decision(
            connection,
            learner_id=learner_id,
            concept_id=concept_id,
            decision=decision,
            outcome=outcome,
            confidence=confidence,
            score=score,
            question_type=question_type,
            now=moment,
        )
        connection.execute(text("""
            UPDATE concept_memory_states
            SET provenance_json = json_set(COALESCE(provenance_json, '{}'), '$.lastScheduleSource', :source)
            WHERE learner_id=:learner AND concept_id=:concept
        """), {"source": source, "learner": learner_id, "concept": concept_id})
        # SQLite json_set may be unavailable on older builds; ignore and keep memory write.
        # PostgreSQL uses jsonb operators differently — fall back to Python merge when needed.
        try:
            memory = memory_store.get_memory(connection, learner_id, concept_id)
            if memory is not None:
                provenance = {**(memory.get("provenance") or {}), "lastScheduleSource": source}
                connection.execute(text("""
                    UPDATE concept_memory_states SET provenance_json=:provenance WHERE learner_id=:learner AND concept_id=:concept
                """), {
                    "provenance": __import__("json").dumps(provenance, separators=(",", ":")),
                    "learner": learner_id,
                    "concept": concept_id,
                })
        except Exception:
            pass

    if not mirror_schedule:
        return decision

    activity = activity_type or question_type or "review"
    if evidence_id:
        updated = connection.execute(text("""
            UPDATE review_schedules SET due_at=:due, interval_days=:interval, status=:status,
                due_reason=:reason, activity_type=:activity, confidence_at_schedule=:confidence,
                scheduler_version=:version, updated_at=:now
            WHERE learner_id=:owner AND originating_evidence_id=:evidence
        """), {
            "due": decision.due_at, "interval": interval, "status": schedule_status,
            "reason": decision.due_reason, "activity": activity, "confidence": confidence,
            "version": decision.scheduler_version or SCHEDULER_VERSION, "now": moment,
            "owner": learner_id, "evidence": evidence_id,
        }).rowcount
        if not updated:
            connection.execute(text("""
                INSERT INTO review_schedules(
                    id, learner_id, concept_id, originating_evidence_id, due_at, status, interval_days,
                    created_at, updated_at, due_reason, activity_type, confidence_at_schedule, scheduler_version, priority_score)
                VALUES (:id, :owner, :concept, :evidence, :due, :status, :interval, :now, :now, :reason, :activity, :confidence, :version, NULL)
            """), {
                "id": f"review_{uuid4().hex}", "owner": learner_id, "concept": concept_id,
                "evidence": evidence_id, "due": decision.due_at, "status": schedule_status,
                "interval": interval, "now": moment, "reason": decision.due_reason,
                "activity": activity, "confidence": confidence,
                "version": decision.scheduler_version or SCHEDULER_VERSION,
            })
    else:
        connection.execute(text("""
            UPDATE review_schedules SET status='superseded', updated_at=:now
            WHERE learner_id=:owner AND concept_id=:concept AND status IN ('scheduled','due')
        """), {"now": moment, "owner": learner_id, "concept": concept_id})
        connection.execute(text("""
            INSERT INTO review_schedules(
                id, learner_id, concept_id, originating_evidence_id, due_at, status, interval_days,
                created_at, updated_at, due_reason, activity_type, confidence_at_schedule, scheduler_version, priority_score)
            VALUES (:id, :owner, :concept, NULL, :due, :status, :interval, :now, :now, :reason, :activity, :confidence, :version, NULL)
        """), {
            "id": f"review_{uuid4().hex}", "owner": learner_id, "concept": concept_id,
            "due": decision.due_at, "status": schedule_status, "interval": interval, "now": moment,
            "reason": decision.due_reason, "activity": activity, "confidence": confidence,
            "version": decision.scheduler_version or SCHEDULER_VERSION,
        })
    return decision


def insert_evidence_linked_schedule(
    connection: Connection,
    *,
    learner_id: str,
    concept_id: str,
    evidence_id: str,
    due_at: datetime,
    interval_days: int,
    due_reason: str,
    activity_type: str,
    confidence: str | None,
    scheduler_version: str,
    now: datetime | None = None,
) -> None:
    """Insert a schedule row for evidence admission (memory may already be deferred)."""
    moment = now or utc_now()
    connection.execute(text("""
        INSERT INTO review_schedules
        (id, learner_id, concept_id, originating_evidence_id, due_at, status, interval_days, created_at, updated_at,
         due_reason, activity_type, confidence_at_schedule, scheduler_version, priority_score)
        VALUES (:id, :learner_id, :concept_id, :evidence_id, :due_at, 'scheduled', :interval, :now, :now,
                :reason, :activity, :confidence, :version, NULL)
    """), {
        "id": f"review_{uuid4().hex}", "learner_id": learner_id, "concept_id": concept_id,
        "evidence_id": evidence_id, "due_at": due_at, "interval": interval_days, "now": moment,
        "reason": due_reason, "activity": activity_type, "confidence": confidence, "version": scheduler_version,
    })
