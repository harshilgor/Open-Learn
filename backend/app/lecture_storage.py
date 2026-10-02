"""Immutable owner-scoped chunk objects on the existing local data volume."""
from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4
from .object_storage import LocalImmutableObjects


class LectureObjectStore:
    def __init__(self):
        db_path = os.getenv("FORMA_DB_PATH")
        data_root = Path(db_path).resolve().parent if db_path and db_path != ":memory:" else Path(__file__).resolve().parents[1] / "data"
        self.root = (Path(os.getenv("AI_TUTOR_RECORDINGS_DIR", str(data_root / "recordings"))) / "lectures").resolve()
        self.backend = LocalImmutableObjects(self.root)

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
        self._folder(owner, recording_id)
        return self.backend.path(owner, recording_id + "/" + key)

    def write(self, owner: str, recording_id: str, content: bytes) -> tuple[str, str]:
        self._folder(owner, recording_id)
        key = "chunk_" + uuid4().hex
        digest = self.backend.put(owner, recording_id + "/" + key, content)
        return key, digest

    def read(self, owner: str, recording_id: str, key: str) -> bytes:
        self.path(owner, recording_id, key)
        return self.backend.read(owner, recording_id + "/" + key)

    def delete(self, owner: str, recording_id: str, key: str) -> None:
        self.path(owner, recording_id, key)
        self.backend.delete(owner, recording_id + "/" + key)
