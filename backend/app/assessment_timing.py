"""Content-free assessment spans, correlated per execution rather than learner."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import time
from uuid import uuid4

from .performance import logger, configure_performance_logging

_execution = ContextVar("assessment_execution", default=None)
STAGES = frozenset({"author", "independent_check", "solution_agreement", "grading",
    "prepare", "publication", "queue_age", "command"})


def emit(stage, milliseconds, *, status="completed", attempt=None, command=None):
    if stage not in STAGES:
        raise ValueError("Unknown assessment timing stage")
    event = {"event": "assessment_timing", "eventId": uuid4().hex, "executionId": _execution.get(),
        "stage": stage, "durationMs": round(max(0, milliseconds), 3), "status": status}
    if attempt is not None:
        event["attempt"] = attempt
    if command is not None:
        event["command"] = command
    configure_performance_logging()
    logger.info(json.dumps(event, separators=(",", ":")))


@contextmanager
def span(stage, *, attempt=None):
    started, status = time.perf_counter(), "failed"
    try:
        yield
        status = "completed"
    finally:
        emit(stage, (time.perf_counter() - started) * 1000, status=status, attempt=attempt)


def timed(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span(stage):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def execution_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _execution.set(uuid4().hex)
        try:
            return function(*args, **kwargs)
        finally:
            _execution.reset(token)
    return wrapped
