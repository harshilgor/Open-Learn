"""Supervised hosted roles; no migrations or provider calls during diagnostics."""
import argparse
import os
import signal
import threading
from urllib.parse import urlparse


def configuration_errors(env=None):
    env=os.environ if env is None else env
    errors=[]
    if env.get('AI_TUTOR_ENV') not in {'production','deployed'}:errors.append('AI_TUTOR_ENV')
    if env.get('AI_TUTOR_DEV_IDENTITY')!='false':errors.append('AI_TUTOR_DEV_IDENTITY')
    if not env.get('DATABASE_URL','').startswith('postgresql'):errors.append('DATABASE_URL')
    for key in ('OPENLEARN_OIDC_ISSUER','OPENLEARN_OIDC_JWKS_URL','FORMA_WEB_ORIGIN'):
        if urlparse(env.get(key,'')).scheme!='https':errors.append(key)
    if not env.get('OPENLEARN_OIDC_AUDIENCE'):errors.append('OPENLEARN_OIDC_AUDIENCE')
    if env.get('OPENLEARN_OBJECT_BACKEND')!='s3':errors.append('OPENLEARN_OBJECT_BACKEND')
    for key in ('OPENLEARN_OBJECT_BUCKET','OPENLEARN_ASSISTANT_S3_BUCKET'):
        if not env.get(key):errors.append(key)
    if env.get('OPENLEARN_MIGRATE_ON_START')!='false':errors.append('OPENLEARN_MIGRATE_ON_START')
    if env.get('FORMA_API_TOKEN'):errors.append('FORMA_API_TOKEN must be absent in hosted services')
    try:
        from .usage.policy import Policy
        Policy.load()
    except Exception:
        errors.append('OPENLEARN_USAGE_POLICY_AND_ENABLED_ROUTE_TARIFFS')
    return errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=['check','migrate','api','api-free','generation','learning','agent','class','browser','notifications'])
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    errors=configuration_errors()
    if errors:raise SystemExit('Hosted configuration requires: '+', '.join(errors))
    if args.role=='check':print('Hosted configuration shape valid; connectivity not checked.');return
    os.environ['OPENLEARN_PROCESS_ROLE'] = args.role
    from .database import database_url,run_migrations
    if args.role=='migrate':run_migrations(database_url());return
    if args.role=='api-free':
        worker_mode = os.getenv('OPENLEARN_WORKER_MODE', 'embedded')
        migrations_external = os.getenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL') == 'true'
        if worker_mode not in {'embedded', 'external'}:
            raise SystemExit('api-free requires OPENLEARN_WORKER_MODE=embedded or external')
        if worker_mode == 'external' and not migrations_external:
            raise SystemExit('api-free external workers require the release-owned migration job')
        # Free Render has no pre-deploy command. Complete the migration before
        # importing the app or starting its embedded workers. Concurrent boots
        # share a PostgreSQL lock, including during deploy overlap.
        if migrations_external:
            from .database import require_current_schema
            require_current_schema(database_url())
        else:
            from .database import run_serialized_migrations
            run_serialized_migrations(database_url())
    if args.role in {'api','api-free'}:
        import uvicorn
        from .capacity import process_budget
        uvicorn.run('backend.app.main:app',host='0.0.0.0',port=int(os.getenv('PORT','8000')),workers=1,
                    limit_concurrency=process_budget().http_concurrency)
        return
    from .storage import Store
    from .model_provider import configured_lesson_provider
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    store=Store(database_url())
    try:
        if args.role in {'browser','notifications'} and os.getenv('OPENLEARN_CLOUD_WORKER_STANDBY')=='true':
            from .cloud_worker_health import heartbeat
            while not stop.is_set():
                heartbeat(store,args.role,'standby')
                if args.once:return
                stop.wait(5)
            return
        if args.role=='generation':
            from .generation_worker import GenerationWorker
            GenerationWorker(store, configured_lesson_provider).run(stop, args.once)
        elif args.role=='learning':
            from .worker import run
            run(store,configured_lesson_provider,stop,args.once)
        elif args.role=='notifications':
            from .reminder_worker import NotificationsWorker
            NotificationsWorker(store,configured_lesson_provider).run(stop,args.once)
        elif args.role=='browser':
            from .browser_assistant.workers import AssistantWorker
            AssistantWorker(store,configured_lesson_provider).run(stop,args.once,role='browser')
        elif args.role=='class':
            from .in_class_worker import InClassWorker
            InClassWorker(store,configured_lesson_provider).run(stop,args.once)
        else:
            from .agent_execution.worker import AgentWorker
            provider=configured_lesson_provider();worker=AgentWorker(store,lambda:provider)
            if args.once:worker.tick()
            else:worker.run(stop)
    finally:store.close()


if __name__=='__main__':main()
