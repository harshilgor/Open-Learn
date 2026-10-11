import asyncio
import json
import logging
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError

from backend.app import performance


def test_registry_bounds_samples_and_counts_failures_without_dynamic_labels():
    metrics = performance.TimingRegistry(capacity=3, max_series=2)
    for value in range(10):
        metrics.observe('api_headers', value, resource='chat', failed=value == 9)
    metrics.observe('api_headers', 2, resource='learner-secret')
    metrics.observe('SQL containing private text', 2)
    row = metrics.snapshot()['series'][0]
    assert row['countSinceStart'] == 10 and row['failuresSinceStart'] == 1
    assert row['sampleCount'] == 3 and row['p95Ms'] == 9
    assert len(metrics.snapshot()['series']) == 1


def test_sql_timing_retains_no_statement_parameters_or_identity(caplog, monkeypatch):
    metrics = performance.TimingRegistry()
    monkeypatch.setattr(performance, 'registry', metrics)
    engine = performance.instrument_engine(create_engine('sqlite://'))
    with performance.trace_scope('a' * 32, 'notes_save') as trace:
        with engine.connect() as connection:
            connection.execute(text('SELECT :private'), {'private': 'sensitive-note'})
            with pytest.raises(Exception):
                connection.execute(text('SELECT * FROM missing_private_table'))
        with caplog.at_level(logging.INFO, logger='openlearn.performance'):
            performance.emit_trace(trace, 'completed')
    output = caplog.text + json.dumps(metrics.snapshot())
    assert 'sensitive-note' not in output and 'missing_private_table' not in output
    query = next(row for row in metrics.snapshot()['series'] if row['stage'] == 'database_query')
    assert query['countSinceStart'] == 2 and query['failuresSinceStart'] == 1
    engine.dispose()


def test_checkout_timeout_is_measured_and_not_swallowed(monkeypatch):
    metrics = performance.TimingRegistry()
    monkeypatch.setattr(performance, 'registry', metrics)
    engine = create_engine('sqlite://', poolclass=performance.ObservedQueuePool,
        pool_size=1, max_overflow=0, pool_timeout=.01)
    with engine.connect(), performance.trace_scope(resource='chat'):
        with pytest.raises(TimeoutError):
            engine.connect()
    assert any(row['stage'] == 'database_checkout' and row['failuresSinceStart'] == 1 for row in metrics.snapshot()['series'])
    engine.dispose()


def test_trace_context_propagates_to_thread_and_isolates_concurrent_requests():
    async def work(value):
        with performance.trace_scope(value, 'chat'):
            return await asyncio.to_thread(lambda: performance.current_trace.get().trace_id)
    async def run():
        return await asyncio.gather(work('a' * 32), work('b' * 32))
    assert asyncio.run(run()) == ['a' * 32, 'b' * 32]
    assert performance.current_trace.get() is None


def test_middleware_streams_without_buffering_and_measures_failures(monkeypatch):
    metrics = performance.TimingRegistry()
    monkeypatch.setattr(performance, 'registry', metrics)
    app = FastAPI()
    app.add_middleware(performance.PerformanceMiddleware)
    @app.get('/v1/sessions/private/events')
    def streaming():
        async def chunks():
            yield 'data: first\n\n'
            yield 'data: second\n\n'
        return StreamingResponse(chunks(), media_type='text/event-stream')
    with TestClient(app) as client:
        response = client.get('/v1/sessions/private/events?secret=value', headers={'X-OpenLearn-Trace-Id': 'c' * 32})
        assert response.headers['x-openlearn-trace-id'] == 'c' * 32
        assert 'api_headers;dur=' in response.headers['server-timing']
        assert response.text == 'data: first\n\ndata: second\n\n'
        rejected = client.get('/v1/sessions/private/missing', headers={'X-OpenLearn-Trace-Id': 'learner@example.com'})
        assert rejected.status_code == 404
        assert len(rejected.headers['x-openlearn-trace-id']) == 32
    output = json.dumps(metrics.snapshot())
    assert 'secret' not in output and 'private' not in output
    assert any(row['failuresSinceStart'] for row in metrics.snapshot()['series'])


def test_metrics_sink_failure_does_not_fail_the_response(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('metrics sink unavailable')
    monkeypatch.setattr(performance.registry, 'observe', broken)
    app = FastAPI()
    app.add_middleware(performance.PerformanceMiddleware)
    @app.get('/v1/account')
    def account():
        return {'available': True}
    with TestClient(app) as client:
        response = client.get('/v1/account')
    assert response.status_code == 200 and response.json() == {'available': True}
