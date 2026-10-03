"""One explainable capability reducer for every workflow.

Policies are operational rules, not calibrated probabilities. Original events
are immutable; a projection and its retention schedule are rebuilt together.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .execution import ProjectionWatermarks
from .identity import assert_owner_active


@dataclass(frozen=True)
class ProjectionPolicy:
    revision: str = "capability-v1-shadow"
    required_families: int = 2
    required_sessions: int = 2
    delayed_hours: int = 24
    contradiction_days: int = 30
    maximum_interval_days: int = 60
    initial_interval_days: int = 1
    stale_multiplier: int = 3
    # Enable only through an explicit versioned policy change following labeled
    # history comparison. A code default must not mass-promote legacy learners.
    demonstrated_enabled: bool = False


POLICY = ProjectionPolicy()


def _moment(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def reduce_capability(entries, policy=POLICY):
    """Pure reduction; derived dates use occurrence time, never wall time."""
    ordered = sorted(entries, key=lambda e: (_moment(e["occurredAt"]), e["id"]))
    successes, failures, assisted, uncertain = [], [], [], []
    families, sessions, retrieval_groups = set(), set(), set()
    last_retrieval = None
    interval = policy.initial_interval_days
    due = None
    delayed = 0
    has_exposure = False
    for entry in ordered:
        category = entry["category"]
        when = _moment(entry["occurredAt"])
        if category in {"exposure", "coverage"}:
            has_exposure = True
            continue
        if category in {"skip", "self_report", "assistance", "excluded"}:
            if category == "excluded":
                uncertain.append(entry["id"])
            continue
        measurable = entry.get("attributionResolved", False)
        independent = entry.get("assistance") == "independent" and measurable and bool(entry.get("familyId"))
        family = entry.get("familyId")
        session = entry.get("sessionId") or entry.get("activityId")
        if not independent:
            (assisted if entry.get("assistance") == "assisted" else uncertain).append(entry["id"])
            if entry.get("assistance") == "assisted" and measurable:
                interval = policy.initial_interval_days
                due = when + timedelta(days=interval)
            continue
        group = (family, session)
        outcome = entry.get("outcome")
        if outcome == "correct":
            successes.append(entry["id"])
            families.add(family)
            sessions.add(session)
            if group not in retrieval_groups:
                if last_retrieval is not None and (when - last_retrieval).total_seconds() >= policy.delayed_hours * 3600:
                    delayed += 1
                    interval = min(policy.maximum_interval_days, max(3, interval * 2))
                last_retrieval = when
                due = when + timedelta(days=interval)
                retrieval_groups.add(group)
        elif outcome in {"incorrect", "partial"}:
            failures.append((entry["id"], when))
            interval = policy.initial_interval_days
            due = when + timedelta(days=interval)
    latest = _moment(ordered[-1]["occurredAt"]) if ordered else None
    recent_failures = [identifier for identifier, when in failures if latest and latest - when <= timedelta(days=policy.contradiction_days)]
    conflicting = bool(successes and recent_failures)
    candidate = len(families) >= policy.required_families and len(sessions) >= policy.required_sessions and delayed > 0 and not conflicting
    state = "demonstrated" if candidate and policy.demonstrated_enabled else "developing" if successes or failures or assisted else "exposed" if has_exposure else "unobserved"
    strength = "conflicting" if conflicting else "supported" if candidate else "tentative" if successes or failures or assisted else "insufficient_evidence"
    reasons = []
    if not successes: reasons.append("independent_check_needed")
    if len(families) < policy.required_families: reasons.append("distinct_families_needed")
    if not delayed: reasons.append("delayed_confirmation_needed")
    if conflicting: reasons.append("diagnosis_needed")
    if uncertain: reasons.append("uncertain_or_legacy_evidence")
    if candidate and not policy.demonstrated_enabled: reasons.append("demonstration_policy_pending_validation")
    return {"state": state, "evidenceStrength": strength, "demonstrationCandidate": candidate,
        "independentSuccessIds": successes, "independentFailureIds": [identifier for identifier, _ in failures],
        "assistedEventIds": assisted, "uncertainEventIds": uncertain, "distinctFamilies": len(families),
        "distinctSessions": len(sessions), "delayedRetrievalCount": delayed,
        "lastIndependentRetrieval": last_retrieval.isoformat() if last_retrieval else None,
        "intervalDays": interval, "dueAt": due.isoformat() if due else None,
        "effectiveEventIds": [entry["id"] for entry in ordered], "reasonCodes": reasons,
        "policyRevision": policy.revision}


def retention_at(projection, as_of):
    result = dict(projection)
    due = _moment(result["dueAt"]) if result.get("dueAt") else None
    last = result.get("lastIndependentRetrieval")
    result["retention"] = "unmeasured" if not last else "stale" if due and as_of > due + timedelta(days=result["intervalDays"] * POLICY.stale_multiplier) else "review_due" if due and as_of >= due else "recently_recalled"
    result["asOf"] = as_of.isoformat()
    return result


class UnifiedLearnerState:
    def __init__(self, store):
        self.store = store

    def rebuild(self, conn, owner):
        assert_owner_active(conn, owner)
        conn.execute(text("INSERT INTO learning_event_sequences(owner_id,sequence) VALUES(:owner,0) ON CONFLICT(owner_id) DO NOTHING"), {"owner": owner})
        conn.execute(text("UPDATE learning_event_sequences SET sequence=sequence WHERE owner_id=:owner"), {"owner": owner})
        from .evidence_ledger import EvidenceLedger
        from .stable_concept_service import StableConceptService
        history = EvidenceLedger(self.store).history(conn, owner)
        grouped = defaultdict(list)
        concepts = StableConceptService(self.store)
        for entry in history["entries"]:
            for link in entry["concepts"]:
                original = link["concept_id"]
                exists = conn.execute(text("SELECT 1 FROM stable_concepts WHERE owner_id=:owner AND id=:id"), {"owner": owner, "id": original}).first()
                graph = entry.get("graph")
                canonical = concepts.canonical(owner, original, connection=conn) if exists else concepts.resolve_legacy(owner, graph["id"], graph["revision"], original, connection=conn) if graph else {"status": "unmapped"}
                target = canonical.get("concept_id") or original
                copy = {**entry, "originalConceptId": original,
                    "attributionResolved": link["uncertainty"] == "resolved" and link["attribution_basis"] in {"rubric", "reviewed_mapping"} and link["role"] == "target" and canonical.get("status") == "resolved"}
                grouped[(target, link["capability"])].append(copy)
        # Replacement rather than incremental reduction makes late events and
        # revoked mappings remove stale rows, including old merge destinations.
        conn.execute(text("DELETE FROM capability_projections WHERE owner_id=:owner"), {"owner": owner})
        for (concept, capability), entries in grouped.items():
            value = {**reduce_capability(entries), "conceptId": concept, "capability": capability,
                "eventWatermark": history["watermark"]}
            conn.execute(text("INSERT INTO capability_projections(owner_id,concept_id,capability,event_watermark,policy_revision,payload) VALUES(:owner,:concept,:capability,:watermark,:policy,:payload)"), {
                "owner": owner, "concept": concept, "capability": capability,
                "watermark": history["watermark"], "policy": POLICY.revision, "payload": json.dumps(value, sort_keys=True)})
        from .state_service import LearnerStateService
        LearnerStateService(self.store).mirror_capability_projections(conn, owner)
        ProjectionWatermarks.advance(conn, owner, "learner_projection", "all", history["watermark"])
        return self.read(conn, owner)

    def read(self, conn, owner, concept_id=None, as_of=None):
        assert_owner_active(conn, owner)
        rows = conn.execute(text("SELECT payload FROM capability_projections WHERE owner_id=:owner ORDER BY concept_id,capability"), {"owner": owner}).scalars().all()
        moment = as_of or datetime.now(timezone.utc)
        result = [retention_at(json.loads(row), moment) for row in rows]
        if concept_id:
            result = [row for row in result if row["conceptId"] == concept_id]
        return {"policyRevision": POLICY.revision, "states": result,
            "eventWatermark": max((row["eventWatermark"] for row in result), default=0)}
