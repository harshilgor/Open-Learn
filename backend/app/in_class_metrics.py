"""Bounded, owner-scoped timing samples for live class processing."""
import hashlib
import json
import math
import time

from sqlalchemy import text

MAX_SAMPLES_PER_CLASS = 2000


def _metric_id(owner, class_id, stage, correlation_id):
    raw = json.dumps([owner, class_id, stage, correlation_id], separators=(",", ":"), ensure_ascii=False)
    return "metric_" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def record(conn, *, owner, class_id, stage, correlation_id, started_at, finished_at, queued_at=None, outcome="completed", counters=None):
    """Persist one idempotent measurement in the transaction for its stage."""
    finished_at = max(float(finished_at), float(started_at))
    started_at = float(started_at)
    queue_wait_ms = max(0.0, (started_at - float(queued_at)) * 1000) if queued_at is not None else 0.0
    duration_ms = max(0.0, (finished_at - started_at) * 1000)
    values = {
        "id": _metric_id(owner, class_id, stage, correlation_id),
        "owner": owner,
        "class": class_id,
        "stage": stage[:60],
        "correlation": hashlib.sha256(str(correlation_id).encode()).hexdigest()[:40],
        "outcome": outcome[:30],
        "queued": queued_at,
        "started": started_at,
        "finished": finished_at,
        "queue_ms": queue_wait_ms,
        "duration_ms": duration_ms,
        "counters": json.dumps(counters or {}, sort_keys=True, separators=(",", ":")),
        "created": time.time(),
    }
    result = conn.execute(text("""INSERT INTO class_processing_metrics
        (id,owner_id,class_id,stage,correlation_id,outcome,queued_at,started_at,finished_at,queue_wait_ms,duration_ms,counters_json,created_at)
        VALUES (:id,:owner,:class,:stage,:correlation,:outcome,:queued,:started,:finished,:queue_ms,:duration_ms,:counters,:created)
        ON CONFLICT(id) DO NOTHING"""), values)
    if result.rowcount:
        count = conn.execute(text("SELECT COUNT(*) FROM class_processing_metrics WHERE owner_id=:owner AND class_id=:class"), {"owner": owner, "class": class_id}).scalar_one()
        if count > MAX_SAMPLES_PER_CLASS:
            # Retain a bounded sample set per class; avoid sorting on the common
            # path until the per-class retention boundary is crossed.
            conn.execute(text("""DELETE FROM class_processing_metrics
                WHERE owner_id=:owner AND class_id=:class AND id NOT IN (
                    SELECT id FROM class_processing_metrics WHERE owner_id=:owner AND class_id=:class
                    ORDER BY finished_at DESC,id DESC LIMIT :limit
                )"""), {"owner": owner, "class": class_id, "limit": MAX_SAMPLES_PER_CLASS})
    return bool(result.rowcount)


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)], 1)


def summarize(conn, owner, class_id):
    rows = conn.execute(text("""SELECT stage,outcome,queued_at,started_at,finished_at,queue_wait_ms,duration_ms,counters_json
        FROM class_processing_metrics WHERE owner_id=:owner AND class_id=:class
        ORDER BY finished_at DESC,id DESC LIMIT :limit"""),
        {"owner": owner, "class": class_id, "limit": MAX_SAMPLES_PER_CLASS}).mappings().all()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["stage"], []).append(row)
    stages = {}
    for stage, samples in grouped.items():
        run_times = [sample["duration_ms"] for sample in samples]
        queue_times = [sample["queue_wait_ms"] for sample in samples]
        end_to_end = [(sample["finished_at"] - sample["queued_at"]) * 1000 for sample in samples if sample["queued_at"] is not None]
        counters = {}
        outcomes = {}
        for sample in samples:
            outcomes[sample["outcome"]] = outcomes.get(sample["outcome"], 0) + 1
            for key, value in json.loads(sample["counters_json"]).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and not (key.startswith("pending") or key == "watermark"):
                    counters[key] = counters.get(key, 0) + value
        stages[stage] = {
            "sampleCount": len(samples),
            "outcomes": outcomes,
            "queueWaitP50Ms": _percentile(queue_times, 0.5),
            "queueWaitP90Ms": _percentile(queue_times, 0.9),
            "runP50Ms": _percentile(run_times, 0.5),
            "runP90Ms": _percentile(run_times, 0.9),
            "endToEndP50Ms": _percentile(end_to_end, 0.5),
            "endToEndP90Ms": _percentile(end_to_end, 0.9),
            "lastFinishedAt": max(sample["finished_at"] for sample in samples),
            "counters": counters,
            "lastCounters": json.loads(samples[0]["counters_json"]),
        }
    return {"classId": class_id, "retainedSampleLimit": MAX_SAMPLES_PER_CLASS, "stages": stages}
