"""Read-only, content-free database and object inventory for migration reviews.

Run with ``python -m backend.app.migration_inventory [--output report.json]``.
This module never constructs Store (which automatically applies migrations).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from .database import create_database_engine, database_url


def _file_inventory(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"present": False, "fileCount": 0, "bytes": 0, "contentSetSha256": hashlib.sha256(b"").hexdigest()}
    digest = hashlib.sha256()
    count = size = 0
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        item_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                item_hash.update(chunk)
                size += len(chunk)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item_hash.digest())
        count += 1
    return {"present": True, "fileCount": count, "bytes": size, "contentSetSha256": digest.hexdigest()}


def inventory(url: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return aggregate counts and file hashes without exposing row contents."""
    values = env or os.environ
    database = url or database_url()
    engine = create_database_engine(database)
    try:
        inspector = inspect(engine)
        tables = sorted(name for name in inspector.get_table_names() if name != "alembic_version")
        counts: dict[str, int] = {}
        ownership_counts: dict[str, dict[str, int]] = {}
        with engine.connect() as connection:
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                counts[table] = int(connection.execute(text(f"SELECT count(*) FROM {quoted}")).scalar_one())
                columns = {column["name"] for column in inspector.get_columns(table)}
                owner_column = next((name for name in ("owner_id", "learner_id", "user_id") if name in columns), None)
                if owner_column:
                    owner = '"' + owner_column + '"'
                    stats = connection.execute(text(
                        f"SELECT count(DISTINCT {owner}), count(*) FROM {quoted} WHERE {owner} IS NOT NULL"
                    )).one()
                    ownership_counts[table] = {"ownerCount": int(stats[0]), "rowCount": int(stats[1])}
            migration = None
            if "alembic_version" in inspector.get_table_names():
                migration = connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
        root = Path(values.get("FORMA_DB_PATH", "backend/data/forma.db")).expanduser().resolve().parent
        roots = {
            "notes": Path(values.get("AI_TUTOR_NOTE_VAULT_DIR", str(root / "notes"))),
            "materials": Path(values.get("AI_TUTOR_MATERIAL_DIR", str(root / "materials"))),
            "recordings": Path(values.get("AI_TUTOR_RECORDINGS_DIR", str(root / "recordings"))),
        }
        return {
            "format": "openlearn-migration-inventory",
            "version": 1,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "databaseDialect": engine.dialect.name,
            "schemaRevisions": migration or [],
            "tableCounts": counts,
            "totalRows": sum(counts.values()),
            "ownerScopedCounts": ownership_counts,
            "fileStores": {name: _file_inventory(path) for name, path in roots.items()},
            "privacy": "No row payloads, source text, note titles, account identifiers, or credentials are included.",
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON to a local report file (stdout by default).")
    args = parser.parse_args()
    report = json.dumps(inventory(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
