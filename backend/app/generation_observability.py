"""Read-only, aggregate operational metrics for live branching."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict

from sqlalchemy import text

def record_client_outbox_snapshot(store, owner: str, session_id: str, metrics) -> None:
    """Store counts and oldest age only; never accept message bodies or client IDs beyond a tab key."""
    now = time.time()
    values = {
        "owner": owner, "session": session_id, "client": metrics.client_id,
        "queued": metrics.queued_count, "sending": metrics.sending_count,
        "accepted": metrics.accepted_count, "failed": metrics.failed_count,
        "choice": metrics.choice_count, "age": metrics.oldest_pending_age_seconds, "now": now,
    }
    with store.transaction() as connection:
        connection.execute(text("""
            INSERT INTO conversation_outbox_metric_snapshots(
                owner_id,session_id,client_id,queued_count,sending_count,accepted_count,failed_count,
                choice_count,oldest_pending_age_seconds,updated_at)
            VALUES(:owner,:session,:client,:queued,:sending,:accepted,:failed,:choice,:age,:now)
            ON CONFLICT(owner_id,session_id,client_id) DO UPDATE SET
                queued_count=excluded.queued_count,sending_count=excluded.sending_count,
                accepted_count=excluded.accepted_count,failed_count=excluded.failed_count,
                choice_count=excluded.choice_count,oldest_pending_age_seconds=excluded.oldest_pending_age_seconds,
                updated_at=excluded.updated_at
        """), values)


def purge_expired_outbox_snapshots(store, now: float | None = None) -> int:
    current = time.time() if now is None else float(now)
    with store.transaction() as connection:
        result = connection.execute(text("""
            DELETE FROM conversation_outbox_metric_snapshots WHERE updated_at<:cutoff
        """), {"cutoff": current - 86400})
        return int(result.rowcount or 0)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def live_branching_metrics(store, hours: int = 24) -> dict:
    """Return low-cardinality aggregate metrics; never return prompt text or IDs."""
    hours = max(1, min(720, int(hours)))
    now = time.time()
    cutoff = now - hours * 3600
    with store.engine.connect() as connection:
        records = connection.execute(text("""
            SELECT g.id,g.owner_id,g.session_id,g.status,g.provider,g.model,g.error_code,g.created_at,
                   g.payload,COALESCE(e.created_at,g.created_at) AS accepted_at
            FROM generation_records g
            LEFT JOIN conversation_events e ON e.id=g.message_event_id
            WHERE g.created_at>=:cutoff
        """), {"cutoff": cutoff}).mappings().all()
        active_rows = connection.execute(text("""
            SELECT owner_id,session_id,COUNT(*) AS active_count
            FROM generation_records WHERE status IN ('queued','preparing','streaming','finalizing','cancel_requested')
            GROUP BY owner_id,session_id
        """)).mappings().all()
        acceptance = connection.execute(text("""
            SELECT acceptance_latency_ms FROM generation_acceptance_metrics WHERE measured_at>=:cutoff
        """), {"cutoff": cutoff}).scalars().all()
        counters = connection.execute(text("""
            SELECT name,value FROM live_branching_metric_counters
        """)).mappings().all()
        branch_events = connection.execute(text("""
            SELECT owner_id,session_id,payload_json FROM conversation_events
            WHERE event_type='branch.updated' AND created_at>=:cutoff
        """), {"cutoff": cutoff}).mappings().all()
        user_messages = connection.execute(text("""
            SELECT owner_id,session_id,payload_json FROM conversation_events
            WHERE event_type='user_message' AND created_at>=:cutoff
        """), {"cutoff": cutoff}).mappings().all()
        outbox_rows = connection.execute(text("""
            SELECT queued_count,sending_count,accepted_count,failed_count,choice_count,oldest_pending_age_seconds
            FROM conversation_outbox_metric_snapshots WHERE updated_at>=:fresh
        """), {"fresh": now - 90}).mappings().all()

    first_token_seconds: list[float] = []
    tokens_by_conversation: dict[str, int] = defaultdict(int)
    cost_by_conversation: dict[str, float] = defaultdict(float)
    usage_known_by_conversation: Counter[str] = Counter()
    cost_known_by_conversation: Counter[str] = Counter()
    generations_by_conversation: Counter[str] = Counter()
    states_by_provider: dict[str, Counter[str]] = defaultdict(Counter)
    failure_causes: Counter[str] = Counter()
    repeated_prompts: dict[tuple[str, str, str], int] = Counter()
    token_unknown = 0
    cost_unknown = 0
    for row in records:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        metrics = payload.get("metrics") if isinstance(payload, dict) else {}
        metrics = metrics if isinstance(metrics, dict) else {}
        provider = str(row["provider"] or "unknown")
        states_by_provider[provider][row["status"]] += 1
        if row["status"] in {"failed", "interrupted"}:
            failure_causes[f"{provider}:{row['error_code'] or row['status']}"] += 1
        first_delta = metrics.get("firstDeltaAt")
        try:
            elapsed = float(first_delta) - float(row["accepted_at"])
            if first_delta is not None and elapsed >= 0:
                first_token_seconds.append(elapsed)
        except (TypeError, ValueError):
            pass
        session_key = hashlib.sha256(f"{row['owner_id']}:{row['session_id']}".encode()).hexdigest()[:16]
        generations_by_conversation[session_key] += 1
        tokens = metrics.get("totalTokens")
        if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and tokens >= 0:
            tokens_by_conversation[session_key] += int(tokens)
            usage_known_by_conversation[session_key] += 1
        elif row["status"] in {"completed", "cancelled", "failed", "interrupted"}:
            token_unknown += 1
        cost = metrics.get("providerCost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            cost_by_conversation[session_key] += float(cost)
            cost_known_by_conversation[session_key] += 1
        elif row["status"] in {"completed", "cancelled", "failed", "interrupted"}:
            cost_unknown += 1

    for row in user_messages:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        text_value = payload.get("text") if isinstance(payload, dict) else None
        if isinstance(text_value, str) and text_value.strip():
            normalized = " ".join(text_value.casefold().split())
            prompt_hash = hashlib.sha256(normalized.encode()).hexdigest()
            repeated_prompts[(row["owner_id"], row["session_id"], prompt_hash)] += 1

    explicit_switches = 0
    for row in branch_events:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("selectionSource") == "user":
            explicit_switches += 1

    active_counts = [int(row["active_count"]) for row in active_rows]
    known_conversations = set(generations_by_conversation)
    states_summary = {}
    for provider, states in states_by_provider.items():
        total = sum(states.values())
        failed = states.get("failed", 0)
        interrupted = states.get("interrupted", 0)
        states_summary[provider] = {
            "states": dict(states), "total": total,
            "failedRate": round(failed / total, 4) if total else 0,
            "interruptedRate": round(interrupted / total, 4) if total else 0,
            "unsuccessfulRate": round((failed + interrupted) / total, 4) if total else 0,
        }
    conversation_usage = [{
        "conversationKey": key,
        "generationCount": generations_by_conversation[key],
        "tokensIncludingSuperseded": tokens_by_conversation.get(key, 0),
        "providerCostIncludingSuperseded": round(cost_by_conversation.get(key, 0.0), 8),
        "generationsWithKnownTokens": usage_known_by_conversation.get(key, 0),
        "generationsWithKnownCost": cost_known_by_conversation.get(key, 0),
    } for key in sorted(known_conversations,
                        key=lambda item: (tokens_by_conversation.get(item, 0), cost_by_conversation.get(item, 0)),
                        reverse=True)[:100]]
    return {
        "windowHours": hours,
        "generatedAt": now,
        "acceptanceLatencyMs": {
            "count": len(acceptance), "p50": _percentile([float(value) for value in acceptance], 0.5),
            "p95": _percentile([float(value) for value in acceptance], 0.95),
        },
        "followupToFirstTokenSeconds": {
            "count": len(first_token_seconds), "p50": _percentile(first_token_seconds, 0.5),
            "p95": _percentile(first_token_seconds, 0.95),
        },
        "activeGenerations": {
            "deployment": sum(active_counts), "conversations": len(active_counts),
            "maxPerConversation": max(active_counts, default=0),
        },
        "usage": {
            "conversations": len(known_conversations),
            "tokensIncludingSuperseded": sum(tokens_by_conversation.values()),
            "providerCostIncludingSuperseded": round(sum(cost_by_conversation.values()), 8),
            "conversationsWithKnownUsage": sum(1 for count in usage_known_by_conversation.values() if count),
            "terminalGenerationsWithoutKnownTokens": token_unknown,
            "terminalGenerationsWithoutKnownCost": cost_unknown,
            "conversationBreakdown": conversation_usage,
            "breakdownTruncated": len(known_conversations) > len(conversation_usage),
        },
        "staleWriteRejections": sum(int(row["value"]) for row in counters if row["name"] == "stale_write_rejections"),
        "generationStatesByProvider": states_summary,
        "failureCauses": dict(failure_causes),
        "branchSelectionSwitches": explicit_switches,
        "repeatedPromptSubmissions": sum(count - 1 for count in repeated_prompts.values() if count > 1),
        "clientOutbox": {
            "available": True,
            "activeClientSnapshots": len(outbox_rows),
            "queued": sum(int(row["queued_count"]) for row in outbox_rows),
            "sending": sum(int(row["sending_count"]) for row in outbox_rows),
            "accepted": sum(int(row["accepted_count"]) for row in outbox_rows),
            "failed": sum(int(row["failed_count"]) for row in outbox_rows),
            "choice": sum(int(row["choice_count"]) for row in outbox_rows),
            "oldestPendingAgeSeconds": max((float(row["oldest_pending_age_seconds"]) for row in outbox_rows), default=0),
            "collection": "Counts and oldest pending age only; no text or message identifiers are sent. Snapshots expire after 24 hours.",
        },
    }
