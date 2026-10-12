"""Three bounded synthetic prompts through the tutor, durable replay and usage ledger.

Requires a localhost qualification database and a provider-limited test key.
Does not qualify hosted authentication, browser paint, availability or load.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url


async def run_probe(store, provider, output):
    from backend.app.identity import Principal, principal_context
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.app.model_provider import close_provider_http_clients
    from backend.scripts.performance_benchmark import seed
    owner, session = 'qualification-owner-' + uuid4().hex, 'qualification-session-' + uuid4().hex
    token = principal_context.set(Principal(owner, 'local'))
    manager = GenerationManager(store, provider)
    manager.runtime_loop = asyncio.get_running_loop()
    rows = []
    try:
        await asyncio.to_thread(seed, store, session, owner)
        for index, prompt in enumerate(('Explain inertia in two sentences.', 'Give a bus example of that idea in two sentences.',
                                        'New topic: explain a linear equation in two sentences.')):
            started = time.perf_counter()
            row = {'scenario': ('short-tutoring', 'contextual-followup', 'context-switch')[index],
                'status': 'failed', 'firstTextMs': None, 'answer': ''}
            identifier = None
            try:
                receipt = await asyncio.to_thread(manager.create, owner, session,
                    GenerationRequest(mode='ask', presentation='conversation', message=prompt, gear='Quick', expectedRevision=1), uuid4().hex)
                identifier = receipt['id']
                row['acceptanceMs'] = (time.perf_counter() - started) * 1000
                async def observe():
                    async for event in manager.events(owner, identifier, 0):
                        if event.type == 'text.delta':
                            delta = event.data.get('text', '')
                            if delta.strip() and row['firstTextMs'] is None:
                                row['firstTextMs'] = (time.perf_counter() - started) * 1000
                            row['answer'] += delta
                        if event.type in {'generation.completed', 'generation.cancelled', 'generation.error', 'generation.interrupted'}:
                            break
                await asyncio.wait_for(observe(), timeout=45)
                record = await asyncio.to_thread(manager.records.get, owner, identifier)
                row['status'] = record['status']
                row['metrics'] = {key: value for key, value in record.get('metrics', {}).items()
                    if key in {'providerTtftSeconds','contextBuildSeconds','providerCost','promptTokens','completionTokens',
                               'cachedPromptTokens','cacheWriteTokens','responseRoute','modelInvoked'}}
                if record.get('errorCode'): row['errorCode'] = record['errorCode']
            except Exception as cause:
                row['errorType'] = type(cause).__name__
                if identifier: await asyncio.to_thread(manager.cancel, owner, identifier)
            row['completionMs'] = (time.perf_counter() - started) * 1000
            rows.append(row)
            output.write_text(json.dumps({'scope': 'local PostgreSQL tutor path + real provider + enforced usage',
                'productionQualification': False, 'browserDeliveryMeasured': False, 'qualityQualified': False,
                'model': provider.model, 'results': rows}, indent=2), encoding='utf-8')
            if row['status'] != 'completed': break
    finally:
        for task in list(manager.tasks.values()): task.cancel()
        await asyncio.gather(*list(manager.tasks.values()), return_exceptions=True)
        manager.notifications.close()
        await close_provider_http_clients()
        principal_context.reset(token)
    return len(rows) == 3 and all(row['status'] == 'completed' for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', required=True)
    parser.add_argument('--key-env-file', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    value = os.getenv(args.database_url_env)
    if not value or args.database_url_env == 'DATABASE_URL': parser.error('Dedicated isolated database required.')
    url = make_url(value)
    if url.query or url.host not in {'localhost','127.0.0.1'} or not (url.database or '').startswith('openlearn_qualification_') or url.get_backend_name() != 'postgresql':
        parser.error('Only localhost qualification databases are accepted.')
    from dotenv import dotenv_values
    key = dotenv_values(args.key_env_file).get('OPENROUTER_API_KEY')
    if not key: parser.error('The restricted test key is missing; no credential value is printed.')
    os.environ.update(DATABASE_URL=value, OPENROUTER_API_KEY=key, OPENROUTER_MODEL='anthropic/claude-haiku-5.5',
        AI_TUTOR_ENV='development', AI_TUTOR_DEV_IDENTITY='true', OPENLEARN_PROCESS_ROLE='api',
        OPENLEARN_WORKER_MODE='embedded', OPENLEARN_DB_POOL_SIZE='3', OPENLEARN_MIGRATE_ON_START='true',
        OPENLEARN_USAGE_MODE='enforce', OPENLEARN_USAGE_PAID_ROUTES_ENABLED='true',
        OPENLEARN_PROVIDER_RATE_VERSION='openrouter-catalog-2026-10-11-bounded-probe',
        OPENLEARN_HAIKU55_INPUT_USD_PER_MILLION='.1', OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION='.5',
        OPENLEARN_HAIKU55_CACHE_READ_USD_PER_MILLION='.01',
        OPENLEARN_PLATFORM_DAILY_BUDGET_USD='.05', OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD='.05',
        AI_TUTOR_MODEL_MAX_OUTPUT_TOKENS=json.dumps({'anthropic/claude-haiku-5.5':256}),
        AI_TUTOR_ASSESSMENT_MODEL_PROFILES='false', AI_TUTOR_WEB_EVIDENCE='false', AI_TUTOR_EMBEDDING_MODEL='off',
        OPENLEARN_PROVIDER_PREFIX_CACHE_ENABLED='false', OPENLEARN_GENERATION_NOTIFY_ENABLED='false')
    for name in ('OPENAI_API_KEY','EXA_API_KEY','BROWSERBASE_API_KEY','DAYTONA_API_KEY'): os.environ[name] = ''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    from backend.app.storage import Store
    from backend.app.model_provider import OpenRouterLessonProvider
    with tempfile.TemporaryDirectory(prefix='real-tutor-probe-', dir=args.out.parent) as directory:
        os.environ['AI_TUTOR_NOTE_VAULT_DIR'] = str(Path(directory) / 'vault')
        os.environ['OPENLEARN_OBJECT_BACKEND'] = 'local'
        os.environ['OPENLEARN_OBJECT_DIR'] = str(Path(directory) / 'objects')
        store = Store(value)
        try:
            success = asyncio.run(run_probe(store, OpenRouterLessonProvider(key, os.environ['OPENROUTER_MODEL'], None, 'Open Learn restricted performance probe'), args.out))
        finally: store.close()
    print(json.dumps({'allThreeCompleted': success, 'productionQualification': False}))
    raise SystemExit(0 if success else 1)


if __name__ == '__main__': main()
