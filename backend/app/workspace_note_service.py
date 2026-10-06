"""Local Markdown vault service for the right-hand learning workspace.

The filesystem is authoritative for authored content.  The database table is
only an owner-scoped, reconstructable metadata/search index.  This service has
no dependency on learner-state services, so note authoring cannot award
mastery by accident.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from .storage import Store
from .workspace_note_models import (
    WorkspaceLinkTargetType,
    WorkspaceNoteCreate,
    WorkspaceNoteExport,
    WorkspaceNoteLinkCreate,
    WorkspaceNoteLinkRecord,
    WorkspaceNoteRecord,
    WorkspaceNoteReindexResponse,
    WorkspaceNoteSummary,
    WorkspaceNoteUpdate,
)


NOTE_ID = re.compile(r"^note_[A-Za-z0-9_-]{8,120}$")
LEARNER_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
LINK_ID = re.compile(r"^link_[A-Za-z0-9_-]{8,120}$")
LINK_TYPES = {"note", "concept", "lesson_block", "attempt", "source_passage"}


class WorkspaceNoteError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback


def _scalar(value: str) -> Any:
    """Parse the conservative YAML subset written by this service.

    Unknown frontmatter is retained as values; deliberately avoid accepting
    YAML tags, aliases, or arbitrary object construction.
    """

    value = value.strip()
    if not value:
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    if value.startswith("[") and value.endswith("]"):
        return [part.strip().strip("'\"") for part in value[1:-1].split(",") if part.strip()]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Return portable frontmatter and the untouched Markdown body.

    Notes without frontmatter are valid as user files, although they are not
    indexed until they have a stable Forma note ID.
    """

    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end < 0:
        return {}, markdown
    metadata: dict[str, Any] = {}
    for line in markdown[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            metadata[key] = _scalar(value)
    return metadata, markdown[end + 5:]


def _frontmatter_value(value: Any) -> str:
    if isinstance(value, str):
        # JSON quoting preserves leading/trailing spaces, colons, and newlines.
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def write_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
            lines.append(f"{key}: {_frontmatter_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


class WorkspaceNoteService:
    def __init__(self, store: Store):
        self.store = store
        # The packaged Electron runtime already supplies FORMA_DB_PATH inside
        # its per-user app-data directory.  Deriving the fallback from it keeps
        # notes out of the installation/resources directory without coupling
        # this backend service to Electron implementation details.
        database_path = os.getenv("FORMA_DB_PATH")
        default_root = (
            Path(database_path).resolve().parent / "notes"
            if database_path and database_path != ":memory:"
            else Path(__file__).resolve().parents[1] / "data" / "notes"
        )
        self.root = Path(os.getenv("AI_TUTOR_NOTE_VAULT_DIR", str(default_root))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_learner(learner_id: str) -> None:
        if not LEARNER_ID.fullmatch(learner_id):
            raise WorkspaceNoteError("invalid_learner", "Invalid learner identifier.", 422)

    @staticmethod
    def _validate_note_id(note_id: str) -> None:
        if not NOTE_ID.fullmatch(note_id):
            raise WorkspaceNoteError("invalid_note", "Invalid note identifier.", 422)

    def learner_root(self, learner_id: str) -> Path:
        self._validate_learner(learner_id)
        path = (self.root / learner_id).resolve()
        if path.parent != self.root:
            raise WorkspaceNoteError("invalid_note_path", "Note path is outside the local vault.", 422)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def note_path(self, learner_id: str, note_id: str) -> Path:
        self._validate_note_id(note_id)
        owner_root = self.learner_root(learner_id)
        path = (owner_root / f"{note_id}.md").resolve()
        if path.parent != owner_root:
            raise WorkspaceNoteError("invalid_note_path", "Note path is outside the local vault.", 422)
        return path

    @staticmethod
    def _file_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _index_payload(frontmatter: dict[str, Any]) -> str:
        return json.dumps(frontmatter, ensure_ascii=False, separators=(",", ":"), default=str)

    def _to_record(self, learner_id: str, relative_path: str, raw: str) -> WorkspaceNoteRecord:
        frontmatter, body = parse_frontmatter(raw)
        note_id = frontmatter.get("id")
        if not isinstance(note_id, str) or not NOTE_ID.fullmatch(note_id):
            raise WorkspaceNoteError("invalid_note_file", "Markdown file has no valid Forma note ID.", 422)
        title = frontmatter.get("title")
        if not isinstance(title, str) or not title.strip():
            title = "Untitled note"
        revision = frontmatter.get("revision")
        try:
            revision = int(revision)
        except (TypeError, ValueError):
            revision = 1
        if revision < 1:
            revision = 1
        now = _utc_now()
        return WorkspaceNoteRecord(
            id=note_id,
            learner_id=learner_id,
            title=title.strip()[:240],
            body=body,
            frontmatter=frontmatter,
            revision=revision,
            relative_path=relative_path,
            created_at=_timestamp(frontmatter.get("created_at"), now),
            updated_at=_timestamp(frontmatter.get("updated_at"), now),
        )

    def _read_file(self, learner_id: str, note_id: str) -> WorkspaceNoteRecord:
        path = self.note_path(learner_id, note_id)
        from .identity import hosted
        if hosted():
            # PostgreSQL retains the exact body and frontmatter. Local Markdown
            # is a disposable cache on independently supervised hosted services.
            with self.store.engine.connect() as conn:
                row=conn.execute(text('SELECT title,frontmatter_json,search_text FROM workspace_notes WHERE id=:id AND learner_id=:owner'),{'id':note_id,'owner':learner_id}).mappings().first()
            if not row:raise WorkspaceNoteError('note_not_found','Note does not exist for this learner.',404)
            prefix=row['title']+'\n'
            if not row['search_text'].startswith(prefix):raise WorkspaceNoteError('invalid_note_file','Stored note content is unavailable.',409)
            self._write_file(path,write_frontmatter(json.loads(row['frontmatter_json']),row['search_text'][len(prefix):]))
        if not path.is_file():
            raise WorkspaceNoteError("note_not_found", "Note does not exist for this learner.", 404)
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceNoteError("invalid_note_file", "Note is not valid UTF-8 Markdown.", 422) from exc
        record = self._to_record(learner_id, path.name, raw)
        if record.id != note_id:
            raise WorkspaceNoteError("invalid_note_file", "Note identifier does not match its file name.", 422)
        return record

    def _indexed_hash(self, learner_id: str, note_id: str) -> str | None:
        with self.store.engine.connect() as connection:
            return connection.execute(text("""
                SELECT content_hash FROM workspace_notes WHERE id=:id AND learner_id=:learner_id
            """), {"id": note_id, "learner_id": learner_id}).scalar_one_or_none()

    def _assert_not_externally_changed(self, learner_id: str, note_id: str) -> None:
        """Do not overwrite a changed Markdown file with an old editor revision.

        A reader can deliberately reload a note (or run reindex) to accept an
        external edit.  Until then the saved file hash is the second half of
        optimistic concurrency alongside the visible revision.
        """

        expected_hash = self._indexed_hash(learner_id, note_id)
        if expected_hash is None:
            return
        actual_hash = self._file_hash(self.note_path(learner_id, note_id).read_text(encoding="utf-8"))
        if actual_hash != expected_hash:
            raise WorkspaceNoteError("external_change_conflict", "The note was changed outside Forma; reload before saving.", 409)

    def _write_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, prefix=".writing-", suffix=".md") as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _upsert_index(self, record: WorkspaceNoteRecord, content_hash: str | None = None) -> None:
        course_id = (record.frontmatter or {}).get("course_id") or (record.frontmatter or {}).get("courseId")
        index_values = {
            "id": record.id,
            "learner_id": record.learner_id,
            "relative_path": record.relative_path,
            "title": record.title,
            "revision": record.revision,
            "frontmatter_json": self._index_payload(record.frontmatter),
            "search_text": f"{record.title}\n{record.body}",
            "content_hash": content_hash or self._file_hash(write_frontmatter(record.frontmatter, record.body)),
            "course_id": course_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        with self.store.transaction() as connection:
            from .identity import hosted
            if hosted():
                suffix=' FOR UPDATE' if connection.dialect.name=='postgresql' else ''
                existing=connection.execute(text('SELECT revision,content_hash FROM workspace_notes WHERE id=:id AND learner_id=:learner_id'+suffix),index_values).mappings().first()
                if existing:
                    if existing['revision']==record.revision and existing['content_hash']==index_values['content_hash']:return
                    if existing['revision']!=record.revision-1:
                        raise WorkspaceNoteError('revision_conflict','The note changed; reload before saving.',409)
            prior=connection.execute(text('SELECT content_hash FROM workspace_notes WHERE id=:id AND learner_id=:learner_id'),index_values).scalar_one_or_none()
            result = connection.execute(text("""
                UPDATE workspace_notes SET relative_path=:relative_path, title=:title, revision=:revision,
                frontmatter_json=:frontmatter_json, search_text=:search_text, content_hash=:content_hash,
                course_id=:course_id,
                created_at=:created_at, updated_at=:updated_at WHERE id=:id AND learner_id=:learner_id
            """), index_values)
            if not result.rowcount:
                connection.execute(text("""
                    INSERT INTO workspace_notes(id, learner_id, relative_path, title, revision, frontmatter_json,
                                                search_text, content_hash, course_id, created_at, updated_at)
                    VALUES (:id, :learner_id, :relative_path, :title, :revision, :frontmatter_json,
                            :search_text, :content_hash, :course_id, :created_at, :updated_at)
                """), index_values)
            if result.rowcount and prior!=index_values['content_hash']:
                from .flashcards.class_adapter import invalidate_source
                invalidate_source(self.store,connection,record.learner_id,record.id)
            self._sync_link_index(connection, record)

    @staticmethod
    def _declared_links(frontmatter: dict[str, Any]) -> list[dict[str, Any]]:
        """Read only Forma's conservative link records from Markdown metadata.

        The Markdown file remains the source of truth: a reindex can recreate
        link and backlink rows after a local recovery.  Invalid hand-edited
        items stay in the document but never become an actionable link.
        """

        raw = frontmatter.get("forma_links")
        if not isinstance(raw, list):
            return []
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            link_id = item.get("id")
            target_type = item.get("target_type")
            target_id = item.get("target_id")
            if not isinstance(link_id, str) or not LINK_ID.fullmatch(link_id) or link_id in seen:
                continue
            if target_type not in LINK_TYPES or not isinstance(target_id, str) or not target_id.strip() or len(target_id) > 360:
                continue
            label = item.get("label")
            created_at = item.get("created_at")
            links.append({
                "id": link_id,
                "target_type": target_type,
                "target_id": target_id.strip(),
                "label": label.strip()[:240] if isinstance(label, str) and label.strip() else None,
                "created_at": created_at if isinstance(created_at, str) else None,
            })
            seen.add(link_id)
        return links

    def _sync_link_index(self, connection: Any, record: WorkspaceNoteRecord) -> None:
        """Replace this source note's reconstructable link index atomically."""

        connection.execute(text("DELETE FROM workspace_note_links WHERE learner_id=:learner_id AND source_note_id=:source_note_id"), {
            "learner_id": record.learner_id, "source_note_id": record.id,
        })
        links = self._declared_links(record.frontmatter)
        if links:
            connection.execute(text("""
                INSERT INTO workspace_note_links
                (id, learner_id, source_note_id, target_type, target_id, label, created_at)
                VALUES (:id, :learner_id, :source_note_id, :target_type, :target_id, :label, :created_at)
            """), [{
                **link,
                "learner_id": record.learner_id,
                "source_note_id": record.id,
                "created_at": _timestamp(link["created_at"], record.updated_at),
            } for link in links])

    def _target_available(self, learner_id: str, target_type: WorkspaceLinkTargetType, target_id: str) -> bool:
        """Check links before rendering them; broken references remain records."""

        if target_type == "note":
            try:
                self._read_file(learner_id, target_id)
                return True
            except WorkspaceNoteError:
                return False
        if target_type == "concept":
            with self.store.engine.connect() as connection:
                return connection.execute(text("SELECT 1 FROM learner_graph_concepts WHERE learner_id=:learner_id AND id=:id"), {
                    "learner_id": learner_id, "id": target_id,
                }).first() is not None
        if target_type == "lesson_block":
            lesson_id, separator, block_id = target_id.partition(":")
            if not separator or not lesson_id or not block_id:
                return False
            artifact = self.store.get_artifact(lesson_id)
            session = self.store.get_session(artifact.session_id) if artifact else None
            return bool(session and session.learner_id == learner_id and any(block.id == block_id for block in artifact.blocks))
        if target_type == "attempt":
            with self.store.engine.connect() as connection:
                return connection.execute(text("SELECT 1 FROM practice_records WHERE owner_id=:owner AND id=:id AND kind='attempt'"), {
                    "owner": learner_id, "id": target_id,
                }).first() is not None
        if target_type == "source_passage":
            with self.store.engine.connect() as connection:
                return connection.execute(text("""
                    SELECT 1 FROM material_blocks block
                    JOIN material_versions version ON version.id=block.version_id
                    JOIN materials material ON material.id=version.material_id
                    WHERE block.id=:id AND material.owner_id=:owner AND material.deleted=false
                """), {"owner": learner_id, "id": target_id}).first() is not None
        return False

    def _validate_link_target(self, learner_id: str, target_type: WorkspaceLinkTargetType, target_id: str) -> None:
        if target_type not in LINK_TYPES or not target_id.strip() or len(target_id) > 360:
            raise WorkspaceNoteError("invalid_link_target", "The note link target is invalid.", 422)
        if not self._target_available(learner_id, target_type, target_id):
            raise WorkspaceNoteError("link_target_not_found", "The link target is not available to this learner.", 404)

    def _link_record(self, learner_id: str, row: Any) -> WorkspaceNoteLinkRecord:
        source_available = self._target_available(learner_id, "note", row["source_note_id"])
        target_available = self._target_available(learner_id, row["target_type"], row["target_id"])
        return WorkspaceNoteLinkRecord(
            id=row["id"], learner_id=learner_id, source_note_id=row["source_note_id"],
            target_type=row["target_type"], target_id=row["target_id"], label=row["label"],
            source_status="available" if source_available else "broken",
            target_status="available" if target_available else "broken",
            created_at=row["created_at"],
        )

    def list_links(self, learner_id: str, source_note_id: str) -> list[WorkspaceNoteLinkRecord]:
        self._validate_learner(learner_id)
        self._validate_note_id(source_note_id)
        # Reading the source confirms caller ownership.  Its index is then
        # fresh before backlinks are rendered.
        self.get(learner_id, source_note_id)
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM workspace_note_links
                WHERE learner_id=:learner_id AND source_note_id=:source_note_id
                ORDER BY created_at ASC, id ASC
            """), {"learner_id": learner_id, "source_note_id": source_note_id}).mappings().all()
        return [self._link_record(learner_id, row) for row in rows]

    def list_backlinks(self, learner_id: str, target_type: WorkspaceLinkTargetType, target_id: str) -> list[WorkspaceNoteLinkRecord]:
        self._validate_learner(learner_id)
        if target_type not in LINK_TYPES or not target_id.strip():
            raise WorkspaceNoteError("invalid_link_target", "The note link target is invalid.", 422)
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT * FROM workspace_note_links
                WHERE learner_id=:learner_id AND target_type=:target_type AND target_id=:target_id
                ORDER BY created_at ASC, id ASC
            """), {"learner_id": learner_id, "target_type": target_type, "target_id": target_id}).mappings().all()
        return [self._link_record(learner_id, row) for row in rows]

    def add_link(self, learner_id: str, source_note_id: str, request: WorkspaceNoteLinkCreate) -> WorkspaceNoteLinkRecord:
        self._validate_link_target(learner_id, request.target_type, request.target_id)
        current = self.get(learner_id, source_note_id)
        if current.revision != request.expected_revision:
            raise WorkspaceNoteError("revision_conflict", "The note changed; reload before saving its links.", 409)
        links = self._declared_links(current.frontmatter)
        if any(item["target_type"] == request.target_type and item["target_id"] == request.target_id for item in links):
            raise WorkspaceNoteError("duplicate_link", "This note already links to that target.", 409)
        link_id = f"link_{uuid4().hex}"
        now = _utc_now().isoformat().replace("+00:00", "Z")
        updated = self.update(learner_id, source_note_id, WorkspaceNoteUpdate(
            expected_revision=current.revision,
            frontmatter={"forma_links": [*links, {
                "id": link_id, "target_type": request.target_type, "target_id": request.target_id,
                "label": request.label, "created_at": now,
            }]},
        ))
        with self.store.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM workspace_note_links WHERE learner_id=:learner_id AND id=:id"), {
                "learner_id": learner_id, "id": link_id,
            }).mappings().one()
        return self._link_record(updated.learner_id, row)

    def remove_link(self, learner_id: str, source_note_id: str, link_id: str, expected_revision: int) -> None:
        if not LINK_ID.fullmatch(link_id):
            raise WorkspaceNoteError("invalid_link", "Invalid note link identifier.", 422)
        current = self.get(learner_id, source_note_id)
        if current.revision != expected_revision:
            raise WorkspaceNoteError("revision_conflict", "The note changed; reload before saving its links.", 409)
        links = self._declared_links(current.frontmatter)
        if not any(item["id"] == link_id for item in links):
            raise WorkspaceNoteError("link_not_found", "The note link does not exist.", 404)
        self.update(learner_id, source_note_id, WorkspaceNoteUpdate(
            expected_revision=current.revision,
            frontmatter={"forma_links": [item for item in links if item["id"] != link_id]},
        ))

    @staticmethod
    def _summary(record: WorkspaceNoteRecord) -> WorkspaceNoteSummary:
        metadata = record.frontmatter or {}
        note_type = ("recording" if metadata.get("lecture_recording_id") or metadata.get("class_recording_id")
                     else "lesson" if metadata.get("study_note") is True else "manual")
        lines = []
        in_code = False
        for raw in record.body.splitlines():
            line = raw.strip()
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not line or line.startswith(("#", "|", "---", "![")):
                continue
            if line.startswith(("This Lesson was created when you started Learn.", "Keep learning in chat", "Study notes maintained with the tutor.", "Your own writing is never rewritten.")):
                continue
            from .content_titles import looks_like_prompt
            if looks_like_prompt(line):
                continue
            line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
            line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
            line = re.sub(r"[`*_~]", "", line).strip()
            if line:
                lines.append(line)
            if len(" ".join(lines)) >= 180:
                break
        paragraph = " ".join(lines).strip()
        preview = re.split(r"(?<=[.!?])\s+", paragraph, maxsplit=1)[0][:180].strip()
        return WorkspaceNoteSummary(
            id=record.id, title=record.title, preview=preview, note_type=note_type,
            frontmatter=record.frontmatter,
            revision=record.revision, relative_path=record.relative_path,
            updated_at=record.updated_at,
        )

    def create(self, learner_id: str, request: WorkspaceNoteCreate, *, command_id: str | None = None) -> WorkspaceNoteRecord:
        self._validate_learner(learner_id)
        if not request.title.strip():
            raise WorkspaceNoteError("invalid_title", "Note title cannot be blank.", 422)
        now = _utc_now()
        note_id = f"note_{uuid4().hex}" if command_id is None else 'note_' + hashlib.sha256(f'{learner_id}:{command_id}'.encode()).hexdigest()[:32]
        if command_id is not None:
            request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
            try:
                existing = self._read_file(learner_id, note_id)
            except WorkspaceNoteError as exc:
                if exc.code != 'note_not_found':
                    raise
            else:
                if existing.frontmatter.get('command_hash') != request_hash:
                    raise WorkspaceNoteError('idempotency_conflict', 'This note command has different content.', 409)
                return existing
        frontmatter = dict(request.frontmatter)
        if command_id is not None:
            frontmatter['command_hash'] = request_hash
        from .content_titles import generate_content_title, looks_like_prompt
        if frontmatter.get("title_source") != "user" and looks_like_prompt(request.title):
            headings = [{"heading": line.lstrip("# ")} for line in request.body.splitlines() if line.startswith("#")]
            title = generate_content_title(request.title, headings)
            old_heading = f"# {request.title}\n"
            body = f"# {title}\n{request.body[len(old_heading):]}" if request.body.startswith(old_heading) else request.body
            request = request.model_copy(update={"title": title, "body": body})
        # Canonical fields always win over supplied import/draft metadata.
        frontmatter.update({
            "id": note_id,
            "title": request.title.strip(),
            "revision": 1,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        })
        record = WorkspaceNoteRecord(
            id=note_id, learner_id=learner_id, title=request.title.strip(), body=request.body,
            frontmatter=frontmatter, revision=1, relative_path=f"{note_id}.md",
            created_at=now, updated_at=now,
        )
        content = write_frontmatter(frontmatter, request.body)
        self._write_file(self.note_path(learner_id, note_id), content)
        self._upsert_index(record, self._file_hash(content))
        return record

    def get(self, learner_id: str, note_id: str) -> WorkspaceNoteRecord:
        record = self._read_file(learner_id, note_id)
        from .identity import hosted
        if not hosted():self._upsert_index(record, self._file_hash(self.note_path(learner_id, note_id).read_text(encoding="utf-8")))
        return record

    def refresh_generated_titles(self, learner_id: str) -> dict[str, int]:
        """Repair legacy prompt titles and recover course IDs from explicit session links."""
        from .content_titles import generate_content_title, looks_like_prompt
        updated = skipped = 0
        for summary in self.list(learner_id):
            metadata = summary.frontmatter or {}
            session_ids = metadata.get("session_ids") or []
            session = self.store.get_session(session_ids[0]) if isinstance(session_ids, list) and session_ids and isinstance(session_ids[0], str) else None
            if session and session.learner_id != learner_id:
                session = None
            changes = {}
            if session and session.course_id and not metadata.get("course_id"):
                changes["course_id"] = session.course_id
            rename = metadata.get("title_source") != "user" and looks_like_prompt(summary.title)
            if not rename and not changes:
                continue
            try:
                note = self.get(learner_id, summary.id)
                title = note.title
                body = note.body
                if rename:
                    headings = [{"heading": line.lstrip("# ")} for line in body.splitlines() if line.startswith("#")]
                    title = session.title if session and session.title and not looks_like_prompt(session.title) else generate_content_title(note.title, headings)
                    old_heading = f"# {note.title}\n"
                    if body.startswith(old_heading):
                        body = f"# {title}\n{body[len(old_heading):]}"
                    changes["title_source"] = "auto"
                self.update(learner_id, note.id, WorkspaceNoteUpdate(expected_revision=note.revision, title=title, body=body, frontmatter=changes))
                updated += 1
            except WorkspaceNoteError:
                skipped += 1
        return {"updated": updated, "skipped": skipped}

    def list(self, learner_id: str) -> list[WorkspaceNoteSummary]:
        self._validate_learner(learner_id)
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id FROM workspace_notes WHERE learner_id=:learner_id ORDER BY updated_at DESC, title ASC
            """), {"learner_id": learner_id}).mappings().all()
        results: list[WorkspaceNoteSummary] = []
        stale: list[str] = []
        for row in rows:
            try:
                results.append(self._summary(self._read_file(learner_id, row["id"])))
            except WorkspaceNoteError as exc:
                if exc.code == "note_not_found":
                    stale.append(row["id"])
                else:
                    raise
        if stale:
            with self.store.transaction() as connection:
                for note_id in stale:
                    connection.execute(text("DELETE FROM workspace_notes WHERE id=:id AND learner_id=:learner_id"), {"id": note_id, "learner_id": learner_id})
        return results

    def search(self, learner_id: str, query: str, limit: int = 30) -> list[WorkspaceNoteSummary]:
        self._validate_learner(learner_id)
        term = query.strip()
        if not term:
            return self.list(learner_id)[:limit]
        # Read only index data here; `reindex` is available after user file edits.
        pattern = f"%{term.lower()}%"
        with self.store.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id FROM workspace_notes WHERE learner_id=:learner_id
                AND LOWER(search_text) LIKE :pattern ORDER BY updated_at DESC, title ASC LIMIT :limit
            """), {"learner_id": learner_id, "pattern": pattern, "limit": limit}).mappings().all()
        notes: list[WorkspaceNoteSummary] = []
        for row in rows:
            try:
                notes.append(self._summary(self._read_file(learner_id, row["id"])))
            except WorkspaceNoteError:
                continue
        return notes

    def update(self, learner_id: str, note_id: str, request: WorkspaceNoteUpdate) -> WorkspaceNoteRecord:
        current = self._read_file(learner_id, note_id)
        self._assert_not_externally_changed(learner_id, note_id)
        if current.revision != request.expected_revision:
            raise WorkspaceNoteError("revision_conflict", "The note changed; reload before saving.", 409)
        now = _utc_now()
        frontmatter = dict(current.frontmatter) if request.frontmatter is None else {**current.frontmatter, **request.frontmatter}
        title = request.title.strip() if request.title is not None else current.title
        if not title:
            raise WorkspaceNoteError("invalid_title", "Note title cannot be blank.", 422)
        body = request.body if request.body is not None else current.body
        revision = current.revision + 1
        frontmatter.update({
            "id": current.id,
            "title": title,
            "revision": revision,
            "created_at": current.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        })
        record = WorkspaceNoteRecord(
            id=current.id, learner_id=learner_id, title=title, body=body, frontmatter=frontmatter,
            revision=revision, relative_path=current.relative_path,
            created_at=current.created_at, updated_at=now,
        )
        content = write_frontmatter(frontmatter, body)
        self._write_file(self.note_path(learner_id, note_id), content)
        self._upsert_index(record, self._file_hash(content))
        return record

    def delete(self, learner_id: str, note_id: str, expected_revision: int) -> None:
        current = self._read_file(learner_id, note_id)
        self._assert_not_externally_changed(learner_id, note_id)
        if current.revision != expected_revision:
            raise WorkspaceNoteError("revision_conflict", "The note changed; reload before deleting.", 409)
        self.note_path(learner_id, note_id).unlink()
        with self.store.transaction() as connection:
            changed=connection.execute(text("DELETE FROM workspace_notes WHERE id=:id AND learner_id=:learner_id AND revision=:revision"), {"id": note_id, "learner_id": learner_id,'revision':expected_revision})
            if changed.rowcount!=1:raise WorkspaceNoteError('revision_conflict','The note changed; reload before deleting.',409)
            from .flashcards.class_adapter import invalidate_source
            invalidate_source(self.store,connection,learner_id,note_id)

    def reindex(self, learner_id: str) -> WorkspaceNoteReindexResponse:
        from .identity import hosted
        if hosted():
            raise WorkspaceNoteError('local_only','Hosted notes are retained in the database; local directory reindex is unavailable.',409)
        owner_root = self.learner_root(learner_id)
        observed: set[str] = set()
        indexed = skipped = 0
        for path in owner_root.rglob("*.md"):
            resolved = path.resolve()
            if owner_root not in resolved.parents:
                skipped += 1
                continue
            try:
                raw = resolved.read_text(encoding="utf-8")
                relative_path = resolved.relative_to(owner_root).as_posix()
                record = self._to_record(learner_id, relative_path, raw)
                if resolved != self.note_path(learner_id, record.id):
                    skipped += 1
                    continue
                self._upsert_index(record, self._file_hash(raw))
                observed.add(record.id)
                indexed += 1
            except (OSError, UnicodeDecodeError, WorkspaceNoteError):
                skipped += 1
        with self.store.transaction() as connection:
            existing = connection.execute(text("SELECT id FROM workspace_notes WHERE learner_id=:learner_id"), {"learner_id": learner_id}).scalars().all()
            removed = 0
            for note_id in existing:
                if note_id not in observed:
                    from .flashcards.class_adapter import invalidate_source
                    invalidate_source(self.store,connection,learner_id,note_id)
                    removed += connection.execute(text("DELETE FROM workspace_notes WHERE id=:id AND learner_id=:learner_id"), {"id": note_id, "learner_id": learner_id}).rowcount
        return WorkspaceNoteReindexResponse(indexed=indexed, skipped=skipped, removed=removed)

    def export(self, learner_id: str) -> WorkspaceNoteExport:
        self.reindex(learner_id)
        return WorkspaceNoteExport(learner_id=learner_id, notes=[self.get(learner_id, item.id) for item in self.list(learner_id)])
