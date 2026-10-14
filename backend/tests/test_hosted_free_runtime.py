"""Free-service boot must finish migration before serving or running jobs."""
import sys
from unittest.mock import MagicMock

import pytest

from backend.app import database, hosted_runtime


def test_free_boot_migrates_before_uvicorn(monkeypatch):
    monkeypatch.delenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL', raising=False)
    monkeypatch.setattr(hosted_runtime, 'configuration_errors', lambda: [])
    monkeypatch.setenv('OPENLEARN_WORKER_MODE', 'embedded')
    monkeypatch.setattr(sys, 'argv', ['hosted_runtime', 'api-free'])
    monkeypatch.setattr(database, 'database_url', lambda: 'postgresql+psycopg://test')
    events = []
    monkeypatch.setattr(database, 'run_serialized_migrations', lambda url: events.append('migrate'))
    import uvicorn
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: events.append('serve'))
    hosted_runtime.main()
    assert events == ['migrate', 'serve']


def test_failed_free_migration_does_not_serve(monkeypatch):
    monkeypatch.delenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL', raising=False)
    monkeypatch.setattr(hosted_runtime, 'configuration_errors', lambda: [])
    monkeypatch.setenv('OPENLEARN_WORKER_MODE', 'embedded')
    monkeypatch.setattr(sys, 'argv', ['hosted_runtime', 'api-free'])
    def fail(url):
        raise RuntimeError('migration failed')
    monkeypatch.setattr(database, 'run_serialized_migrations', fail)
    import uvicorn
    serve = MagicMock()
    monkeypatch.setattr(uvicorn, 'run', serve)
    with pytest.raises(RuntimeError, match='migration failed'):
        hosted_runtime.main()
    serve.assert_not_called()


def test_migration_lock_is_released_on_failure(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr(database, 'create_database_engine', lambda url: engine)
    monkeypatch.setattr(database, 'run_migrations', MagicMock(side_effect=RuntimeError('failed')))
    with pytest.raises(RuntimeError, match='failed'):
        database.run_serialized_migrations('postgresql+psycopg://test')
    engine.begin.return_value.__exit__.assert_called_once()
    engine.dispose.assert_called_once()


def test_free_boot_requires_release_migration_owner_for_external_mode(monkeypatch):
    monkeypatch.setattr(hosted_runtime, 'configuration_errors', lambda: [])
    monkeypatch.setenv('OPENLEARN_WORKER_MODE', 'external')
    monkeypatch.delenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL', raising=False)
    monkeypatch.setattr(sys, 'argv', ['hosted_runtime', 'api-free'])
    with pytest.raises(SystemExit, match='release-owned migration job'):
        hosted_runtime.main()


def test_release_managed_free_boot_checks_schema_without_migrating(monkeypatch):
    monkeypatch.setattr(hosted_runtime, 'configuration_errors', lambda: [])
    monkeypatch.setenv('OPENLEARN_WORKER_MODE', 'embedded')
    monkeypatch.setenv('OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL', 'true')
    monkeypatch.setattr(sys, 'argv', ['hosted_runtime', 'api-free'])
    monkeypatch.setattr(database, 'database_url', lambda: 'postgresql+psycopg://test')
    events = []
    monkeypatch.setattr(database, 'require_current_schema', lambda url: events.append('schema-check'))
    migrate = MagicMock()
    monkeypatch.setattr(database, 'run_serialized_migrations', migrate)
    import uvicorn
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: events.append('serve'))
    hosted_runtime.main()
    assert events == ['schema-check', 'serve']
    migrate.assert_not_called()


def test_cloud_worker_standby_does_not_claim_tasks(monkeypatch):
    from backend.app import storage,cloud_worker_health
    monkeypatch.setattr(hosted_runtime,'configuration_errors',lambda:[])
    monkeypatch.setattr(database,'database_url',lambda:'postgresql+psycopg://test')
    store=MagicMock()
    monkeypatch.setattr(storage,'Store',lambda url:store)
    monkeypatch.setattr(sys,'argv',['hosted_runtime','browser','--once'])
    monkeypatch.setenv('OPENLEARN_CLOUD_WORKER_STANDBY','true')
    heartbeat=MagicMock()
    monkeypatch.setattr(cloud_worker_health,'heartbeat',heartbeat)
    from backend.app.browser_assistant.workers import AssistantWorker
    run=MagicMock()
    monkeypatch.setattr(AssistantWorker,'run',run)
    hosted_runtime.main()
    heartbeat.assert_called_once_with(store,'browser','standby')
    run.assert_not_called()
    store.close.assert_called_once()
