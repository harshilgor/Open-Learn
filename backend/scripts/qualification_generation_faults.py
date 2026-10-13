"""Exercise real separate-process generation recovery against isolated local PostgreSQL."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url


def wait_until(check, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise TimeoutError('Isolated exercise deadline elapsed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    value = os.getenv(args.database_url_env)
    if not value or args.database_url_env == 'DATABASE_URL': parser.error('Dedicated isolated URL required.')
    url = make_url(value)
    if url.query or url.host not in {'localhost', '127.0.0.1'} or not (url.database or '').startswith('openlearn_qualification_') or url.get_backend_name() != 'postgresql':
        parser.error('Only an isolated localhost PostgreSQL database is accepted.')
    os.environ.update(DATABASE_URL=value, AI_TUTOR_ENV='development', OPENLEARN_PROCESS_ROLE='api',
        OPENLEARN_WORKER_MODE='external', OPENLEARN_MIGRATE_ON_START='true', OPENLEARN_DB_POOL_SIZE='3',
        OPENLEARN_GENERATION_NOTIFY_ENABLED='true', OPENLEARN_USAGE_PAID_ROUTES_ENABLED='false',
        AI_TUTOR_WEB_EVIDENCE='false', AI_TUTOR_EMBEDDING_MODEL='off', OPENLEARN_FIXTURE_CHUNK_DELAY_MS='750')
    for key in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'EXA_API_KEY', 'BROWSERBASE_API_KEY', 'DAYTONA_API_KEY'):
        os.environ[key] = ''
    from backend.app.storage import Store
    from backend.app.identity import Principal, principal_context
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.app.generation_store import StaleGenerationWrite
    from backend.scripts.performance_benchmark import FixtureProvider, seed
    args.out.parent.mkdir(parents=True, exist_ok=True)
    store = Store(value)
    owner = 'qualification-owner-' + uuid4().hex
    token = principal_context.set(Principal(owner, 'local'))
    manager = GenerationManager(store, FixtureProvider())
    results = {}
    worker = api = None
    log = args.out.with_suffix('.worker.log').open('w', encoding='utf-8')
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='generation-faults-', dir=args.out.parent) as directory:
            root = Path(directory)
            os.environ['AI_TUTOR_NOTE_VAULT_DIR'] = str(root / 'vault')
            os.environ['OPENLEARN_OBJECT_BACKEND'] = 'local'
            os.environ['OPENLEARN_OBJECT_DIR'] = str(root / 'objects')
            def start_worker(suffix):
                ready = root / ('ready-' + suffix)
                stop = root / ('stop-' + suffix)
                process = subprocess.Popen([sys.executable, '-m', 'backend.scripts.qualification_generation_worker',
                    '--database-url-env', args.database_url_env, '--ready-file', str(ready), '--stop-file', str(stop)],
                    stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                wait_until(lambda: ready.exists() or process.poll() is not None)
                if process.poll() is not None: raise RuntimeError('Synthetic worker startup failed')
                return process, stop
            worker, worker_stop = start_worker('initial')
            session = 'qualification-session-' + uuid4().hex
            seed(store, session, owner)
            receipt = root / 'api-receipt.json'
            api = subprocess.Popen([sys.executable, '-m', 'backend.scripts.qualification_probe_process',
                '--database-url-env', args.database_url_env, '--owner', owner, '--session', session, '--receipt', str(receipt)],
                stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            wait_until(lambda: receipt.exists() or api.poll() is not None)
            if not receipt.exists(): raise RuntimeError('Synthetic API admission failed')
            identifier = json.loads(receipt.read_text())['generationId']
            wait_until(lambda: manager.records.get(owner, identifier)['status'] == 'streaming')
            api.terminate(); api.wait(timeout=5); api = None
            completed = wait_until(lambda: manager.records.get(owner, identifier) if manager.records.get(owner, identifier)['status'] == 'completed' else None)
            results['apiRestartIndependentCompletion'] = completed['status'] == 'completed'

            # Stop this observer's PG listener: delivery must still replay committed SQL.
            async def replay_without_listener():
                manager.runtime_loop = asyncio.get_running_loop()
                manager.notifications.start(manager.handle_notification)
                manager.notifications.close()
                return [event async for event in manager.events(owner, identifier, 0)]
            events = asyncio.run(replay_without_listener())
            sequences = [event.sequence for event in events if not event.data.get('heartbeat')]
            results['notificationLossReplayOrdered'] = bool(sequences) and sequences == sorted(set(sequences)) and events[-1].type == 'generation.completed'

            def submit():
                sid = 'qualification-session-' + uuid4().hex
                seed(store, sid, owner)
                record = manager.create(owner, sid, GenerationRequest(mode='ask', message='Explain probability briefly.', gear='Quick', expectedRevision=1), uuid4().hex)
                return record['id']
            cancellation = submit()
            wait_until(lambda: any(event.type == 'text.delta' for event in manager.records.events_after(cancellation, 0)))
            manager.cancel(owner, cancellation)
            cancelled = wait_until(lambda: manager.records.get(owner, cancellation) if manager.records.get(owner, cancellation)['status'] == 'cancelled' else None)
            results['crossProcessCancelTerminal'] = cancelled['status'] == 'cancelled'

            crashed = submit()
            wait_until(lambda: any(event.type == 'text.delta' for event in manager.records.events_after(crashed, 0)))
            stale_token = manager.records.get(owner, crashed)['ownerToken']
            worker.kill(); worker.wait(timeout=5); worker = None
            with store.transaction() as connection:
                connection.execute(text('UPDATE generation_records SET lease_expires_at=:expired WHERE id=:id AND owner_id=:owner'),
                    {'expired': time.time()-1, 'id': crashed, 'owner': owner})
            worker, worker_stop = start_worker('recovery')
            interrupted = wait_until(lambda: manager.records.get(owner, crashed) if manager.records.get(owner, crashed)['status'] == 'interrupted' else None)
            results['workerCrashInterruptedWithPartial'] = bool(interrupted.get('partialOutput')) or any(event.type == 'text.delta' for event in manager.records.events_after(crashed, 0))
            try:
                manager.records.append_event(crashed, 'text.delta', {'text': 'stale synthetic write'}, owner_token=stale_token)
                results['staleOwnerWriteRejected'] = False
            except StaleGenerationWrite:
                results['staleOwnerWriteRejected'] = True
            results['noAutomaticProviderRetry'] = manager.records.get(owner, crashed)['status'] == 'interrupted'
            with store.engine.connect() as connection:
                count = connection.execute(text('SELECT active_count FROM generation_capacity WHERE scope_type=\'global\' AND scope_id=\'deployment\'')).scalar_one()
            results['capacityReleasedAfterRecovery'] = count == 0
            worker_stop.touch(); worker.wait(timeout=30); worker = None
    except Exception as cause:
        results['exerciseErrorType'] = type(cause).__name__
    finally:
        for process in (api, worker):
            if process is not None and process.poll() is None:
                process.terminate(); process.wait(timeout=5)
        log.close(); principal_context.reset(token); store.close()
    passed = bool(results) and all(value is True for value in results.values())
    args.out.write_text(json.dumps({'scope': 'isolated PostgreSQL + synthetic independent processes',
        'productionQualification': False, 'passed': passed, 'elapsedSeconds': round(time.monotonic()-started, 3),
        'results': results, 'limitations': ['No real provider charge/usage settlement, HTTP authentication or browser paint is qualified.']}, indent=2), encoding='utf-8')
    print(json.dumps({'passed': passed, 'results': results}))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
