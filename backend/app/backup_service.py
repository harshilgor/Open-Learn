"""Versioned, local-only Forma backup archives.

Archives deliberately contain application data only: SQLite records, the
learner-owned Markdown vault, locally owned material objects, and recordings. Provider
credentials live in the desktop OS credential store and are never read here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

ARCHIVE_FORMAT = "forma-local-backup"
ARCHIVE_VERSION = 1
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


class BackupError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"encoding": "base64", "value": base64.b64encode(bytes(value)).decode("ascii")}
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def _safe_relative(name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not name or "\\" in name:
        raise BackupError("invalid_archive", "The backup contains an unsafe file path.")
    return path


class BackupService:
    def __init__(self, store):
        self.store = store
        db_path = os.getenv("FORMA_DB_PATH")
        self.data_root = Path(db_path).resolve().parent if db_path and db_path != ":memory:" else Path(__file__).resolve().parents[1] / "data"
        self.vault_root = Path(os.getenv("AI_TUTOR_NOTE_VAULT_DIR", str(self.data_root / "notes"))).resolve()
        self.material_root = Path(os.getenv("AI_TUTOR_MATERIAL_DIR", str(self.data_root / "materials"))).resolve()
        self.recording_root = Path(os.getenv("AI_TUTOR_RECORDINGS_DIR", str(self.data_root / "recordings"))).resolve()

    def _tables(self) -> dict[str, list[dict[str, Any]]]:
        tables = [name for name in inspect(self.store.engine).get_table_names() if name != "alembic_version"]
        dumped: dict[str, list[dict[str, Any]]] = {}
        with self.store.engine.connect() as connection:
            for table in tables:
                columns = [column["name"] for column in inspect(self.store.engine).get_columns(table)]
                rows = connection.execute(text(f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}"')).mappings().all()
                dumped[table] = [{column: _json(row.get(column)) for column in columns} for row in rows]
        return dumped

    @staticmethod
    def _files(root: Path, prefix: str) -> list[tuple[str, Path]]:
        if not root.is_dir():
            return []
        return [(f"{prefix}/{file.relative_to(root).as_posix()}", file) for file in root.rglob("*") if file.is_file()]

    def create(self) -> bytes:
        export = {"format": "forma-local-export", "version": 1, "tables": self._tables()}
        members: list[tuple[str, bytes | Path]] = [("data/export.json", json.dumps(export, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))]
        members += self._files(self.vault_root, "vault") + self._files(self.material_root, "materials") + self._files(self.recording_root, "recordings")
        checksums = {name: hashlib.sha256(value if isinstance(value, bytes) else value.read_bytes()).hexdigest() for name, value in members}
        manifest = {"format": ARCHIVE_FORMAT, "version": ARCHIVE_VERSION, "createdAt": datetime.now(timezone.utc).isoformat(), "files": checksums,
                    "excludes": ["provider credentials", "desktop tokens", "environment variables", "logs"]}
        with tempfile.SpooledTemporaryFile(max_size=MAX_ARCHIVE_BYTES) as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
                for name, value in members:
                    if isinstance(value, bytes):
                        archive.writestr(name, value)
                    else:
                        archive.write(value, name)
            output.seek(0)
            return output.read()

    def _read(self, payload: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
        if not payload or len(payload) > MAX_ARCHIVE_BYTES:
            raise BackupError("archive_too_large", "The backup is empty or exceeds the local restore size limit.")
        try:
            with zipfile.ZipFile(__import__("io").BytesIO(payload)) as archive:
                names = archive.namelist()
                if len(names) > 10000 or "manifest.json" not in names or "data/export.json" not in names:
                    raise BackupError("invalid_archive", "The backup is missing its required manifest or data export.")
                files = {name: archive.read(name) for name in names if not name.endswith("/")}
        except zipfile.BadZipFile as exc:
            raise BackupError("invalid_archive", "The selected file is not a valid Forma backup.") from exc
        try:
            manifest = json.loads(files.pop("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError("invalid_archive", "The backup manifest is unreadable.") from exc
        if manifest.get("format") != ARCHIVE_FORMAT or manifest.get("version") != ARCHIVE_VERSION:
            raise BackupError("unsupported_archive", "This backup uses an unsupported Forma archive version.")
        expected = manifest.get("files")
        if not isinstance(expected, dict) or set(expected) != set(files):
            raise BackupError("invalid_archive", "The archive manifest does not match its contents.")
        for name, content in files.items():
            _safe_relative(name)
            if hashlib.sha256(content).hexdigest() != expected[name]:
                raise BackupError("checksum_mismatch", f"Backup file {name} is corrupted.")
        return manifest, files

    def preflight(self, payload: bytes) -> dict[str, Any]:
        _, files = self._read(payload)
        try:
            exported = json.loads(files["data/export.json"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError("invalid_archive", "The backup database export is unreadable.") from exc
        tables = exported.get("tables")
        if exported.get("format") != "forma-local-export" or not isinstance(tables, dict):
            raise BackupError("invalid_archive", "The backup database export is invalid.")
        known = set(inspect(self.store.engine).get_table_names()) - {"alembic_version"}
        unknown = set(tables) - known
        if unknown or any(not isinstance(rows, list) for rows in tables.values()):
            raise BackupError("invalid_archive", "The backup has unknown or invalid database tables.")
        existing = sum(len(rows) for rows in self._tables().values())
        return {"archiveVersion": ARCHIVE_VERSION, "tableCount": len(tables), "recordCount": sum(len(rows) for rows in tables.values()),
                "fileCount": len(files) - 1, "existingRecordCount": existing, "requiresReplaceConfirmation": existing > 0}

    @staticmethod
    def _decode(value: Any) -> Any:
        if isinstance(value, dict) and value.get("encoding") == "base64" and isinstance(value.get("value"), str):
            return base64.b64decode(value["value"])
        return value

    def restore(self, payload: bytes, *, confirm_replace: bool) -> dict[str, Any]:
        report = self.preflight(payload)
        if report["requiresReplaceConfirmation"] and not confirm_replace:
            raise BackupError("restore_conflict", "Local data already exists. Confirm replacement after making a fresh backup.", 409)
        _, files = self._read(payload)
        exported = json.loads(files["data/export.json"].decode("utf-8"))
        # Stage filesystem content before touching live paths. Database changes
        # use one transaction; a failure leaves existing data untouched.
        stage = Path(tempfile.mkdtemp(prefix="forma-restore-", dir=self.data_root))
        try:
            for name, content in files.items():
                if name == "data/export.json":
                    continue
                target = stage / _safe_relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            tables: dict[str, list[dict[str, Any]]] = exported["tables"]
            with self.store.transaction() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                for table in reversed(list(tables)):
                    connection.execute(text(f'DELETE FROM "{table.replace(chr(34), chr(34) * 2)}"'))
                for table, rows in tables.items():
                    if rows:
                        columns = list(rows[0])
                        quoted = ", ".join(f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns)
                        parameters = ", ".join(f":{column}" for column in columns)
                        connection.execute(text(f'INSERT INTO "{table.replace(chr(34), chr(34) * 2)}" ({quoted}) VALUES ({parameters})'), [{key: self._decode(value) for key, value in row.items()} for row in rows])
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            for name, root in (("vault", self.vault_root), ("materials", self.material_root), ("recordings", self.recording_root)):
                staged = stage / name
                if root.exists():
                    shutil.rmtree(root)
                if staged.exists():
                    shutil.move(str(staged), str(root))
            return {"restored": report["recordCount"], "files": report["fileCount"], "archiveVersion": ARCHIVE_VERSION}
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError("restore_failed", "Restore failed before completion. Your archive is unchanged; restart Forma and use the backup to retry.", 500) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)
