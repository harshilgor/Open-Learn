"""Read-only release gates and private process diagnostics; no startup migrations."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import threading
import time
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .database import BACKEND_ROOT, approved_schema_heads
from .performance import registry, sample_event_loop_lag

CONTRACT_PATH = BACKEND_ROOT.parent / "deploy" / "release-contract.json"


def release_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def code_schema_heads():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return sorted(ScriptDirectory.from_config(config).get_heads())


def release_status(store):
    contract = release_contract()
    expected = code_schema_heads()
    # Deliberately invoked only by explicit release checks, not on each request.
    with store.engine.connect() as connection:
        actual = sorted(MigrationContext.configure(connection).get_current_heads())
    compatible = set(actual) in approved_schema_heads(set(expected))
    commit = os.getenv("OPENLEARN_RELEASE_SHA") or os.getenv("RENDER_GIT_COMMIT") or "development"
    return {"status": "compatible" if compatible else "incompatible", "commit": commit,
        "protocolVersion": contract["protocolVersion"], "capabilities": contract["requiredCapabilities"],
        "schema": {"expectedHeads": expected, "actualHeads": actual, "compatible": compatible},
        "workerMode": os.getenv("OPENLEARN_WORKER_MODE", "default"),
        "migrationOwner": "single-release-job" if os.getenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL') == 'true' else 'legacy-bootstrap-or-predeploy',
        "generationExecution": "api-process"}


def queue_health(store):
    try:
        now = time.time()
        with store.engine.connect() as connection:
            generation = connection.execute(text("""SELECT COUNT(*) AS total,
                MIN(CASE WHEN status='queued' THEN created_at END) AS oldest,
                SUM(CASE WHEN lease_expires_at<:now AND status<>'queued' THEN 1 ELSE 0 END) AS stale
                FROM generation_records WHERE status IN ('queued','preparing','streaming','finalizing','cancel_requested')"""), {'now': now}).mappings().one()
            jobs = connection.execute(text("""SELECT queue,COUNT(*) AS total,
                MIN(CASE WHEN status IN ('queued','retry_wait') THEN created_at END) AS oldest,
                SUM(CASE WHEN status='running' AND expires<:now THEN 1 ELSE 0 END) AS stale
                FROM learning_jobs WHERE status IN ('queued','retry_wait','running') GROUP BY queue"""), {'now': now}).mappings().all()
            lock_waiters = connection.execute(text("""SELECT COUNT(*) FROM pg_stat_activity
                WHERE datname=current_database() AND wait_event_type='Lock'""")).scalar_one() if connection.dialect.name == 'postgresql' else None
            terminal = connection.execute(text("""SELECT status,COUNT(*) AS total FROM generation_records
                WHERE updated_at>=:cutoff AND status IN ('completed','failed','interrupted','cancelled')
                GROUP BY status"""), {'cutoff': now - 3600}).mappings().all()
        pool = store.engine.pool
        return {'available': True, 'databaseLockWaiters': lock_waiters,
            'terminalGenerationsLastHour': {row['status']: int(row['total']) for row in terminal},
            'pool': {'size': pool.size() if hasattr(pool, 'size') else None, 'checkedOut': pool.checkedout() if hasattr(pool, 'checkedout') else None},
            'generations': {'activeIncludingQueued': int(generation['total']),
            'oldestQueuedSeconds': max(0, now - generation['oldest']) if generation['oldest'] is not None else 0,
            'expiredLeases': int(generation['stale'] or 0)},
            'jobs': [{'queue': row['queue'] if row['queue'] in {'interactive', 'batch'} else 'other',
                'activeIncludingQueued': int(row['total']), 'oldestQueuedSeconds': max(0, now - row['oldest']) if row['oldest'] is not None else 0,
                'expiredLeases': int(row['stale'] or 0)} for row in jobs]}
    except Exception:
        return {'available': False, 'reason': 'dependency_unavailable'}


def build_release_router(store_provider):
    router = APIRouter()
    stop = threading.Event()
    sampler = None

    @router.on_event("startup")
    async def start_sampler():
        nonlocal sampler
        stop.clear()
        sampler = asyncio.create_task(sample_event_loop_lag(stop), name="performance-loop-lag")

    @router.on_event("shutdown")
    async def stop_sampler():
        stop.set()
        if sampler:
            sampler.cancel()
            await asyncio.gather(sampler, return_exceptions=True)

    @router.get("/release")
    def release():
        try:
            report = release_status(store_provider())
            return JSONResponse(report, status_code=200 if report["schema"]["compatible"] else 503,
                headers={"Cache-Control": "no-store"})
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"})

    @router.get("/operations/performance")
    def performance_metrics(token: str | None = Header(default=None, alias="X-OpenLearn-Metrics-Token")):
        expected = os.getenv("LIVE_BRANCHING_METRICS_TOKEN", "")
        if not expected:
            raise HTTPException(404, "Not found")
        if not token or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Unauthorized")
        return JSONResponse({**registry.snapshot(), 'queueHealth': queue_health(store_provider())}, headers={"Cache-Control": "no-store"})
    return router
