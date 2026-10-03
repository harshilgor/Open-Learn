from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from backend.app.database import create_database_engine
from backend.app.migration_inventory import inventory


def test_inventory_is_content_free_and_does_not_upgrade_schema():
    test_root = Path(__file__).resolve().parent
    database = test_root / f".inventory-{uuid4().hex}.db"
    root = database.with_suffix("")
    engine = create_database_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version(version_num TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO alembic_version VALUES('0039_recording_revisions')"))
            conn.execute(text("CREATE TABLE learning_events(id TEXT, owner_id TEXT, payload TEXT)"))
            conn.execute(text("INSERT INTO learning_events VALUES('event1','private-account','PRIVATE NOTE CONTENT')"))
        engine.dispose()

        report = inventory(f"sqlite+pysqlite:///{database.as_posix()}", {
            "FORMA_DB_PATH": str(database),
            "AI_TUTOR_NOTE_VAULT_DIR": str(root / "notes"),
            "AI_TUTOR_MATERIAL_DIR": str(root / "materials"),
            "AI_TUTOR_RECORDINGS_DIR": str(root / "recordings"),
        })

        assert report["schemaRevisions"] == ["0039_recording_revisions"]
        assert report["tableCounts"]["learning_events"] == 1
        assert report["ownerScopedCounts"]["learning_events"] == {"ownerCount": 1, "rowCount": 1}
        assert report["fileStores"]["notes"]["fileCount"] == 0
        assert "private-account" not in str(report)
        assert "PRIVATE NOTE CONTENT" not in str(report)
        assert "private file text" not in str(report)

        check = create_database_engine(f"sqlite+pysqlite:///{database.as_posix()}")
        with check.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0039_recording_revisions"
        check.dispose()
    finally:
        engine.dispose()
        database.unlink(missing_ok=True)
