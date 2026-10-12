"""Bounded, content-free timing diagnostics. PostgreSQL remains authoritative.

Snapshots are per process and rolling, not fleet-wide SLO accounting. Export
structured records from stdout for retention/aggregation by the hosting logs.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import hashlib
import math
import os
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.pool import QueuePool

STAGES = frozenset({"api_headers", "api_total", "database_checkout", "database_query",
    "database_hold", "identity", "admission", "generation_queue", "generation_context",
    "provider_first_delta", "generation_first_persisted_text", "generation_total",
    "event_persist", "event_loop_lag", "cache_get", "cache_load"})
logger = logging.getLogger("openlearn.performance")
logger.setLevel(logging.INFO)


def configure_performance_logging():
    """Own a single content-free sink independently of Uvicorn/root settings."""
    logger.disabled = False
    if not any(getattr(handler, 'openlearn_sink', False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.openlearn_sink = True
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    logger.propagate = False


class QueryRegistry:
    """Bounded query-shape aggregates; SQL and bound parameters never leave here."""
    def __init__(self, capacity=128):
        self.capacity = capacity
        self.rows = {}
        self.lock = threading.Lock()

    def observe(self, statement, milliseconds, failed=False):
        # Strip literals even if a caller used literal SQL instead of binds.
        shape = re.sub(r"'(?:''|[^'])*'", '?', statement)
        shape = re.sub(r'\b\d+(?:\.\d+)?\b', '?', shape)
        shape = ' '.join(shape.split())
        fingerprint = hashlib.sha256(shape.encode()).hexdigest()[:16]
        operation = shape.split(' ', 1)[0].upper() if shape else 'OTHER'
        if operation not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE'}:
            operation = 'OTHER'
        with self.lock:
            if fingerprint not in self.rows:
                if len(self.rows) >= self.capacity:
                    fingerprint = 'overflow'
                    operation = 'OTHER'
                self.rows.setdefault(fingerprint, {'fingerprint': fingerprint, 'operation': operation,
                    'count': 0, 'failures': 0, 'totalMs': 0.0, 'maxMs': 0.0})
            row = self.rows[fingerprint]
            row['count'] += 1
            row['failures'] += int(failed)
            row['totalMs'] += milliseconds
            row['maxMs'] = max(row['maxMs'], milliseconds)

    def snapshot(self):
        with self.lock:
            return [dict(row, totalMs=round(row['totalMs'], 3), maxMs=round(row['maxMs'], 3))
                for row in sorted(self.rows.values(), key=lambda row: row['totalMs'], reverse=True)]


queries = QueryRegistry()


class TimingRegistry:
    def __init__(self, capacity=512, max_series=96):
        self.capacity, self.max_series = capacity, max_series
        self.started_at = time.time()
        self._series = {}
        self._lock = threading.Lock()

    def observe(self, stage, milliseconds, *, resource="other", failed=False):
        if stage not in STAGES or resource not in {"chat", "notes", "notes_save", "account", "operations", "health", "other"}:
            return
        if not math.isfinite(milliseconds) or milliseconds < 0:
            return
        key = (stage, resource)
        with self._lock:
            if key not in self._series:
                if len(self._series) >= self.max_series:
                    return
                self._series[key] = {"values": deque(maxlen=self.capacity), "count": 0, "failed": 0}
            row = self._series[key]
            row["values"].append((float(milliseconds), bool(failed)))
            row["count"] += 1
            row["failed"] += int(failed)

    def snapshot(self):
        def percentile(values, fraction):
            if not values:
                return None
            return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)
        with self._lock:
            rows = []
            for (stage, resource), row in sorted(self._series.items()):
                values = sorted(value for value, failed in row["values"])
                rows.append({"stage": stage, "resource": resource, "countSinceStart": row["count"],
                    "failuresSinceStart": row["failed"], "sampleFailures": sum(failed for value, failed in row["values"]), "sampleCount": len(values),
                    "p50Ms": percentile(values, .5), "p95Ms": percentile(values, .95),
                    "p99Ms": percentile(values, .99)})
        from .cache import cache_status, metrics as cache_metrics
        return {"scope": "process", "pid": os.getpid(), "startedAt": self.started_at,
            "retention": "last 512 durations per series; counters since process start",
            "series": rows, "queryShapes": queries.snapshot(),
            "cache": {"status": cache_status(), "namespaces": cache_metrics.snapshot()}}


registry = TimingRegistry()


@dataclass
class Trace:
    trace_id: str
    resource: str
    started_at: float = field(default_factory=time.perf_counter)
    stages: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


current_trace = contextvars.ContextVar("openlearn_performance_trace", default=None)


def trace_id(value=None):
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) else uuid4().hex


def resource_for_path(path, method="GET"):
    # Never retain path parameters, query strings, SQL, or learner content.
    if path.startswith("/v1/learners/") and "/workspace-notes" in path:
        return "notes_save" if method in {"POST", "PATCH", "PUT"} else "notes"
    if path.startswith("/v1/account"):
        return "account"
    if path.startswith(("/v1/generations/", "/v1/sessions/")):
        return "chat"
    if path.startswith(("/v1/operations/", "/operations/", "/release")):
        return "operations"
    if path.startswith(("/health", "/ready")):
        return "health"
    return "other"


def observe(stage, milliseconds, *, failed=False, resource=None):
    try:
        trace = current_trace.get()
        registry.observe(stage, milliseconds, resource=resource or (trace.resource if trace else "other"), failed=failed)
        if trace:
            with trace.lock:
                row = trace.stages.setdefault(stage, {"count": 0, "durationMs": 0.0})
                row["count"] += 1
                row["durationMs"] += milliseconds
    except Exception:
        pass


@contextmanager
def span(stage):
    start = time.perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        observe(stage, (time.perf_counter() - start) * 1000, failed=failed)


@contextmanager
def trace_scope(value=None, resource="other"):
    trace = Trace(trace_id(value), resource)
    token = current_trace.set(trace)
    try:
        yield trace
    finally:
        current_trace.reset(token)


def emit_trace(trace, outcome, *, status=None):
    try:
        # Keep all slow/error/execution traces; sample ordinary successful polls.
        rate = max(0, min(1, float(os.getenv('OPENLEARN_PERFORMANCE_TRACE_LOG_RATE', '0.1'))))
        elapsed = (time.perf_counter() - trace.started_at) * 1000
        if status is not None and status < 400 and elapsed < 750 and int(trace.trace_id[:8], 16) / 0xffffffff >= rate:
            return
        # Alembic's fileConfig disables pre-existing application loggers.
        configure_performance_logging()
        with trace.lock:
            stages = {key: {"count": value["count"], "durationMs": round(value["durationMs"], 3)}
                for key, value in trace.stages.items()}
        logger.info(json.dumps({"event": "openlearn.performance", "traceId": trace.trace_id,
            "resource": trace.resource, "outcome": outcome, "status": status, "stages": stages}, separators=(",", ":")))
    except Exception:
        # A broken metrics sink must not invalidate durable acceptance/saving.
        pass


class PerformanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        incoming = headers.get(b"x-openlearn-trace-id", b"").decode("ascii", errors="ignore")
        with trace_scope(incoming, resource_for_path(scope.get("path", ""), scope.get("method", "GET"))) as trace:
            started = time.perf_counter()
            status = 500
            async def measured_send(message):
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                    elapsed = (time.perf_counter() - started) * 1000
                    observe("api_headers", elapsed, failed=status >= 400)
                    response_headers = list(message.get("headers", []))
                    response_headers.append((b"x-openlearn-trace-id", trace.trace_id.encode()))
                    with trace.lock:
                        timing = ", ".join(f"{name};dur={row['durationMs']:.3f}" for name, row in trace.stages.items())
                    response_headers.append((b"server-timing", timing.encode()))
                    message = {**message, "headers": response_headers}
                await send(message)
            outcome = "completed"
            try:
                await self.app(scope, receive, measured_send)
            except BaseException:
                outcome = "interrupted"
                raise
            finally:
                observe("api_total", (time.perf_counter() - started) * 1000,
                    failed=status >= 400 or outcome != "completed")
                emit_trace(trace, outcome, status=status)


class ObservedQueuePool(QueuePool):
    def _do_get(self):
        # Includes opening a new connection when required, not only queue wait.
        with span("database_checkout"):
            return super()._do_get()


def instrument_engine(engine):
    if getattr(engine, "_openlearn_timing_enabled", False):
        return engine
    engine._openlearn_timing_enabled = True

    @event.listens_for(engine, "before_cursor_execute")
    def before_query(conn, cursor, statement, parameters, context, executemany):
        context._openlearn_query_start = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_query(conn, cursor, statement, parameters, context, executemany):
        start = getattr(context, "_openlearn_query_start", None)
        if start is not None:
            context._openlearn_query_start = None
            observe("database_query", (time.perf_counter() - start) * 1000)
            queries.observe(statement, (time.perf_counter() - start) * 1000)

    @event.listens_for(engine, "handle_error")
    def query_error(context):
        execution = context.execution_context
        start = getattr(execution, "_openlearn_query_start", None)
        if start is not None:
            execution._openlearn_query_start = None
            observe("database_query", (time.perf_counter() - start) * 1000, failed=True)
            queries.observe(context.statement or '', (time.perf_counter() - start) * 1000, failed=True)

    @event.listens_for(engine, "checkout")
    def checkout(connection, record, proxy):
        record.info["openlearn_hold_started"] = time.perf_counter()

    @event.listens_for(engine, "checkin")
    def checkin(connection, record):
        start = record.info.pop("openlearn_hold_started", None)
        if start is not None:
            observe("database_hold", (time.perf_counter() - start) * 1000)
    return engine


async def sample_event_loop_lag(stop, interval=1.0):
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(interval)
        observe("event_loop_lag", max(0, (time.perf_counter() - start - interval) * 1000), resource="operations")
