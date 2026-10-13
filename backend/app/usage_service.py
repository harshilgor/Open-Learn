"""Local-first usage aggregation over durable generation records.

Only completed generations contribute usage. Records with exact
provider-reported metrics are used as-is; legacy records without them fall
back to the pre-existing character-based estimate and are flagged
``usageSource: estimated`` so the UI never presents estimates as exact.
Provider cost is summed only when the provider reported it.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone

RANGE_SECONDS = {"7d": 7 * 86400, "30d": 30 * 86400, "all": None}


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return 0


def _day_key(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def _record_usage(row: dict) -> dict | None:
    """Normalize one generation_records row. Returns None when not countable."""
    if row.get("status") != "completed":
        return None
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    usage_source = metrics.get("usageSource")
    total = _safe_int(metrics.get("totalTokens"))
    prompt = _safe_int(metrics.get("promptTokens"))
    completion = _safe_int(metrics.get("completionTokens"))
    cost_raw = metrics.get("providerCost")
    cost = float(cost_raw) if isinstance(cost_raw, (int, float)) and not isinstance(cost_raw, bool) and cost_raw >= 0 else 0.0
    has_cost = isinstance(cost_raw, (int, float)) and not isinstance(cost_raw, bool) and cost_raw >= 0
    exact = usage_source == "exact" and total > 0
    if metrics.get("modelInvoked") is False:
        total = prompt = completion = 0
        usage_source = "estimated"
        cost = 0.0
        has_cost = False
    elif not exact:
        estimated = _safe_int(metrics.get("estimatedOutputTokens"))
        if estimated <= 0:
            estimated = _safe_int(metrics.get("outputCharacters")) // 4
        total = estimated
        prompt = 0
        completion = estimated
        usage_source = "estimated"
        cost = 0.0
        has_cost = False
    else:
        usage_source = "exact"
    created_at = row.get("created_at")
    try:
        created_at = float(created_at)
    except (TypeError, ValueError):
        created_at = time.time()
    provider_label = str(metrics.get("usageProvider") or "").lower()
    if provider_label not in {"openrouter", "openai"}:
        raw_provider = str(row.get("provider") or "")
        provider_label = raw_provider.split("/")[0].lower() if "/" in raw_provider else raw_provider.lower()
        if provider_label not in {"openrouter", "openai"}:
            provider_label = provider_label or "unknown"
    model = str(row.get("model") or metrics.get("model") or "unknown")
    mode = str(row.get("mode") or "").lower()
    course = str(row.get("course_name") or "Unassigned")
    return {
        "total": total,
        "prompt": prompt,
        "completion": completion,
        "cost": cost,
        "has_cost": has_cost,
        "exact": exact,
        "created_at": created_at,
        "day": _day_key(created_at),
        "provider": provider_label,
        "model": model,
        "mode": mode,
        "course": course,
        "session_id": str(row.get("session_id") or "unknown"),
    }


def summarize(rows: list[dict], *, range_key: str = "all") -> dict:
    """Aggregate normalized rows. Pure function for easy testing."""
    if range_key not in RANGE_SECONDS:
        range_key = "all"
    now = time.time()
    cutoff = now - RANGE_SECONDS[range_key] if RANGE_SECONDS[range_key] is not None else None
    usages = []
    for row in rows:
        parsed = _record_usage(row)
        if parsed is None:
            continue
        if cutoff is not None and parsed["created_at"] < cutoff:
            continue
        usages.append(parsed)
    total_tokens = sum(item["total"] for item in usages)
    prompt_tokens = sum(item["prompt"] for item in usages)
    completion_tokens = sum(item["completion"] for item in usages)
    total_cost = round(sum(item["cost"] for item in usages), 6)
    exact_count = sum(1 for item in usages if item["exact"])
    estimated_count = len(usages) - exact_count
    by_day_map: dict[str, dict] = defaultdict(lambda: {"date": "", "totalTokens": 0, "generations": 0})
    by_model_map: dict[str, dict] = defaultdict(lambda: {"model": "", "totalTokens": 0, "generations": 0})
    by_provider_map: dict[str, dict] = defaultdict(lambda: {"provider": "", "totalTokens": 0, "generations": 0})
    for item in usages:
        day = by_day_map[item["day"]]
        day["date"] = item["day"]
        day["totalTokens"] += item["total"]
        day["generations"] += 1
        model_entry = by_model_map[item["model"]]
        model_entry["model"] = item["model"]
        model_entry["totalTokens"] += item["total"]
        model_entry["generations"] += 1
        provider_entry = by_provider_map[item["provider"]]
        provider_entry["provider"] = item["provider"]
        provider_entry["totalTokens"] += item["total"]
        provider_entry["generations"] += 1
    by_day = sorted(by_day_map.values(), key=lambda entry: entry["date"])
    if cutoff is not None:
        # Fill empty days so the time series renders continuously.
        span_days = 7 if range_key == "7d" else 30
        existing = {entry["date"]: entry for entry in by_day}
        filled = []
        for offset in range(span_days - 1, -1, -1):
            key = _day_key(now - offset * 86400)
            filled.append(existing.get(key, {"date": key, "totalTokens": 0, "generations": 0}))
        by_day = filled
    by_model = sorted(by_model_map.values(), key=lambda entry: entry["totalTokens"], reverse=True)
    by_provider = sorted(by_provider_map.values(), key=lambda entry: entry["totalTokens"], reverse=True)
    return {
        "range": range_key,
        "totals": {
            "totalTokens": total_tokens,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "generations": len(usages),
            "exactGenerations": exact_count,
            "estimatedGenerations": estimated_count,
            "providerCost": total_cost,
            "costIsExact": total_cost > 0,
        },
        "byDay": by_day,
        "byModel": by_model,
        "byProvider": by_provider,
    }


def fetch_completed_rows(store, owner: str, session_id: str | None = None) -> list[dict]:
    """Load completed generation rows for one owner. Ownership enforced here."""
    from sqlalchemy import text

    query = """SELECT g.id, g.owner_id, g.session_id, g.status, g.mode, g.provider, g.model, g.payload, g.created_at,
                      c.name AS course_name
               FROM generation_records g
               LEFT JOIN learning_sessions s ON s.id=g.session_id AND s.learner_id=g.owner_id
               LEFT JOIN courses c ON c.id=s.course_id AND c.owner_id=g.owner_id
               WHERE g.owner_id=:owner AND g.status='completed'"""
    params: dict[str, object] = {"owner": owner}
    if session_id:
        query += " AND g.session_id=:session"
        params["session"] = session_id
    with store.engine.connect() as connection:
        result = connection.execute(text(query), params).mappings().all()
    return [dict(row) for row in result]


def fetch_session_titles(store, owner: str) -> dict[str, str]:
    """Map session_id -> display title for one owner. Never raises."""
    from sqlalchemy import text

    try:
        with store.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, payload FROM learning_sessions WHERE learner_id=:owner"),
                {"owner": owner},
            ).mappings().all()
    except Exception:
        return {}
    titles: dict[str, str] = {}
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            title = payload.get("title") or payload.get("goal")
            if title:
                titles[str(row["id"])] = str(title)
    return titles


DIMENSIONS = ("mode", "model", "provider", "course")
MODE_LABELS = {"ask": "Ask", "learn": "Learn"}
SERIES_LIMIT = 5


def _dimension_key(item: dict, dimension: str) -> str:
    if dimension == "model":
        return item["model"]
    if dimension == "provider":
        return item["provider"]
    if dimension == "course":
        return item["course"]
    return MODE_LABELS.get(item["mode"], "Other")


def analytics(
    rows: list[dict],
    *,
    range_key: str = "7d",
    dimension: str = "mode",
    session_titles: dict[str, str] | None = None,
    session_limit: int = 5,
) -> dict:
    """Deep-insights aggregation. Pure function for easy testing."""
    if range_key not in ("7d", "30d"):
        range_key = "7d"
    if dimension not in DIMENSIONS:
        dimension = "mode"
    session_limit = max(1, min(int(session_limit or 5), 20))
    now = time.time()
    span_days = 7 if range_key == "7d" else 30
    cutoff = now - span_days * 86400
    usages = []
    for row in rows:
        parsed = _record_usage(row)
        if parsed is None or parsed["created_at"] < cutoff:
            continue
        usages.append(parsed)
    days = [_day_key(now - offset * 86400) for offset in range(span_days - 1, -1, -1)]
    day_index = {date: position for position, date in enumerate(days)}
    # Per-day totals (powers bars and trend lines).
    daily = [{"date": date, "totalTokens": 0, "generations": 0, "promptTokens": 0,
              "completionTokens": 0, "cost": 0.0} for date in days]
    totals = {"totalTokens": 0, "promptTokens": 0, "completionTokens": 0, "generations": 0,
              "exactGenerations": 0, "estimatedGenerations": 0, "providerCost": 0.0, "costIsExact": False}
    bucket_tokens: dict[str, int] = defaultdict(int)
    bucket_generations: dict[str, int] = defaultdict(int)
    bucket_points: dict[str, list[int]] = defaultdict(lambda: [0] * span_days)
    bucket_gen_points: dict[str, list[int]] = defaultdict(lambda: [0] * span_days)
    sessions: dict[str, dict] = {}
    for item in usages:
        position = day_index[item["day"]]
        entry = daily[position]
        entry["totalTokens"] += item["total"]
        entry["generations"] += 1
        entry["promptTokens"] += item["prompt"]
        entry["completionTokens"] += item["completion"]
        entry["cost"] = round(entry["cost"] + item["cost"], 6)
        totals["totalTokens"] += item["total"]
        totals["promptTokens"] += item["prompt"]
        totals["completionTokens"] += item["completion"]
        totals["generations"] += 1
        totals["exactGenerations"] += 1 if item["exact"] else 0
        totals["providerCost"] = round(totals["providerCost"] + item["cost"], 6)
        key = _dimension_key(item, dimension)
        bucket_tokens[key] += item["total"]
        bucket_generations[key] += 1
        bucket_points[key][position] += item["total"]
        bucket_gen_points[key][position] += 1
        session = sessions.setdefault(item["session_id"], {
            "sessionId": item["session_id"], "totalTokens": 0, "generations": 0,
            "providerCost": 0.0, "lastActive": 0.0, "byModel": defaultdict(lambda: {"model": "", "totalTokens": 0, "generations": 0}),
        })
        session["totalTokens"] += item["total"]
        session["generations"] += 1
        session["providerCost"] = round(session["providerCost"] + item["cost"], 6)
        session["lastActive"] = max(session["lastActive"], item["created_at"])
        model_entry = session["byModel"][item["model"]]
        model_entry["model"] = item["model"]
        model_entry["totalTokens"] += item["total"]
        model_entry["generations"] += 1
    totals["estimatedGenerations"] = totals["generations"] - totals["exactGenerations"]
    totals["costIsExact"] = totals["providerCost"] > 0
    grand = totals["totalTokens"] or 1
    ranked = sorted(bucket_tokens, key=lambda key: bucket_tokens[key], reverse=True)
    series = []
    for key in ranked[:SERIES_LIMIT]:
        series.append({"key": key, "totalTokens": bucket_tokens[key], "generations": bucket_generations[key],
                       "sharePct": round(bucket_tokens[key] / grand * 100, 2), "points": bucket_points[key],
                       "genPoints": bucket_gen_points[key]})
    if len(ranked) > SERIES_LIMIT:
        rest = ranked[SERIES_LIMIT:]
        combined = [0] * span_days
        combined_gens = [0] * span_days
        for key in rest:
            for position, value in enumerate(bucket_points[key]):
                combined[position] += value
            for position, value in enumerate(bucket_gen_points[key]):
                combined_gens[position] += value
        other_total = sum(bucket_tokens[key] for key in rest)
        series.append({"key": "Other", "totalTokens": other_total,
                       "generations": sum(bucket_generations[key] for key in rest),
                       "sharePct": round(other_total / grand * 100, 2), "points": combined,
                       "genPoints": combined_gens})
    titles = session_titles or {}
    top_sessions = []
    for session in sorted(sessions.values(), key=lambda item: item["totalTokens"], reverse=True)[:session_limit]:
        by_model = sorted(session["byModel"].values(), key=lambda item: item["totalTokens"], reverse=True)[:4]
        top_sessions.append({
            "sessionId": session["sessionId"],
            "title": titles.get(session["sessionId"], session["sessionId"]),
            "totalTokens": session["totalTokens"],
            "generations": session["generations"],
            "providerCost": session["providerCost"],
            "costIsExact": session["providerCost"] > 0,
            "lastActive": datetime.fromtimestamp(session["lastActive"], tz=timezone.utc).isoformat() if session["lastActive"] else None,
            "byModel": by_model,
        })
    return {"range": range_key, "dimension": dimension, "totals": totals,
            "days": daily, "series": series, "topSessions": top_sessions}
