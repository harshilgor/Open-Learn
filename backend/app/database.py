"""Database configuration and migration startup boundary."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    """Resolve the database without making PostgreSQL a test dependency."""

    configured = os.getenv("DATABASE_URL")
    if configured:
        if os.getenv("AI_TUTOR_ENV", "development").lower() in {"production", "deployed"} and not configured.startswith("postgresql"):
            raise RuntimeError("Deployed environments require a PostgreSQL DATABASE_URL.")
        return configured
    if os.getenv("AI_TUTOR_ENV", "development").lower() in {"production", "deployed"}:
        raise RuntimeError("DATABASE_URL is required in deployed environments.")
    legacy_path = os.getenv("FORMA_DB_PATH")
    if legacy_path:
        if legacy_path == ":memory:":
            return "sqlite+pysqlite:///:memory:"
        return f"sqlite+pysqlite:///{Path(legacy_path).resolve()}"
    return f"sqlite+pysqlite:///{(BACKEND_ROOT / 'data' / 'forma.db').resolve()}"


def create_database_engine(url: str | None = None) -> Engine:
    resolved = url or database_url()
    if resolved.startswith("sqlite") and ":memory:" not in resolved:
        database_file = make_url(resolved).database
        if database_file and not database_file.startswith("file:"):
            Path(database_file).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(resolved, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def run_migrations(url: str | None = None) -> None:
    resolved = url or database_url()
    if resolved.startswith("sqlite") and ":memory:" not in resolved:
        database_file = make_url(resolved).database
        if database_file and not database_file.startswith("file:"):
            Path(database_file).parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", resolved.replace("%", "%%"))
    command.upgrade(config, "head")


def require_current_schema(url: str) -> None:
    """Readers/workers fail closed until the single release migration finishes."""
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    config=Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('script_location',str(BACKEND_ROOT / 'migrations'))
    expected=set(ScriptDirectory.from_config(config).get_heads())
    engine=create_database_engine(url)
    try:
        with engine.connect() as conn:
            if set(MigrationContext.configure(conn).get_current_heads())!=expected:
                raise RuntimeError('Database schema is not current. Run the release migration before starting services.')
    finally:engine.dispose()
