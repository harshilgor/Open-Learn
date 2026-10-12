"""Synthetic API admission process for isolated worker-recovery qualification."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    value = os.getenv(args.database_url_env)
    if not value or args.database_url_env == 'DATABASE_URL':
        parser.error('Require a dedicated isolated database variable.')
    url = make_url(value)
    if url.query or url.host not in {'localhost', '127.0.0.1'} or not (url.database or '').startswith('openlearn_qualification_') or url.get_backend_name() != 'postgresql':
        parser.error('Only an isolated localhost PostgreSQL database is accepted.')
    os.environ.update(DATABASE_URL=value, AI_TUTOR_ENV='development', OPENLEARN_PROCESS_ROLE='api',
        OPENLEARN_WORKER_MODE='external', OPENLEARN_MIGRATE_ON_START='false',
        OPENLEARN_USAGE_PAID_ROUTES_ENABLED='false', AI_TUTOR_WEB_EVIDENCE='false', AI_TUTOR_EMBEDDING_MODEL='off')
    for key in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'EXA_API_KEY', 'BROWSERBASE_API_KEY', 'DAYTONA_API_KEY'):
        os.environ[key] = ''
    from backend.app.storage import Store
    from backend.app.identity import Principal, principal_context
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.scripts.performance_benchmark import FixtureProvider
    store = Store(value)
    token = principal_context.set(Principal(args.owner, 'local'))
    try:
        manager = GenerationManager(store, FixtureProvider())
        receipt = manager.create(args.owner, args.session,
            GenerationRequest(mode='ask', message='Explain probability briefly.', gear='Quick', expectedRevision=1),
            'qualified-api-restart-' + args.session)
        args.receipt.write_text(json.dumps({'generationId': receipt['id']}), encoding='utf-8')
        # The controller ends this API process while the independent worker runs.
        time.sleep(20)
    finally:
        principal_context.reset(token)
        store.close()


if __name__ == '__main__':
    main()
