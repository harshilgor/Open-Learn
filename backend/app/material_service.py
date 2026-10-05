"""Owner-scoped material ingestion and persistent worker leases.

The first parser handles text PDFs and UTF-8; scanned/image material is
explicitly marked needs_attention. No model is required for indexing.
"""
from __future__ import annotations
from contextlib import nullcontext
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text
from fastapi import HTTPException
from .storage import Store


def uid(prefix):
    return f"{prefix}_{uuid4().hex}"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def problem(code, message, status=422):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


class MaterialService:
    def __init__(self, store: Store):
        self.store = store
        self.root = Path(os.getenv("AI_TUTOR_MATERIAL_DIR", str(Path(__file__).resolve().parents[1] / "data" / "materials"))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        from .object_store import configured_objects
        self.objects=configured_objects(self.root)

    def object_path(self, key):
        if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
            problem("invalid_object", "Invalid object identifier")
        return self.root / key

    def version(self, owner, version_id, connection=None):
        def query(c):
            return c.execute(text("SELECT v.*, m.owner_id, m.title, m.role, m.course_id FROM material_versions v JOIN materials m ON m.id=v.material_id WHERE v.id=:id AND m.owner_id=:owner AND m.deleted=false"), {"id": version_id, "owner": owner}).mappings().first()
        if connection is not None:
            row = query(connection)
        else:
            with self.store.engine.connect() as c:
                row = query(c)
        if not row:
            problem("material_not_found", "Material is not available", 404)
        return dict(row)

    def create(self, owner, request, connection=None):
        mid, vid = uid("mat"), uid("matver")
        course_id = getattr(request, "course_id", None)
        with (nullcontext(connection) if connection is not None else self.store.transaction()) as c:
            c.execute(
                text("INSERT INTO materials(id,owner_id,title,role,deleted,course_id) VALUES(:id,:owner,:title,:role,false,:course_id)"),
                {"id": mid, "owner": owner, "title": request.title, "role": request.role, "course_id": course_id},
            )
            c.execute(
                text("INSERT INTO material_versions(id,material_id,version,object_key,media_type,byte_count,status,payload) VALUES(:id,:mid,1,:key,:media,:size,'uploaded',:payload)"),
                {"id": vid, "mid": mid, "key": uid("object"), "media": request.media_type, "size": request.byte_count, "payload": encoded({"issues": [], "parser": "text-v1"})},
            )
        return {"materialId": mid, "versionId": vid, "uploadPath": f"/v1/materials/{mid}/versions/{vid}/content", "status": "uploaded", "courseId": course_id}

    def upload(self, owner, mid, vid, content):
        v = self.version(owner, vid)
        if v["material_id"] != mid:
            problem("material_not_found", "Material is not available", 404)
        if len(content) != v["byte_count"] or len(content) > 50 * 1024 * 1024:
            problem("upload_size_mismatch", "Uploaded size does not match the declared file")
        digest = hashlib.sha256(content).hexdigest()
        if v["sha256"]:
            if v["sha256"] != digest:
                problem("immutable_version", "Create a new material for changed content", 409)
            return self.details(owner, mid)
        if v["media_type"] == "application/pdf":
            if not content.startswith(b"%PDF-"):
                problem("invalid_pdf", "The file is not a PDF")
        elif v["media_type"].startswith("image/"):
            signatures = {
                "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                "image/jpeg": content.startswith(b"\xff\xd8\xff"),
                "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
                "image/gif": content.startswith((b"GIF87a", b"GIF89a")),
            }
            if not signatures.get(v["media_type"], False):
                problem("invalid_image", "Uploaded bytes do not match the selected image format")
        else:
            try:
                decoded = content.decode("utf-8-sig")
                if "\x00" in decoded or not decoded.strip():
                    raise ValueError()
            except (UnicodeError, ValueError):
                problem("invalid_text", "Upload non-empty UTF-8 text")
        # Atomic exclusive version admission; simultaneous different bytes never
        # overwrite a committed version. Upload I/O is bounded to 50 MiB.
        with self.store.transaction() as c:
            self.version(owner, vid, c)
            changed = c.execute(text("UPDATE material_versions SET sha256=:hash WHERE id=:id AND sha256 IS NULL"), {"hash": digest, "id": vid}).rowcount
            if not changed:
                problem("upload_conflict", "Upload already completed; reload its status", 409)
            self.objects.put(v['object_key'],content)
            jid = uid("job")
            c.execute(text("INSERT INTO material_jobs(id,owner_id,kind,target_id,status,attempt,payload) VALUES(:id,:owner,'ingest',:target,'queued',0,'{}')"), {"id": jid, "owner": owner, "target": vid})
            c.execute(text("UPDATE material_versions SET status='queued' WHERE id=:id"), {"id": vid})
        return self.details(owner, mid)

    def details(self, owner, mid):
        with self.store.engine.connect() as c:
            rows = c.execute(text("SELECT v.id FROM material_versions v JOIN materials m ON m.id=v.material_id WHERE m.id=:id AND m.owner_id=:owner AND m.deleted=false ORDER BY v.version DESC"), {"id": mid, "owner": owner}).scalars().all()
            if not rows:
                problem("material_not_found", "Material is not available", 404)
            v = self.version(owner, rows[0], c)
            job = c.execute(text("SELECT id,status,payload FROM material_jobs WHERE target_id=:id AND kind='ingest'"), {"id": v["id"]}).mappings().first()
            mat_row = c.execute(text("SELECT course_id FROM materials WHERE id=:id"), {"id": mid}).mappings().first()
            course_id = mat_row["course_id"] if mat_row else None
        payload = json.loads(v["payload"])
        return {"id": mid, "title": v["title"], "role": v["role"], "courseId": course_id, "versionId": v["id"], "status": v["status"], "mediaType": v["media_type"], "byteCount": v["byte_count"], "jobId": job["id"] if job else None, **payload}

    def list(self, owner, course_id: str | None = None):
        with self.store.engine.connect() as c:
            query = "SELECT id FROM materials WHERE owner_id=:owner AND deleted=false"
            params = {"owner": owner}
            if course_id is not None:
                query += " AND course_id=:course_id"
                params["course_id"] = course_id
            query += " ORDER BY id DESC"
            ids = c.execute(text(query), params).scalars().all()
        return [self.details(owner, mid) for mid in ids]

    def session(self, owner, sid):
        session = self.store.get_session(sid)
        if session is None or session.learner_id != owner:
            problem("session_not_found", "Session is not available", 404)
        return session

    def attach(self, owner, sid, vid):
        self.session(owner, sid)
        self.version(owner, vid)
        with self.store.transaction() as c:
            if not c.execute(text("SELECT 1 FROM material_attachments WHERE session_id=:sid AND version_id=:vid"), {"sid": sid, "vid": vid}).first():
                c.execute(text("INSERT INTO material_attachments(session_id,version_id) VALUES(:sid,:vid)"), {"sid": sid, "vid": vid})
        return {"versionId": vid, "sessionId": sid}

    def attachments(self, owner, sid):
        session = self.session(owner, sid)
        with self.store.engine.connect() as c:
            ids = set(c.execute(text("SELECT a.version_id FROM material_attachments a JOIN material_versions v ON v.id=a.version_id JOIN materials m ON m.id=v.material_id WHERE a.session_id=:sid AND m.owner_id=:owner AND m.deleted=false"), {"sid": sid, "owner": owner}).scalars().all())
            # If session belongs to a course, automatically include ready versions of materials belonging to that course
            if getattr(session, "course_id", None):
                course_vids = c.execute(
                    text(
                        "SELECT v.id FROM material_versions v "
                        "JOIN materials m ON m.id=v.material_id "
                        "WHERE m.course_id=:cid AND m.owner_id=:owner AND m.deleted=false "
                        "AND v.status IN ('ready', 'partially_ready')"
                    ),
                    {"cid": session.course_id, "owner": owner},
                ).scalars().all()
                ids.update(course_vids)
        return list(ids)

    def image_context(self, owner, sid, *, max_images=4, byte_budget=20 * 1024 * 1024):
        from .model_provider import ImageInput
        images, used = [], 0
        for version_id in self.attachments(owner, sid):
            version = self.version(owner, version_id)
            if not version["media_type"].startswith("image/"):
                continue
            raw = self.objects.read(version["object_key"])
            if used + len(raw) > byte_budget:
                problem("image_context_too_large", "Attached images exceed the 20 MB vision context budget.", 413)
            images.append(ImageInput(media_type=version["media_type"], data=raw, title=version["title"]))
            used += len(raw)
            if len(images) == max_images:
                break
        return images

    def detach(self, owner, sid, vid):
        self.session(owner, sid)
        with self.store.transaction() as c:
            c.execute(text("DELETE FROM material_attachments WHERE session_id=:sid AND version_id=:vid"), {"sid": sid, "vid": vid})

    def blocks(self, owner, vid):
        self.version(owner, vid)
        with self.store.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM material_blocks WHERE version_id=:id ORDER BY ordinal"), {"id": vid}).mappings().all()
        return [{"id": r["id"], "versionId": vid, "pageIndex": r["page_index"], "kind": r["kind"], "text": r["text"], **json.loads(r["payload"])} for r in rows]

    def source(self, owner, span_id):
        with self.store.engine.connect() as c:
            row = c.execute(text("SELECT version_id FROM material_blocks WHERE id=:id"), {"id": span_id}).first()
        if not row:
            problem("source_not_found", "Source is not available", 404)
        return next(b for b in self.blocks(owner, row[0]) if b["id"] == span_id)

    def claim(self):
        now, lease = time.time(), uid("lease")
        with self.store.transaction() as c:
            suffix = " FOR UPDATE SKIP LOCKED" if c.dialect.name == "postgresql" else ""
            c.execute(text("UPDATE material_jobs SET status='failed',payload=:payload WHERE status='running' AND expires<:now AND attempt>=3"), {"now": now, "payload": encoded({"error": {"code": "attempts_exhausted", "message": "Worker recovery exhausted its attempt budget."}})})
            job = c.execute(text("SELECT * FROM material_jobs WHERE (status='queued' OR (status='running' AND expires<:now)) AND attempt<3 ORDER BY id LIMIT 1" + suffix), {"now": now}).mappings().first()
            if not job:
                return None
            changed = c.execute(text("UPDATE material_jobs SET status='running',attempt=attempt+1,lease=:lease,expires=:expires WHERE id=:id AND (status='queued' OR (status='running' AND expires<:now))"), {"lease": lease, "expires": now + 600, "id": job["id"], "now": now}).rowcount
            return {**job, "lease": lease} if changed else None

    def process_one(self):
        job = self.claim()
        if job is None:
            return False
        try:
            if job["kind"] == "ingest":
                self.ingest(job)
            else:
                problem("unsupported_job", "This worker only accepts ingestion jobs")
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else {"code": "processing_failed", "message": "Could not process this material. Check its format or retry."}
            with self.store.transaction() as c:
                changed = c.execute(text("UPDATE material_jobs SET status='failed',payload=:payload WHERE id=:id AND lease=:lease AND status='running' AND expires>:now"), {"now": time.time(), "id": job["id"], "lease": job["lease"], "payload": encoded({"error": detail})}).rowcount
                if changed and job["kind"] == "ingest":
                    c.execute(text("UPDATE material_versions SET status='failed',payload=:payload WHERE id=:id AND status NOT IN ('ready','deleted')"), {"id": job["target_id"], "payload": encoded({"issues": [detail]})})
        return True

    def ingest(self, job):
        v = self.version(job["owner_id"], job["target_id"])
        raw = self.objects.read(v["object_key"])
        pages = []
        issues = []
        if v["media_type"] == "application/pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 1000:
                problem("unsupported_pdf", "PDF must be unencrypted and at most 1,000 pages")
            for index, page in enumerate(reader.pages):
                # Never advertise OCR or visual understanding from text extraction.
                if page.get_contents() and len(page.get_contents().get_data()) > 10 * 1024 * 1024:
                    problem("page_too_large", "A PDF page exceeds the extraction budget")
                extracted = page.extract_text() or ""
                if len(extracted) > 200000:
                    problem("page_too_large", "A PDF page exceeds the text budget")
                pages.append(extracted)
        elif v["media_type"].startswith("image/"):
            issues.append({"pageIndex": 0, "message": "Image is ready for visual analysis by a vision-capable model. No searchable OCR text was produced."})
        else:
            pages = [raw.decode("utf-8-sig")]
        blocks = []
        total_chars = 0
        for index, page_text in enumerate(pages):
            total_chars += len(page_text)
            if total_chars > 5_000_000:
                problem("extraction_budget", "Extracted text exceeds the processing budget")
            if not page_text.strip():
                issues.append({"pageIndex": index, "message": "No readable text; OCR or visual review is required."})
                continue
            # Bounded passages preserve order and complete paragraph when possible.
            chunks = re.split(r"\n\s*\n", page_text)
            for chunk in chunks:
                chunk = chunk.strip()
                while chunk:
                    end = min(len(chunk), 3500)
                    if end < len(chunk):
                        boundary = chunk.rfind("\n", 0, end)
                        if boundary > 1000:
                            end = boundary
                    passage, chunk = chunk[:end], chunk[end:].strip()
                    blocks.append({"id": uid("span"), "page": index, "text": passage, "kind": "private_solution" if v["role"] == "answer_key" else "passage"})
        status = "ready" if v["media_type"].startswith("image/") else "partially_ready" if issues and blocks else "needs_attention" if not blocks else "ready"
        with self.store.transaction() as c:
            self.version(job["owner_id"], v["id"], c)
            changed = c.execute(text("UPDATE material_jobs SET status='completed',payload=:payload WHERE id=:id AND lease=:lease AND status='running' AND expires>:now"), {"now": time.time(), "id": job["id"], "lease": job["lease"], "payload": encoded({"blockCount": len(blocks), "issues": issues})}).rowcount
            if not changed:
                return
            c.execute(text("DELETE FROM material_blocks WHERE version_id=:id"), {"id": v["id"]})
            for ordinal, b in enumerate(blocks):
                c.execute(text("INSERT INTO material_blocks(id,version_id,page_index,ordinal,kind,text,payload) VALUES(:id,:vid,:page,:ordinal,:kind,:text,:payload)"), {**b, "vid": v["id"], "ordinal": ordinal, "payload": encoded({"extractionStatus": "text_extracted_not_layout_verified", "textHash": hashlib.sha256(b["text"].encode()).hexdigest()})})
            parser = "pypdf-text-v1" if v["media_type"] == "application/pdf" else "vision-context-v1" if v["media_type"].startswith("image/") else "utf8-v1"
            c.execute(text("UPDATE material_versions SET status=:status,payload=:payload WHERE id=:id"), {"id": v["id"], "status": status, "payload": encoded({"pageCount": len(pages), "blockCount": len(blocks), "issues": issues, "parser": parser, "searchMode": "lexical"})})

    def job(self, owner, jid):
        with self.store.engine.connect() as c:
            row = c.execute(text("SELECT * FROM material_jobs WHERE id=:id AND owner_id=:owner"), {"id": jid, "owner": owner}).mappings().first()
        if not row:
            problem("job_not_found", "Job is not available", 404)
        return {"id": row["id"], "status": row["status"], "kind": row["kind"], "targetId": row["target_id"], "attempt": row["attempt"], **json.loads(row["payload"])}

    def retry(self, owner, jid):
        self.job(owner, jid)
        with self.store.transaction() as c:
            changed = c.execute(text("UPDATE material_jobs SET status='queued',lease=NULL,expires=NULL WHERE id=:id AND status='failed' AND attempt<3"), {"id": jid}).rowcount
        if not changed:
            problem("retry_unavailable", "Job is not retryable or exhausted its attempt budget", 409)
        return self.job(owner, jid)

    def delete(self, owner, mid):
        self.details(owner, mid)
        with self.store.transaction() as c:
            versions = c.execute(text("SELECT id,object_key FROM material_versions WHERE material_id=:id"), {"id": mid}).mappings().all()
            from .agent_execution.research_sources import ResearchSources
            ResearchSources.erase_material_versions(c, owner, {v["id"] for v in versions})
            from .agent_execution.sandbox_inputs import erase_versions
            erase_versions(c,owner,{v['id'] for v in versions})
            c.execute(text("UPDATE materials SET deleted=true WHERE id=:id AND owner_id=:owner"), {"id": mid, "owner": owner})
            for v in versions:
                c.execute(text("DELETE FROM material_blocks WHERE version_id=:id"), {"id": v["id"]})
                c.execute(text("DELETE FROM material_attachments WHERE version_id=:id"), {"id": v["id"]})
                c.execute(text("UPDATE material_jobs SET status='cancelled' WHERE target_id=:id"), {"id": v["id"]})
                c.execute(text("UPDATE material_versions SET status='deleted',payload='{}' WHERE id=:id"), {"id": v["id"]})
        for v in versions:
            self.objects.delete(v["object_key"])
        return {"status": "deleted"}
