"""Immutable owner-scoped chunk objects on the existing local data volume."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


class LectureObjectStore:
    def __init__(self):
        db_path = os.getenv("FORMA_DB_PATH")
        data_root = Path(db_path).resolve().parent if db_path and db_path != ":memory:" else Path(__file__).resolve().parents[1] / "data"
        self.root = (Path(os.getenv("AI_TUTOR_RECORDINGS_DIR", str(data_root / "recordings"))) / "lectures").resolve()

    def _folder(self, owner: str, recording_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner) or not re.fullmatch(r"rec_[a-f0-9]{32}", recording_id):
            raise ValueError("Invalid recording identity.")
        folder = (self.root / owner / recording_id).resolve()
        if folder.parent.parent != self.root:
            raise ValueError("Object path escapes recording storage.")
        return folder

    def path(self, owner: str, recording_id: str, key: str) -> Path:
        if not re.fullmatch(r"chunk_[a-f0-9]{32}", key):
            raise ValueError("Invalid storage key.")
        return self._folder(owner, recording_id) / key

    def write(self, owner: str, recording_id: str, content: bytes) -> tuple[str, str]:
        folder = self._folder(owner, recording_id)
        folder.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        key = "chunk_" + uuid4().hex
        destination = self.path(owner, recording_id, key)
        with NamedTemporaryFile("wb", delete=False, dir=folder, prefix=".upload-") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        try:
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return key, digest

    def read(self, owner: str, recording_id: str, key: str) -> bytes:
        return self.path(owner, recording_id, key).read_bytes()

    def delete(self, owner: str, recording_id: str, key: str) -> None:
        self.path(owner, recording_id, key).unlink(missing_ok=True)
