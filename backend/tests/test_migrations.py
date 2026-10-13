import sqlite3

from sqlalchemy import inspect, text

try:
    from backend.app.database import database_url
    from backend.app.models import TopicScope, utc_now
    from backend.app.storage import Store
except ModuleNotFoundError:
    from app.database import database_url
    from app.models import TopicScope, utc_now
    from app.storage import Store


def test_migrations_upgrade_legacy_sqlite_without_erasing_history(tmp_path):
    path = tmp_path / "legacy.db"
    scope = TopicScope(
        id="scope_legacy",
        topic="legacy topic",
        resolved_meaning="legacy topic",
        objective="preserve me",
        depth="introductory",
        created_at=utc_now(),
    )
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE topic_scopes (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.execute("INSERT INTO topic_scopes(id, payload) VALUES(?, ?)", (scope.id, scope.model_dump_json()))
    connection.execute("CREATE TABLE learning_sessions (id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, payload TEXT NOT NULL)")
    connection.execute(
        "INSERT INTO learning_sessions(id, graph_id, payload) VALUES(?, ?, ?)",
        (
            "session_legacy",
            "graph_legacy",
            '{"id":"session_legacy","learnerId":"local","graphId":"graph_legacy","graphRevision":1,"gear":"Guided","stateVersion":3,"createdAt":"2026-01-01T00:00:00Z","updatedAt":"2026-01-02T00:00:00Z"}',
        ),
    )
    connection.commit()
    connection.close()

    store = Store(path)
    assert store.get_scope(scope.id) == scope
    tables = set(inspect(store.engine).get_table_names())
    assert {"alembic_version", "evidence", "learner_concept_states", "branches", "notes", "agent_documents", "agent_tasks", "agent_task_events"} <= tables
    with store.engine.connect() as migrated:
        revision = migrated.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        position = migrated.execute(text("SELECT learner_id, state_version FROM learning_sessions WHERE id='session_legacy'")).mappings().one()
    assert revision == "0005_agent_tasks"
    assert dict(position) == {"learner_id": "local", "state_version": 3}
    store.close()


def test_deployed_environment_requires_postgresql(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///not-production.db")
    try:
        database_url()
    except RuntimeError as exc:
        assert "PostgreSQL" in str(exc)
    else:
        raise AssertionError("Production mode accepted a non-PostgreSQL database")


def test_migrations_preserve_existing_policy_history(tmp_path):
    path = tmp_path / "legacy-policy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE teaching_plans (
                id TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
            );
            CREATE TABLE policy_validation_results (
                id TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE,
                plan_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
            );
            INSERT INTO teaching_plans VALUES ('plan_legacy', 'run_legacy', '{"legacy":true}');
            INSERT INTO policy_validation_results VALUES ('validation_legacy', 'run_legacy', 'plan_legacy', '{"accepted":true}');
        """)
    store = Store(path)
    store.close()
    # Starting again must leave the adopted records intact as well.
    store = Store(path)
    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT payload FROM teaching_plans")).scalar_one() == '{"legacy":true}'
        assert connection.execute(text("SELECT payload FROM policy_validation_results")).scalar_one() == '{"accepted":true}'
    store.close()
