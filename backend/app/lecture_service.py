"""Owner-scoped lecture session, chunk admission, continuity, and status."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .lecture_models import LectureCreate, LectureFinalize, LecturePreferences
from .lecture_storage import LectureObjectStore
from .storage import Store
from .workflow_store import WorkflowStore
from .workspace_note_models import WorkspaceNoteCreate
from .workspace_note_service import WorkspaceNoteService

log = logging.getLogger(__name__)
MAX_CHUNK_BYTES = 4 * 1024 * 1024
MIME_TYPES = {"audio/webm", "audio/mp4", "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/aac", "audio/flac"}
STAGES = {"transcription": "pending", "semanticAnalysis": "pending", "noteGeneration": "pending", "verification": "pending"}


class LectureError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class LectureService:
    def __init__(self, store: Store):
        self.store = store
        self.objects = LectureObjectStore()
        self.jobs = WorkflowStore(store)

    def chunk_audio(self,owner,recording_id,sequence):
        """Read through the object adapter so hosted audio works across workers."""
        with self.store.transaction() as conn:
            recording=self._row(owner,recording_id,conn)
            if not recording:raise LectureError('recording_not_found','Recording unavailable.',404)
            preferences=self._preferences(recording)
            stages=json.loads(recording['stage_json'])
            if recording['status']=='completed' and preferences.get('keepAudio',True) is False and stages.get('audioRetention')=='removed':
                raise LectureError('audio_removed','Audio was removed according to this recording’s retention setting.',404)
            row=conn.execute(text('SELECT storage_key,media_type,sha256 FROM lecture_audio_chunks WHERE recording_id=:id AND sequence_number=:sequence'),{'id':recording_id,'sequence':sequence}).mappings().first()
            if not row:raise LectureError('chunk_not_found','Audio slice unavailable.',404)
            try:content=self.objects.read(owner,recording_id,row['storage_key'])
            except OSError as exc:
                if recording['status']=='completed' and preferences.get('keepAudio',True) is False:
                    raise LectureError('audio_removed','Audio was removed according to this recording’s retention setting.',404) from exc
                raise LectureError('chunk_storage_missing','The audio copy is unavailable; processing needs repair.',503) from exc
            if hashlib.sha256(content).hexdigest()!=row['sha256']:raise LectureError('audio_integrity_failed','Audio integrity check failed.',409)
            return content,row['media_type']

    def _row(self, owner: str, recording_id: str, connection=None):
        def query(conn):
            return conn.execute(text("SELECT * FROM lecture_recordings WHERE id=:id AND learner_id=:owner"), {"id": recording_id, "owner": owner}).mappings().first()
        if connection is None:
            with self.store.engine.connect() as conn:
                row = query(conn)
        else:
            row = query(connection)
        if not row:
            raise LectureError("recording_not_found", "Lecture recording not found.", 404)
        return row

    @staticmethod
    def _preferences(row):
        preferences = json.loads(row["preferences_json"])
        preferences["keepAudio"] = preferences.get("keepAudio", preferences.get("keep_audio", True))
        preferences["captureSystemAudio"] = preferences.get("captureSystemAudio", preferences.get("capture_system_audio", False))
        return preferences

    def create(self, owner: str, command: LectureCreate):
        try:
            existing = self._row(owner, command.id)
        except LectureError as exc:
            if exc.status_code != 404:
                raise
            existing = None
        if existing:
            if existing["title"] != command.title.strip() or existing["course_id"] != command.course_id or existing["started_at"] != command.started_at_ms / 1000:
                raise LectureError("recording_conflict", "This recording ID already belongs to another capture.", 409)
            if command.buddy_id:
                with self.store.engine.connect() as conn:
                    buddy=conn.execute(text('SELECT buddy_id FROM buddy_classes WHERE id=:id AND owner_id=:owner'),{'id':command.id,'owner':owner}).scalar_one_or_none()
                if buddy and buddy!=command.buddy_id:raise LectureError('recording_conflict','This recording already has another Buddy.',409)
            return self.status(owner, command.id)
        if command.course_id:
            with self.store.engine.connect() as conn:
                course = conn.execute(text("SELECT id FROM courses WHERE id=:id AND owner_id=:owner AND archived_at IS NULL"), {"id": command.course_id, "owner": owner}).first()
            if not course:
                raise LectureError("course_not_found", "The selected course is unavailable.", 404)
        frontmatter = {"lecture_recording_id": command.id, "lecture_pipeline_version": 1, "lecture_recording_status": "recording"}
        from .buddy_service import BuddyService
        with self.store.transaction() as conn:
            resolved_buddy = BuddyService(self.store).resolve(conn,owner,command.course_id,command.buddy_id)
        frontmatter['buddy_id'] = resolved_buddy
        if command.note_folder:
            frontmatter["note_folder"] = command.note_folder
        if command.course_id:
            frontmatter["course_id"] = command.course_id
        note = WorkspaceNoteService(self.store).create(owner, WorkspaceNoteCreate(title=command.title.strip(), body="", frontmatter=frontmatter))
        now = time.time()
        try:
            with self.store.transaction() as conn:
                BuddyService(self.store).profile(conn,owner,resolved_buddy,True)
                conn.execute(text('INSERT INTO buddy_classes(id,owner_id,buddy_id) VALUES(:id,:owner,:buddy) ON CONFLICT(id) DO NOTHING'), {'id':command.id,'owner':owner,'buddy':resolved_buddy})
                conn.execute(text("""INSERT INTO lecture_recordings(id,learner_id,note_id,course_id,title,status,expected_chunk_count,duration_ms,markers_json,preferences_json,stage_json,pipeline_version,generation_version,started_at,created_at,updated_at)
                    VALUES (:id,:owner,:note,:course,:title,'recording',NULL,0,'[]',:prefs,:stages,1,0,:started,:now,:now)"""), {
                    "id": command.id, "owner": owner, "note": note.id, "course": command.course_id,
                    "title": command.title.strip(), "prefs": encoded(command.preferences.model_dump(mode="json", by_alias=True)),
                    "stages": encoded(STAGES), "started": command.started_at_ms / 1000, "now": now,
                })
        except IntegrityError as exc:
            try:
                WorkspaceNoteService(self.store).delete(owner, note.id, note.revision)
            except Exception:
                pass
            existing = self._row(owner, command.id)
            if existing["title"] == command.title.strip() and existing["course_id"] == command.course_id:
                return self.status(owner, command.id)
            raise LectureError("recording_conflict", "This recording ID already belongs to another capture.", 409) from exc
        except Exception:
            WorkspaceNoteService(self.store).delete(owner,note.id,note.revision)
            raise
        log.info("lecture.created recording_id=%s owner=%s", command.id, owner)
        return self.status(owner, command.id)

    @staticmethod
    def _sniff(content: bytes, media_type: str) -> bool:
        if media_type == "audio/webm":
            return content.startswith(b"\x1a\x45\xdf\xa3")
        if media_type == "audio/mp4":
            return len(content) >= 12 and content[4:8] == b"ftyp"
        if media_type in {"audio/wav", "audio/x-wav"}:
            return content.startswith(b"RIFF") and content[8:12] == b"WAVE"
        if media_type in {"audio/mpeg", "audio/mp3"}:
            return content.startswith(b"ID3") or (len(content) > 2 and content[0] == 0xff and content[1] & 0xe0 == 0xe0)
        if media_type == "audio/ogg":
            return content.startswith(b"OggS")
        if media_type == "audio/flac":
            return content.startswith(b"fLaC")
        return bool(content)

    def put_chunk(self, owner: str, recording_id: str, sequence: int, content: bytes, *, start_ms: int, end_ms: int, media_type: str, checksum: str, capture_epoch: int | None = None, epoch_sequence: int = 0, independent_media: bool = True):
        row = self._row(owner, recording_id)
        capture_epoch = sequence if capture_epoch is None else capture_epoch
        if capture_epoch < 0 or epoch_sequence != 0 or not independent_media:
            raise LectureError('unsupported_capture_adapter', 'This adapter requires complete initialized audio segments. Continuous container fragments need an assembly adapter.', 415)
        if sequence < 0 or sequence >= 10000 or start_ms < 0 or end_ms <= start_ms or end_ms - start_ms > 60_000 or end_ms > 24 * 60 * 60 * 1000:
            raise LectureError("invalid_chunk_time", "The audio slice has invalid timing or sequence.")
        if row["expected_chunk_count"] is not None and sequence >= row["expected_chunk_count"]:
            raise LectureError("chunk_outside_finalized_count", "This slice is beyond the stopped recording.", 409)
        media_type = media_type.split(";", 1)[0].strip().lower()
        if media_type not in MIME_TYPES or not self._sniff(content, media_type):
            raise LectureError("unsupported_audio", "This audio slice is not a supported playable audio file.", 415)
        if not content or len(content) > MAX_CHUNK_BYTES:
            raise LectureError("chunk_too_large", "An audio slice must be smaller than 4 MB.", 413)
        digest = hashlib.sha256(content).hexdigest()
        if digest != checksum.lower():
            raise LectureError("checksum_mismatch", "The audio slice changed before upload.", 422)
        params = {"recording": recording_id, "sequence": sequence}
        with self.store.engine.connect() as conn:
            existing = conn.execute(text("SELECT * FROM lecture_audio_chunks WHERE recording_id=:recording AND sequence_number=:sequence"), params).mappings().first()
        if existing:
            return self._duplicate(owner, recording_id, existing, digest, len(content), start_ms, end_ms, media_type)
        if row["status"] in {"completed", "cancelled"}:
            raise LectureError("recording_closed", "This recording no longer accepts audio.", 409)
        ingest_started_at = time.time()
        key, stored_hash = self.objects.write(owner, recording_id, content)
        now = time.time()
        chunk_id = uid("ach")
        try:
            with self.store.transaction() as conn:
                if conn.dialect.name == "sqlite":
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                lock_suffix = " FOR UPDATE" if conn.dialect.name == "postgresql" else ""
                current = conn.execute(text("SELECT status,expected_chunk_count,duration_ms FROM lecture_recordings WHERE id=:id AND learner_id=:owner" + lock_suffix), {"id": recording_id, "owner": owner}).mappings().first()
                if not current:
                    raise LectureError("recording_not_found", "This recording is not available.", 404)
                if current["status"] in {"completed", "cancelled"}:
                    raise LectureError("recording_closed", "This recording no longer accepts audio.", 409)
                if current["expected_chunk_count"] is not None and sequence >= current["expected_chunk_count"]:
                    raise LectureError("chunk_outside_finalized_count", "This slice is beyond the stopped recording.", 409)
                # Active recordings carry a placeholder duration (the legacy
                # schema requires a non-null value). Enforce the duration fence
                # only after finalization pins expected_chunk_count and duration.
                if current["expected_chunk_count"] is not None and end_ms > current["duration_ms"]:
                    raise LectureError("chunk_outside_finalized_duration", "This slice extends beyond the stopped recording.", 409)
                conn.execute(text("""INSERT INTO lecture_audio_chunks(id,recording_id,sequence_number,start_ms,end_ms,media_type,byte_count,sha256,storage_key,transcription_status,transcription_attempts,created_at,updated_at)
                    VALUES (:id,:recording,:sequence,:start,:end,:mime,:size,:hash,:key,'pending',0,:now,:now)"""), {
                    "id": chunk_id, "recording": recording_id, "sequence": sequence, "start": start_ms,
                    "end": end_ms, "mime": media_type, "size": len(content), "hash": stored_hash,
                    "key": key, "now": now,
                })
                job = self.jobs.enqueue(owner, recording_id, "lecture_transcribe", {"recording_id": recording_id, "sequence": sequence}, f"lecture:chunk:{recording_id}:{sequence}", connection=conn)
                conn.execute(text('UPDATE lecture_audio_chunks SET capture_epoch=:epoch,epoch_sequence=:epoch_sequence,independent_media=:independent WHERE recording_id=:recording AND sequence_number=:sequence'), {'epoch': capture_epoch, 'epoch_sequence': epoch_sequence, 'independent': independent_media, 'recording': recording_id, 'sequence': sequence})
                class_id = conn.execute(text('SELECT id FROM class_sessions WHERE recording_id=:recording AND owner_id=:owner'), {'recording': recording_id, 'owner': owner}).scalar_one_or_none()
                if class_id:
                    from .in_class_metrics import record as record_metric
                    record_metric(conn,owner=owner,class_id=class_id,stage='capture_ingest',correlation_id=chunk_id,queued_at=ingest_started_at,started_at=ingest_started_at,finished_at=time.time(),counters={'bytes':len(content)})
        except IntegrityError:
            self.objects.delete(owner, recording_id, key)
            with self.store.engine.connect() as conn:
                existing = conn.execute(text("SELECT * FROM lecture_audio_chunks WHERE recording_id=:recording AND sequence_number=:sequence"), params).mappings().first()
            if existing:
                return self._duplicate(owner, recording_id, existing, digest, len(content), start_ms, end_ms, media_type)
            raise
        except Exception:
            # The immutable object was written before the SQL transaction. If
            # any other database error aborts that transaction, remove the
            # unreferenced object before propagating the failure.
            self.objects.delete(owner, recording_id, key)
            raise
        log.info("lecture.chunk.accepted recording_id=%s sequence=%s bytes=%s", recording_id, sequence, len(content))
        self.maybe_enqueue_finalize(owner, recording_id)
        return {"recordingId": recording_id, "sequenceNumber": sequence, "sha256": digest, "byteCount": len(content), "transcriptionStatus": "pending", "duplicate": False, "jobId": job["id"]}

    def _duplicate(self, owner, recording_id, row, digest, byte_count, start_ms, end_ms, media_type):
        if (row["sha256"], row["byte_count"], row["start_ms"], row["end_ms"], row["media_type"]) != (digest, byte_count, start_ms, end_ms, media_type):
            raise LectureError("chunk_conflict", "A different audio slice already occupies this position.", 409)
        try:
            existing_bytes = self.objects.read(owner, recording_id, row["storage_key"])
        except OSError as exc:
            recording = self._row(owner, recording_id)
            preferences = self._preferences(recording)
            if recording["status"] == "completed" and not preferences.get("keepAudio", True):
                return {"recordingId": recording_id, "sequenceNumber": row["sequence_number"], "sha256": digest, "byteCount": byte_count, "transcriptionStatus": row["transcription_status"], "duplicate": True}
            raise LectureError("chunk_storage_missing", "The server copy is unavailable; processing needs repair.", 503) from exc
        if hashlib.sha256(existing_bytes).hexdigest() != digest:
            raise LectureError("chunk_storage_corrupt", "The server copy failed its integrity check.", 503)
        return {"recordingId": recording_id, "sequenceNumber": row["sequence_number"], "sha256": digest, "byteCount": byte_count, "transcriptionStatus": row["transcription_status"], "duplicate": True}

    def finalize(self, owner: str, recording_id: str, command: LectureFinalize):
        row = self._row(owner, recording_id)
        if command.markers_ms and command.markers_ms[-1] > command.duration_ms:
            raise LectureError("marker_outside_recording", "A marker is beyond the end of the recording.")
        with self.store.transaction() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            lock_suffix = " FOR UPDATE" if conn.dialect.name == "postgresql" else ""
            current = conn.execute(text("SELECT status,expected_chunk_count,duration_ms FROM lecture_recordings WHERE id=:id AND learner_id=:owner" + lock_suffix), {"id": recording_id, "owner": owner}).mappings().first()
            if not current:
                raise LectureError("recording_not_found", "This recording is not available.", 404)
            if current["status"] == "cancelled":
                raise LectureError("recording_closed", "This recording is no longer accepting changes.", 409)
            if current["expected_chunk_count"] is not None and (current["expected_chunk_count"] != command.expected_chunk_count or current["duration_ms"] != command.duration_ms):
                raise LectureError("finalization_conflict", "The stop details differ from the saved recording.", 409)
            extra_chunk = conn.execute(text("SELECT 1 FROM lecture_audio_chunks WHERE recording_id=:id AND sequence_number>=:count LIMIT 1"), {"id": recording_id, "count": command.expected_chunk_count}).first()
            if extra_chunk:
                raise LectureError("finalization_chunk_conflict", "Saved audio extends beyond the requested stop point.", 409)
            if current["expected_chunk_count"] is None:
                conn.execute(text("UPDATE lecture_recordings SET status='waiting_for_uploads',expected_chunk_count=:count,capture_interrupted=:interrupted,duration_ms=:duration,markers_json=:markers,stopped_at=:now,updated_at=:now WHERE id=:id AND learner_id=:owner AND expected_chunk_count IS NULL"), {
                    "count": command.expected_chunk_count, "duration": command.duration_ms,
                    "interrupted": command.capture_interrupted, "markers": encoded(command.markers_ms), "now": time.time(), "id": recording_id, "owner": owner,
                })
                from .in_class_service import handoff
                handoff(conn,owner,recording_id,'finalize')
        self.maybe_enqueue_finalize(owner, recording_id)
        return self.status(owner, recording_id)

    def maybe_enqueue_finalize(self, owner: str, recording_id: str):
        row = self._row(owner, recording_id)
        expected = row["expected_chunk_count"]
        if expected is None or row["status"] == "cancelled":
            return None
        if row["status"] == "completed":
            self._schedule_unretained_audio_removal(owner, recording_id, row)
            return None
        with self.store.engine.connect() as conn:
            class_recording = conn.execute(text("SELECT 1 FROM class_sessions WHERE recording_id=:id AND owner_id=:owner"), {"id": recording_id, "owner": owner}).first()
            chunks = conn.execute(text("SELECT sequence_number,transcription_status,storage_key FROM lecture_audio_chunks WHERE recording_id=:id"), {"id": recording_id}).all()
            if class_recording:
                # In-Class owns semantic processing. Mark the recording archive
                # complete once every expected chunk is transcribed, without
                # enqueueing a second legacy post-class semantic pass.
                by_sequence = {seq: status for seq, status, _key in chunks}
                if len(by_sequence) == expected and all(by_sequence.get(seq) == "completed" for seq in range(expected)):
                    stages = json.loads(row["stage_json"])
                    stages.update({"transcription": "completed", "semanticAnalysis": "class_managed", "noteGeneration": "class_managed", "verification": "class_managed"})
                    with self.store.transaction() as write:
                        changed = write.execute(text("UPDATE lecture_recordings SET status='completed',stage_json=:stages,error=NULL,updated_at=:now WHERE id=:id AND learner_id=:owner AND expected_chunk_count=:expected AND status!='completed'"), {"stages": encoded(stages), "now": time.time(), "id": recording_id, "owner": owner, "expected": expected})
                    if changed.rowcount == 1:
                        self._schedule_unretained_audio_removal(owner, recording_id)
                return None
        by_sequence = {seq: status for seq, status, _key in chunks}
        if len(by_sequence) != expected or any(by_sequence.get(seq) != "completed" for seq in range(expected)):
            return None
        stages = json.loads(row["stage_json"])
        if stages.get("semanticAnalysis") == "completed":
            return None
        job = self.jobs.enqueue(owner, recording_id, "lecture_segment", {"recording_id": recording_id}, f"lecture:segment:{recording_id}")
        with self.store.transaction() as conn:
            stages["semanticAnalysis"] = "queued"
            conn.execute(text("UPDATE lecture_recordings SET status='processing',stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner AND status!='completed'"), {"stages": encoded(stages), "now": time.time(), "id": recording_id, "owner": owner})
        return job

    def _schedule_unretained_audio_removal(self, owner: str, recording_id: str, row=None):
        row = row or self._row(owner, recording_id)
        if row["status"] != "completed":
            return
        preferences = self._preferences(row)
        stages = json.loads(row["stage_json"])
        if preferences.get("keepAudio", True) or stages.get("audioRetention") in {"removed", "failed"}:
            return
        with self.store.transaction() as conn:
            current = conn.execute(text("SELECT status,stage_json FROM lecture_recordings WHERE id=:id AND learner_id=:owner"), {"id": recording_id, "owner": owner}).mappings().first()
            if not current or current["status"] != "completed":
                return
            current_stages = json.loads(current["stage_json"])
            if current_stages.get("audioRetention") == "removed":
                return
            current_stages.setdefault("audioRetention", "pending")
            current_stages.setdefault("audioRetentionCursor", -1)
            current_stages.setdefault("audioRetentionGeneration", 0)
            conn.execute(text("UPDATE lecture_recordings SET stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner AND status='completed'"), {"stages": encoded(current_stages), "now": time.time(), "id": recording_id, "owner": owner})
            after_sequence = int(current_stages["audioRetentionCursor"])
            generation = int(current_stages["audioRetentionGeneration"])
            self.jobs.enqueue(owner, recording_id, "lecture_audio_retention",
                              {"recording_id": recording_id, "after_sequence": after_sequence, "generation": generation},
                              f"lecture:audio-retention:{recording_id}:{generation}:{after_sequence}",
                              connection=conn, queue="batch")

    def remove_audio_page(self, owner: str, recording_id: str, after_sequence: int, generation: int, page_size: int = 100):
        row = self._row(owner, recording_id)
        preferences = self._preferences(row)
        stages = json.loads(row["stage_json"])
        if preferences.get("keepAudio", True) or stages.get("audioRetention") != "pending" or int(stages.get("audioRetentionGeneration", 0)) != generation:
            return {"status": stages.get("audioRetention", "unchanged")}
        cursor = int(stages.get("audioRetentionCursor", -1))
        if after_sequence < cursor:
            return {"status": "continued"}
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("""SELECT sequence_number,storage_key FROM lecture_audio_chunks
                WHERE recording_id=:id AND sequence_number>:after
                ORDER BY sequence_number LIMIT :limit"""), {"id": recording_id, "after": after_sequence, "limit": page_size}).all()
        for _sequence, key in rows:
            self.objects.delete(owner, recording_id, key)
        with self.store.transaction() as conn:
            current = conn.execute(text("SELECT status,preferences_json,stage_json FROM lecture_recordings WHERE id=:id AND learner_id=:owner"), {"id": recording_id, "owner": owner}).mappings().first()
            if not current:
                return {"status": "unavailable"}
            current_preferences = self._preferences(current)
            current_stages = json.loads(current["stage_json"])
            if current_preferences.get("keepAudio", True) or current_stages.get("audioRetention") != "pending" or int(current_stages.get("audioRetentionGeneration", 0)) != generation:
                return {"status": current_stages.get("audioRetention", "changed")}
            if rows:
                current_stages["audioRetentionCursor"] = int(rows[-1][0])
            if len(rows) < page_size:
                current_stages["audioRetention"] = "removed"
                current_stages.pop("audioRetentionCursor", None)
                current_stages.pop("audioRetentionError", None)
            conn.execute(text("UPDATE lecture_recordings SET stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner"), {
                "stages": encoded(current_stages), "now": time.time(), "id": recording_id, "owner": owner,
            })
            if current_stages["audioRetention"] == "pending":
                next_sequence = int(current_stages["audioRetentionCursor"])
                self.jobs.enqueue(owner, recording_id, "lecture_audio_retention",
                                  {"recording_id": recording_id, "after_sequence": next_sequence, "generation": generation},
                                  f"lecture:audio-retention:{recording_id}:{generation}:{next_sequence}",
                                  connection=conn, queue="batch")
        return {"status": current_stages["audioRetention"], "deletedThrough": current_stages.get("audioRetentionCursor")}

    def mark_audio_retention_failed(self, owner: str, recording_id: str, generation: int):
        with self.store.transaction() as conn:
            row = conn.execute(text("SELECT stage_json FROM lecture_recordings WHERE id=:id AND learner_id=:owner"), {"id": recording_id, "owner": owner}).mappings().first()
            if not row:
                return
            stages = json.loads(row["stage_json"])
            if stages.get("audioRetention") != "pending" or int(stages.get("audioRetentionGeneration", 0)) != generation:
                return
            stages["audioRetention"] = "failed"
            stages["audioRetentionError"] = "Audio removal needs another attempt."
            conn.execute(text("UPDATE lecture_recordings SET stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner"), {
                "stages": encoded(stages), "now": time.time(), "id": recording_id, "owner": owner,
            })

    def remove_audio(self, owner: str, recording_id: str):
        row = self._row(owner, recording_id)
        if row["status"] != "completed":
            raise LectureError("recording_not_ready", "Finish processing before removing the saved audio.", 409)
        preferences = self._preferences(row)
        preferences.pop("keep_audio", None)
        preferences.pop("capture_system_audio", None)
        preferences["keepAudio"] = False
        with self.store.transaction() as conn:
            stages = json.loads(row["stage_json"])
            if stages.get("audioRetention") == "failed":
                stages["audioRetention"] = "pending"
                stages["audioRetentionGeneration"] = int(stages.get("audioRetentionGeneration", 0)) + 1
                stages.pop("audioRetentionError", None)
            changed = conn.execute(text("UPDATE lecture_recordings SET preferences_json=:preferences,stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner AND status='completed'"), {
                "preferences": encoded(preferences), "stages": encoded(stages), "now": time.time(), "id": recording_id, "owner": owner,
            })
            if changed.rowcount != 1:
                raise LectureError("recording_changed", "The recording changed. Reload before removing audio.", 409)
        self._schedule_unretained_audio_removal(owner, recording_id)
        return self.status(owner, recording_id)

    def status(self, owner: str, recording_id: str):
        row = self._row(owner, recording_id)
        if row["status"] == "completed":
            self._schedule_unretained_audio_removal(owner, recording_id, row)
            row = self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            chunks = conn.execute(text("SELECT sequence_number,transcription_status,start_ms,end_ms FROM lecture_audio_chunks WHERE recording_id=:id ORDER BY sequence_number"), {"id": recording_id}).all()
            buddy=conn.execute(text('SELECT buddy_id FROM buddy_classes WHERE id=:id AND owner_id=:owner'),{'id':recording_id,'owner':owner}).scalar_one_or_none()
        expected = row["expected_chunk_count"]
        present = {chunk[0] for chunk in chunks}
        missing = [seq for seq in range(expected) if seq not in present] if expected is not None else []
        return {
            "id": row["id"], "noteId": row["note_id"], "title": row["title"], "courseId": row["course_id"],
            "buddyId":buddy,
            "recordingStatus": row["status"], "captureComplete": expected is not None,
            "captureInterrupted": bool(row["capture_interrupted"]),
            "durationMs": row["duration_ms"], "markersMs": json.loads(row["markers_json"]),
            "chunks": {"expected": expected, "serverConfirmed": len(chunks), "transcribed": sum(chunk[1] == "completed" for chunk in chunks), "failed": sum(chunk[1] == "failed" for chunk in chunks), "missing": missing},
            "stages": json.loads(row["stage_json"]), "preferences": self._preferences(row),
            "generationVersion": row["generation_version"], "pipelineVersion": row["pipeline_version"],
            "error": row["error"], "updatedAt": row["updated_at"],
        }

    def list_recordings(self, owner: str):
        with self.store.engine.connect() as conn:
            ids = conn.execute(text("SELECT id FROM lecture_recordings WHERE learner_id=:owner ORDER BY updated_at DESC LIMIT 100"), {"owner": owner}).scalars().all()
        return [self.status(owner, rid) for rid in ids]

    def chunks(self, owner: str, recording_id: str):
        self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT id,sequence_number,start_ms,end_ms,media_type,byte_count,sha256,transcription_status,transcription_attempts,transcription_error FROM lecture_audio_chunks WHERE recording_id=:id ORDER BY sequence_number"), {"id": recording_id}).mappings().all()
        return [{"id": row["id"], "sequenceNumber": row["sequence_number"], "startMs": row["start_ms"], "endMs": row["end_ms"], "mediaType": row["media_type"], "byteCount": row["byte_count"], "sha256": row["sha256"], "transcriptionStatus": row["transcription_status"], "transcriptionAttempts": row["transcription_attempts"], "error": row["transcription_error"]} for row in rows]

    def transcript(self, owner: str, recording_id: str):
        self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT id,chunk_id,start_ms,end_ms,speaker,speaker_confidence,raw_text,normalized_text,confidence,provider,model,transcription_version,normalization_version FROM lecture_transcript_segments WHERE recording_id=:id ORDER BY start_ms,chunk_id,ordinal"), {"id": recording_id}).mappings().all()
        return [{"id": row["id"], "chunkId": row["chunk_id"], "startMs": row["start_ms"], "endMs": row["end_ms"], "speaker": row["speaker"], "speakerConfidence": row["speaker_confidence"], "rawText": row["raw_text"], "normalizedText": row["normalized_text"], "confidence": row["confidence"], "provider": row["provider"], "model": row["model"], "transcriptionVersion": row["transcription_version"], "normalizationVersion": row["normalization_version"]} for row in rows]

    def sections(self, owner: str, recording_id: str):
        self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM lecture_sections WHERE recording_id=:id ORDER BY ordinal"), {"id": recording_id}).mappings().all()
        return [{"id": row["id"], "ordinal": row["ordinal"], "title": row["title"], "sectionType": row["section_type"], "summary": row["summary"], "startMs": row["start_ms"], "endMs": row["end_ms"], "evidence": json.loads(row["evidence_json"]), "confidence": row["confidence"], "analysisStatus": row["analysis_status"], "analysisVersion": row["analysis_version"]} for row in rows]

    def entities(self, owner: str, recording_id: str):
        self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM lecture_entities WHERE recording_id=:id ORDER BY section_id,id"), {"id": recording_id}).mappings().all()
        return [{"id": row["id"], "sectionId": row["section_id"], "kind": row["kind"], "title": row["title"], "content": row["content"], "spokenForm": row["spoken_form"], "latex": row["latex"], "evidence": json.loads(row["evidence_json"]), "confidence": row["confidence"], "sourceKind": row["source_kind"], "verificationStatus": row["verification_status"], "metadata": json.loads(row["metadata_json"]), "analysisVersion": row["analysis_version"]} for row in rows]

    def note_blocks(self, owner: str, recording_id: str):
        row = self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            blocks = conn.execute(text("SELECT * FROM lecture_note_blocks WHERE recording_id=:id AND generation_version=:version ORDER BY ordinal"), {"id": recording_id, "version": row["generation_version"]}).mappings().all()
        return {"generationVersion": row["generation_version"], "blocks": [{"id": block["id"], "sectionId": block["section_id"], "entityId": block["entity_id"], "ordinal": block["ordinal"], "blockType": block["block_type"], "title": block["title"], "content": block["content"], "evidence": json.loads(block["evidence_json"]), "sourceKind": block["source_kind"], "verificationStatus": block["verification_status"]} for block in blocks]}

    def chunk_audio_path(self, owner: str, recording_id: str, sequence: int):
        self._row(owner, recording_id)
        with self.store.engine.connect() as conn:
            chunk = conn.execute(text("SELECT storage_key,media_type FROM lecture_audio_chunks WHERE recording_id=:id AND sequence_number=:seq"), {"id": recording_id, "seq": sequence}).first()
        if not chunk:
            raise LectureError("chunk_not_found", "Audio slice not found.", 404)
        path = self.objects.path(owner, recording_id, chunk[0])
        if not path.is_file():
            raise LectureError("audio_removed", "Audio was removed according to this recording's retention setting.", 404)
        return path, chunk[1]

    def retry_stage(self, owner: str, recording_id: str, stage: str, section_id: str | None = None):
        self._row(owner, recording_id)
        if stage == "semantic_analysis":
            kind, key, payload = "lecture_segment", f"lecture:segment:{recording_id}", {"recording_id": recording_id}
        elif stage == "section_analysis" and section_id:
            with self.store.engine.connect() as conn:
                section = conn.execute(text("SELECT id FROM lecture_sections WHERE id=:section AND recording_id=:recording"), {"section": section_id, "recording": recording_id}).first()
            if not section:
                raise LectureError("section_not_found", "Lecture section not found.", 404)
            kind, key, payload = "lecture_section", f"lecture:section:{section_id}", {"recording_id": recording_id, "section_id": section_id}
        elif stage == "verification" and section_id:
            kind, key, payload = "lecture_verify", f"lecture:verify:{section_id}", {"recording_id": recording_id, "section_id": section_id}
        elif stage == "note_generation":
            row = self._row(owner, recording_id)
            version = row["generation_version"] + 1
            kind, key, payload = "lecture_generate", f"lecture:generate:{recording_id}:{version}", {"recording_id": recording_id, "version": version}
        else:
            raise LectureError("invalid_stage", "Choose a failed lecture stage to retry.")
        with self.store.transaction() as conn:
            conn.execute(text("UPDATE learning_jobs SET status='queued',lease=NULL,expires=NULL,result=NULL,attempt_count=0,next_retry_at=0,error_code=NULL,cancellation_requested=false WHERE owner_id=:owner AND command_key=:key AND status='failed'"), {"owner": owner, "key": key})
            if stage == "section_analysis":
                conn.execute(text("UPDATE lecture_sections SET analysis_status='pending' WHERE id=:id AND analysis_status='failed'"), {"id": section_id})
            conn.execute(text("UPDATE lecture_recordings SET status='processing',error=NULL,updated_at=:now WHERE id=:id AND learner_id=:owner AND status='failed'"), {"now": time.time(), "id": recording_id, "owner": owner})
        self.jobs.enqueue(owner, recording_id, kind, payload, key)
        return self.status(owner, recording_id)

    def retry_failed(self, owner: str, recording_id: str):
        self._row(owner, recording_id)
        with self.store.transaction() as conn:
            failed = conn.execute(text("SELECT id,kind,payload FROM learning_jobs WHERE owner_id=:owner AND target_id=:id AND kind LIKE 'lecture_%' AND status='failed'"), {"owner": owner, "id": recording_id}).mappings().all()
            for job in failed:
                payload = json.loads(job["payload"])
                if job["kind"] == "lecture_transcribe":
                    conn.execute(text("UPDATE lecture_audio_chunks SET transcription_status='pending',transcription_error=NULL WHERE recording_id=:id AND sequence_number=:seq AND transcription_status='failed'"), {"id": recording_id, "seq": payload["sequence"]})
                if job["kind"] == "lecture_section":
                    conn.execute(text("UPDATE lecture_sections SET analysis_status='pending' WHERE id=:id AND analysis_status='failed'"), {"id": payload["section_id"]})
                conn.execute(text("UPDATE learning_jobs SET status='queued',lease=NULL,expires=NULL,result=NULL,attempt_count=0,next_retry_at=0,error_code=NULL,cancellation_requested=false WHERE id=:id AND status='failed'"), {"id": job["id"]})
            if failed:
                conn.execute(text("UPDATE lecture_recordings SET status='processing',error=NULL,updated_at=:now WHERE id=:id AND learner_id=:owner AND status='failed'"), {"id": recording_id, "owner": owner, "now": time.time()})
        return self.status(owner, recording_id)

    def retry_chunk(self, owner: str, recording_id: str, sequence: int):
        self._row(owner, recording_id)
        key = f"lecture:chunk:{recording_id}:{sequence}"
        with self.store.transaction() as conn:
            row = conn.execute(text("SELECT id,transcription_status FROM lecture_audio_chunks WHERE recording_id=:id AND sequence_number=:seq"), {"id": recording_id, "seq": sequence}).first()
            if not row:
                raise LectureError("chunk_not_found", "Audio slice not found.", 404)
            if row[1] == "completed":
                return self.status(owner, recording_id)
            conn.execute(text("UPDATE lecture_audio_chunks SET transcription_status='pending',transcription_error=NULL,updated_at=:now WHERE id=:id"), {"now": time.time(), "id": row[0]})
            conn.execute(text("UPDATE learning_jobs SET status='queued',lease=NULL,expires=NULL,result=NULL,attempt_count=0,next_retry_at=0,error_code=NULL,cancellation_requested=false WHERE owner_id=:owner AND command_key=:key AND status='failed'"), {"owner": owner, "key": key})
        self.jobs.enqueue(owner, recording_id, "lecture_transcribe", {"recording_id": recording_id, "sequence": sequence}, key)
        return self.status(owner, recording_id)

    def regenerate(self, owner: str, recording_id: str, preferences: LecturePreferences):
        row = self._row(owner, recording_id)
        if row["status"] != "completed":
            raise LectureError("lecture_not_ready", "Finish lecture processing before changing note depth.", 409)
        preference_values = preferences.model_dump(mode="json", by_alias=True)
        if json.loads(row["stage_json"]).get("audioRetention") in {"pending", "removed", "failed"}:
            preference_values["keepAudio"] = False
        version = row["generation_version"] + 1
        stages = json.loads(row["stage_json"])
        stages["noteGeneration"] = "queued"
        stages["verification"] = "pending"
        with self.store.transaction() as conn:
            changed = conn.execute(text("UPDATE lecture_recordings SET status='processing',preferences_json=:prefs,stage_json=:stages,updated_at=:now WHERE id=:id AND learner_id=:owner AND status='completed' AND generation_version=:version"), {"prefs": encoded(preference_values), "stages": encoded(stages), "now": time.time(), "id": recording_id, "owner": owner, "version": row["generation_version"]})
            if changed.rowcount != 1:
                raise LectureError("recording_changed", "Recording changed; reload and try again.", 409)
            from .execution import Outbox
            Outbox.emit(conn, owner, "execution.job.requested", recording_id, f"lecture:generate:{recording_id}:{version}",
                        {"kind": "lecture_generate", "input": {"recording_id": recording_id, "version": version}, "key": f"lecture:generate:{recording_id}:{version}"})
        return self.status(owner, recording_id)

    def delete(self, owner: str, note_id: str):
        with self.store.transaction() as conn:
            rows = conn.execute(text("SELECT id FROM lecture_recordings WHERE learner_id=:owner AND note_id=:note"), {"owner": owner, "note": note_id}).all()
            for (rid,) in rows:
                class_id=conn.execute(text('SELECT id FROM class_sessions WHERE recording_id=:id AND owner_id=:owner'),{'id':rid,'owner':owner}).scalar_one_or_none()
                if class_id:
                    conn.execute(text("UPDATE learning_jobs SET status='cancelled',lease=NULL,expires=NULL,cancel_requested=true,cancellation_requested=true WHERE owner_id=:owner AND target_id=:id AND kind='class_specialist'"),{'owner':owner,'id':class_id})
                    conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND parent_id=:id AND kind='flashcard_deck'"),{'owner':owner,'id':class_id})
                from .flashcards.repository import Repository as FlashcardRepository
                fc=FlashcardRepository(self.store)
                for deck in fc.rows(conn,owner,'decks'):
                    if deck.get('classId')==class_id:
                        deck['status']='deleted';fc.put(conn,owner,'decks',deck)
                conn.execute(text('DELETE FROM buddy_classes WHERE id=:id AND owner_id=:owner'),{'id':rid,'owner':owner})
                conn.execute(text("UPDATE learning_jobs SET status='cancelled',lease=NULL,expires=NULL WHERE owner_id=:owner AND target_id=:id AND kind LIKE 'lecture_%'"), {"owner": owner, "id": rid})
                conn.execute(text("DELETE FROM execution_outbox WHERE owner_id=:owner AND target_id=:id"), {"owner": owner, "id": rid})
            chunks = conn.execute(text("SELECT c.storage_key,c.recording_id FROM lecture_audio_chunks c JOIN lecture_recordings r ON r.id=c.recording_id WHERE r.learner_id=:owner AND r.note_id=:note"), {"owner": owner, "note": note_id}).all()
            conn.execute(text("DELETE FROM lecture_recordings WHERE learner_id=:owner AND note_id=:note"), {"owner": owner, "note": note_id})
        for key, rid in chunks:
            self.objects.delete(owner, rid, key)
