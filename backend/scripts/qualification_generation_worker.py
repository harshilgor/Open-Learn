"""Isolated localhost generation worker with synthetic output and no provider credentials."""
from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path

from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', required=True)
    parser.add_argument('--stop-file', required=True, type=Path)
    parser.add_argument('--ready-file', required=True, type=Path)
    args = parser.parse_args()
    if args.database_url_env == 'DATABASE_URL' or not os.getenv(args.database_url_env):
        parser.error('A dedicated isolated database variable is required.')
    database = os.environ[args.database_url_env]
    url = make_url(database)
    if url.query or url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1'} or not (url.database or '').startswith('openlearn_qualification_'):
        parser.error('Only isolated localhost qualification databases are accepted.')
    os.environ.update(AI_TUTOR_ENV='development', OPENLEARN_PROCESS_ROLE='generation',
        OPENLEARN_WORKER_MODE='external', OPENLEARN_MIGRATE_ON_START='false',
        OPENLEARN_GENERATION_NOTIFY_ENABLED='true', OPENLEARN_USAGE_PAID_ROUTES_ENABLED='false',
        AI_TUTOR_WEB_EVIDENCE='false', AI_TUTOR_EMBEDDING_MODEL='off')
    for key in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'EXA_API_KEY', 'BROWSERBASE_API_KEY', 'DAYTONA_API_KEY'):
        os.environ[key] = ''
    from backend.app.storage import Store
    from backend.app.generation_worker import GenerationWorker
    from backend.scripts.performance_benchmark import FixtureProvider
    store = Store(database)
    stop = threading.Event()
    def watch():
        while not stop.wait(.1):
            if args.stop_file.exists():
                stop.set()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        worker = GenerationWorker(store, FixtureProvider)
        args.ready_file.write_text(json.dumps({'role': 'generation', 'provider': 'synthetic', 'pid': os.getpid()}), encoding='utf-8')
        worker.run(stop)
    finally:
        stop.set()
        watcher.join(timeout=1)
        store.close()


if __name__ == '__main__':
    main()
