"""Offline application-path benchmark with synthetic input and fixture output.

Uses real context assembly, durable generation, replay, and note persistence.
Does not measure provider quality, internet transit, PostgreSQL, or browser paint.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import hashlib
import os
import tempfile
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text

from backend.app.generation_models import GenerationRequest
from backend.app.generation_service import GenerationManager
from backend.app.graph_generator import GraphGenerator
from backend.app.identity import Principal, principal_context
from backend.app.models import TopicScope, utc_now
from backend.app.performance import registry, trace_scope
from backend.app.session_models import LearningSession
from backend.app.storage import Store
from backend.app.workspace_note_models import WorkspaceNoteCreate, WorkspaceNoteUpdate
from backend.app.workspace_note_service import WorkspaceNoteService, WorkspaceNoteError


class FixtureProvider:
    provider_name = 'benchmark-fixture'
    model = 'synthetic-no-network'
    async def stream_text(self, *args, **kwargs):
        for chunk in ('Probability describes how likely an event is. ', 'For a fair coin, each side has probability one half.'):
            delay = max(5, min(2000, int(os.getenv('OPENLEARN_FIXTURE_CHUNK_DELAY_MS', '5'))))
            await asyncio.sleep(delay / 1000)
            yield chunk


def summary(values):
    ordered = sorted(values)
    return {"count": len(values), **{name: round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3) if ordered else None
        for name, fraction in (("p50Ms", .5), ("p95Ms", .95), ("p99Ms", .99))}}


def seed(store, session, owner='local'):
    now = utc_now()
    with store.transaction() as connection:
        connection.execute(text("""INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at)
            VALUES(:owner,:subject,'Synthetic performance owner','active',:now) ON CONFLICT(id) DO NOTHING"""),
            {'owner': owner, 'subject': hashlib.sha256(owner.encode()).hexdigest(), 'now': time.time()})
    scope = TopicScope(id='scope-' + session, topic='probability', resolved_meaning='probability',
        objective='Synthetic performance fixture', depth='introductory', created_at=now)
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    store.save_session(LearningSession(id=session, learner_id=owner, graph_id=graph.id, created_at=now, updated_at=now))


async def benchmark(store, runs, concurrency, checkpoint):
    checkpoint([], phase='running')
    principal_token = principal_context.set(Principal('local', 'local'))
    manager = GenerationManager(store, FixtureProvider())
    manager.runtime_loop = asyncio.get_running_loop()
    manager.notifications.start(manager.handle_notification)
    slots = asyncio.Semaphore(concurrency)
    results = []
    async def one(index):
        async with slots:
            session = 'benchmark-' + uuid4().hex
            owner = 'benchmark-owner-' + uuid4().hex
            sample_principal = principal_context.set(Principal(owner, 'local'))
            scenario = 'greeting' if index % 2 == 0 else 'short-tutoring'
            started = time.perf_counter()
            outcome = {'scenario': scenario, 'status': 'failed', 'firstTextMs': None}
            try:
                await asyncio.to_thread(seed, store, session, owner)
                started = time.perf_counter()
                with trace_scope(resource='chat'):
                    record = await asyncio.to_thread(manager.create, owner, session,
                        GenerationRequest(mode='ask', message='Hi' if scenario == 'greeting' else 'Explain probability briefly.',
                            gear='Quick', expectedRevision=1), uuid4().hex)
                outcome['acceptanceMs'] = (time.perf_counter() - started) * 1000
                async def read():
                    async for event in manager.events(owner, record['id'], 0):
                        if event.type == 'text.delta' and str(event.data.get('text', '')).strip() and outcome['firstTextMs'] is None:
                            outcome['firstTextMs'] = (time.perf_counter() - started) * 1000
                        if event.type in {'generation.completed', 'generation.error', 'generation.cancelled', 'generation.interrupted'}:
                            outcome['status'] = 'completed'
                            if event.type != 'generation.completed':
                                outcome['status'] = event.type.removeprefix('generation.')
                            break
                await asyncio.wait_for(read(), timeout=30)
                final = await asyncio.to_thread(manager.records.get, owner, record['id'])
                outcome['status'] = final['status']
                if final.get('errorCode'):
                    outcome['generationErrorCode'] = final['errorCode']
                # Exercise save while other slots can still be generating.
                service = WorkspaceNoteService(store)
                note = await asyncio.to_thread(service.create, owner, WorkspaceNoteCreate(title='Benchmark note', body='Synthetic original'))
                save_started = time.perf_counter()
                updated = await asyncio.to_thread(service.update, owner, note.id,
                    WorkspaceNoteUpdate(expected_revision=note.revision, body='Synthetic updated'))
                outcome['noteSaveMs'] = (time.perf_counter() - save_started) * 1000
                try:
                    await asyncio.to_thread(service.update, owner, note.id, WorkspaceNoteUpdate(expected_revision=note.revision, body='Stale'))
                    outcome['revisionProtected'] = False
                except WorkspaceNoteError as error:
                    outcome['revisionProtected'] = error.status_code == 409 and updated.revision == note.revision + 1
            except Exception as error:
                outcome['errorType'] = type(error).__name__
                outcome['failurePhase'] = 'seed_or_admission' if 'acceptanceMs' not in outcome else 'generation_or_note'
            outcome['completionMs'] = (time.perf_counter() - started) * 1000
            results.append(outcome)
            if len(results) == 1 or len(results) % 5 == 0 or len(results) == runs:
                checkpoint(results, phase='running')
            principal_context.reset(sample_principal)
    try:
        await asyncio.gather(*(one(index) for index in range(runs)))
    finally:
        pending = list(manager.tasks.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        manager.notifications.close()
        principal_context.reset(principal_token)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--out', required=True)
    parser.add_argument('--temp-dir', type=Path, help='Optional writable parent for the disposable SQLite directory')
    parser.add_argument('--database-url-env', help='Optional isolated local PostgreSQL URL environment variable; never DATABASE_URL')
    parser.add_argument('--external-worker', action='store_true', help='Run a separate synthetic generation process against isolated PostgreSQL')
    args = parser.parse_args()
    if args.external_worker and not args.database_url_env:
        parser.error('--external-worker requires isolated PostgreSQL.')
    isolated_url = None
    if args.database_url_env:
        from sqlalchemy.engine import make_url
        if args.database_url_env == 'DATABASE_URL':
            parser.error('DATABASE_URL cannot be used for qualification.')
        isolated_url = os.getenv(args.database_url_env)
        if not isolated_url:
            parser.error('The isolated PostgreSQL URL variable is missing.')
        parsed = make_url(isolated_url)
        if parsed.query or parsed.get_backend_name() != 'postgresql' or parsed.host not in {'localhost', '127.0.0.1'} or not (parsed.database or '').startswith('openlearn_qualification_'):
            parser.error('Require a local PostgreSQL database named openlearn_qualification_*. Hosted databases are rejected.')
    if not 1 <= args.runs <= 1000 or not 1 <= args.concurrency <= 50:
        parser.error('Runs must be 1–1000; concurrency 1–50')
    temp_parent = args.temp_dir.resolve() if args.temp_dir else None
    if temp_parent is not None and not temp_parent.is_dir():
        parser.error('--temp-dir must be an existing directory')
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    results = []

    def checkpoint(rows, phase):
        report = {"scope": "isolated local PostgreSQL + fixture provider" if isolated_url else "offline SQLite + fixture provider; not production latency or answer quality",
            "executionMode": "separate-generation-process" if args.external_worker else "embedded",
            "productionQualification": False, "phase": phase, "startedAt": started_at,
            "concurrency": args.concurrency, "requestedAttempts": args.runs, "attempts": len(rows),
            "failures": sum(row['status'] != 'completed' or row.get('revisionProtected') is not True for row in rows),
            "timings": {key: summary([row[key] for row in rows if isinstance(row.get(key), (int, float))])
                for key in ('acceptanceMs', 'firstTextMs', 'noteSaveMs', 'completionMs')},
            "results": rows, "processTimings": registry.snapshot()}
        temporary = output.with_suffix(output.suffix + '.tmp')
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        for attempt in range(5):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                # Windows readers may briefly omit FILE_SHARE_DELETE.
                # Reporting must not abort a profile on a transient read lock.
                time.sleep(.025 * (attempt + 1))

    # Create an artifact before Alembic initializes the disposable database so
    # the profile supervisor can distinguish slow schema bootstrap from a hung
    # generation scenario, even if it has to enforce its timeout.
    checkpoint(results, phase='preparing_database')
    # Isolated, disposable fixture environment. Never uses configured DATABASE_URL.
    with tempfile.TemporaryDirectory(prefix='openlearn-benchmark-', dir=temp_parent) as directory:
        os.environ['AI_TUTOR_ENV'] = 'development'
        os.environ['AI_TUTOR_PROVIDER'] = 'deterministic_baseline'
        os.environ['AI_TUTOR_WEB_EVIDENCE'] = 'false'
        os.environ['AI_TUTOR_EMBEDDING_MODEL'] = 'off'
        # Fixture runs must not inherit credentials or invoke paid side routes.
        for credential in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'EXA_API_KEY', 'BROWSERBASE_API_KEY', 'DAYTONA_API_KEY'):
            os.environ[credential] = ''
        os.environ['AI_TUTOR_DEV_IDENTITY'] = 'true'
        os.environ['OPENLEARN_PROCESS_ROLE'] = 'api'
        os.environ['OPENLEARN_WORKER_MODE'] = 'external' if args.external_worker else 'embedded'
        os.environ['OPENLEARN_GENERATION_NOTIFY_ENABLED'] = 'true' if args.external_worker else 'false'
        os.environ['OPENLEARN_MIGRATE_ON_START'] = 'true'
        os.environ['AI_TUTOR_NOTE_VAULT_DIR'] = str(Path(directory) / 'vault')
        os.environ['OPENLEARN_OBJECT_BACKEND'] = 'local'
        os.environ['OPENLEARN_OBJECT_DIR'] = str(Path(directory) / 'objects')
        os.environ['OPENLEARN_USAGE_PAID_ROUTES_ENABLED'] = 'false'
        benchmark_url = isolated_url or f"sqlite+pysqlite:///{(Path(directory) / 'benchmark.db').resolve()}"
        os.environ['DATABASE_URL'] = benchmark_url
        store = Store(benchmark_url)
        worker = None
        worker_log = None
        stop_file = Path(directory) / 'worker-stop'
        try:
            if args.external_worker:
                ready_file = Path(directory) / 'worker-ready.json'
                worker_log = output.with_suffix('.worker.log').open('w', encoding='utf-8')
                worker = subprocess.Popen([sys.executable, '-m', 'backend.scripts.qualification_generation_worker',
                    '--database-url-env', args.database_url_env, '--stop-file', str(stop_file), '--ready-file', str(ready_file)],
                    stdout=worker_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 15
                while not ready_file.exists():
                    if worker.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Isolated generation worker did not become ready; inspect its local log.')
                    time.sleep(.1)
            checkpoint(results, phase='initializing_event_loop')
            results = asyncio.run(benchmark(store, args.runs, args.concurrency, checkpoint))
        finally:
            if worker is not None:
                stop_file.touch()
                try:
                    worker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    worker.terminate()
                    worker.wait(timeout=10)
            if worker_log is not None:
                worker_log.close()
            store.close()
    checkpoint(results, phase='completed' if not any(row['status'] != 'completed' or row.get('revisionProtected') is not True for row in results) else 'failed')
    report = json.loads(output.read_text(encoding='utf-8'))
    print(json.dumps({key: value for key, value in report.items() if key not in {'results', 'processTimings'}}, indent=2))
    raise SystemExit(1 if report['failures'] else 0)


if __name__ == '__main__':
    main()
