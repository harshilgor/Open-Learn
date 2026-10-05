"""Owner-scoped material ingestion and persistent worker leases.

Index text PDFs and UTF-8 directly; blank PDF pages may receive bounded OCR.
Image-only uploads remain available for vision analysis but are not searchable.
"""
from __future__ import annotations
from contextlib import nullcontext
import codecs
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text
from fastapi import HTTPException
from .storage import Store
from .material_models import MAX_DIRECT_MATERIAL_BYTES, MAX_MATERIAL_BYTES, MATERIAL_UPLOAD_CHUNK_BYTES


def uid(prefix):
    return f"{prefix}_{uuid4().hex}"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def problem(code, message, status=422):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _normalized_pdf_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _pdf_text_fragments(page, max_fragments=10000):
    """Return extracted text and coarse visitor rectangles for plain-text PDFs.

    pypdf's visitor coordinates depend on source transforms and font metrics, so
    these rectangles are evidence hints only. We deliberately fail closed for
    rotated pages or fragments whose text cannot be aligned with extracted text.
    """
    fragments = []
    collected_chars = 0
    try:
        crop = page.cropbox
        left, bottom, right, top = map(float, (crop.left, crop.bottom, crop.right, crop.top))
        width, height = right - left, top - bottom
        rotation = int(getattr(page, "rotation", 0) or 0) % 360
        if width <= 0 or height <= 0 or rotation:
            return page.extract_text() or "", [], 0

        def visitor(text_value, user_matrix, text_matrix, _font_dictionary, font_size):
            nonlocal collected_chars
            try:
                text_value = str(text_value or "")
                normalized = _normalized_pdf_text(text_value)
                if not normalized or len(fragments) >= max_fragments or collected_chars + len(text_value) > 200000:
                    return
                size = abs(float(font_size or 0))
                if size <= 0 or size > 1000 or len(user_matrix) < 6 or len(text_matrix) < 6:
                    return
                # Compose text-space origin with the current user-space matrix.
                x = float(user_matrix[0]) * float(text_matrix[4]) + float(user_matrix[2]) * float(text_matrix[5]) + float(user_matrix[4])
                y = float(user_matrix[1]) * float(text_matrix[4]) + float(user_matrix[3]) * float(text_matrix[5]) + float(user_matrix[5])
                lines = [line.strip() for line in text_value.splitlines() if line.strip()]
                if not lines:
                    lines = [text_value.strip()]
                for line_index, line in enumerate(lines):
                    line_norm = _normalized_pdf_text(line)
                    if not line_norm:
                        continue
                    line_y = y - line_index * size * 1.2
                    box_width = min(width, max(size * 0.45, len(line) * size * 0.48))
                    box_height = min(height, size * 1.25)
                    x0 = max(0.0, min(1.0, (x - left) / width))
                    x1 = max(0.0, min(1.0, (x + box_width - left) / width))
                    y0 = max(0.0, min(1.0, (top - (line_y + box_height)) / height))
                    y1 = max(0.0, min(1.0, (top - line_y) / height))
                    if x1 > x0 and y1 > y0:
                        fragments.append({"text": line_norm, "start": None, "end": None,
                                          "box": {"x": round(x0, 4), "y": round(y0, 4),
                                                  "width": round(x1 - x0, 4), "height": round(y1 - y0, 4)}})
                collected_chars += len(text_value)
            except Exception:
                # A broken coordinate callback must never make a readable PDF fail.
                return

        extracted = page.extract_text(visitor_text=visitor) or ""
    except Exception:
        return page.extract_text() or "", [], 0

    # Align callbacks monotonically against the actual extracted page text.
    # Unmatched or reordered fragments are omitted instead of guessed.
    normalized_page = _normalized_pdf_text(extracted)
    cursor = 0
    for fragment in fragments:
        start = normalized_page.find(fragment["text"], cursor)
        if start < 0:
            continue
        fragment["start"], fragment["end"] = start, start + len(fragment["text"])
        cursor = fragment["end"]
    return extracted, [fragment for fragment in fragments if fragment["start"] is not None], len(fragments)


def _outline_manifest(reader, page_labels, max_items=500, max_depth=10):
    outline = []
    try:
        nodes = reader.outline
    except Exception:
        return outline

    def visit(items, depth=0):
        if depth > max_depth or len(outline) >= max_items:
            return
        for item in items if isinstance(items, list) else []:
            if len(outline) >= max_items:
                return
            if isinstance(item, list):
                visit(item, depth + 1)
                continue
            try:
                title = str(getattr(item, "title", "") or "").strip()[:300]
                page_index = reader.get_page_number(item)
                if not title or page_index is None or page_index < 0 or page_index >= len(page_labels):
                    continue
                outline.append({"title": title, "pageIndex": int(page_index),
                                "pageLabel": page_labels[page_index], "depth": depth})
            except Exception:
                continue

    visit(nodes)
    return outline


def _ocr_pdf_pages(path, page_indices, *, max_edge=2400, max_pixels=4_000_000, timeout_seconds=12):
    """OCR a small set of blank-text pages, returning bounded text and regions."""
    import math
    import pypdfium2 as pdfium
    import pytesseract
    from pytesseract import Output

    output = {}
    with pdfium.PdfDocument(str(path)) as document:
        for page_index in page_indices:
            try:
                page = document[page_index]
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    output[page_index] = {"status": "failed"}
                    continue
                scale = min(1.5, max_edge / max(width, height), math.sqrt(max_pixels / (width * height)))
                image = page.render(scale=scale).to_pil().convert("RGB")
                data = pytesseract.image_to_data(image, lang="eng", config="--psm 6",
                                                  output_type=Output.DICT, timeout=timeout_seconds)
                lines = {}
                word_count = min(50000, len(data.get("text", [])))
                for word_index in range(word_count):
                    word = str(data["text"][word_index] or "").strip()
                    try:
                        confidence = float(data["conf"][word_index])
                    except (ValueError, TypeError, IndexError):
                        continue
                    if not word or confidence < 30:
                        continue
                    key = (data["block_num"][word_index], data["par_num"][word_index], data["line_num"][word_index])
                    try:
                        left = int(data["left"][word_index]); top = int(data["top"][word_index])
                        right = left + int(data["width"][word_index]); bottom = top + int(data["height"][word_index])
                    except (ValueError, TypeError, IndexError):
                        continue
                    line = lines.setdefault(key, {"words": [], "left": left, "top": top,
                                                  "right": right, "bottom": bottom,
                                                  "confidences": []})
                    line["words"].append(word)
                    line["left"] = min(line["left"], left); line["top"] = min(line["top"], top)
                    line["right"] = max(line["right"], right); line["bottom"] = max(line["bottom"], bottom)
                    line["confidences"].append(confidence)
                page_lines = []
                for line in list(lines.values())[:10000]:
                    text_value = " ".join(line["words"]).strip()
                    normalized = _normalized_pdf_text(text_value)
                    if not normalized:
                        continue
                    x0 = max(0.0, min(1.0, line["left"] / image.width))
                    y0 = max(0.0, min(1.0, line["top"] / image.height))
                    x1 = max(0.0, min(1.0, line["right"] / image.width))
                    y1 = max(0.0, min(1.0, line["bottom"] / image.height))
                    if x1 > x0 and y1 > y0:
                        page_lines.append({"text": normalized, "start": None, "end": None,
                                           "confidence": sum(line["confidences"]) / len(line["confidences"]),
                                           "box": {"x": round(x0, 4), "y": round(y0, 4),
                                                   "width": round(x1 - x0, 4), "height": round(y1 - y0, 4)}})
                extracted = "\n".join(" ".join(line["words"]) for line in lines.values()).strip()
                if len(extracted) > 200000:
                    extracted = extracted[:200000]
                normalized_page = _normalized_pdf_text(extracted)
                cursor = 0
                for fragment in page_lines:
                    start = normalized_page.find(fragment["text"], cursor)
                    if start < 0:
                        continue
                    fragment["start"], fragment["end"] = start, start + len(fragment["text"])
                    cursor = fragment["end"]
                page_lines = [fragment for fragment in page_lines if fragment["start"] is not None]
                confidence_values = [fragment["confidence"] for fragment in page_lines]
                average_confidence = round(sum(confidence_values) / len(confidence_values), 1) if confidence_values else None
                output[page_index] = {"status": "completed" if extracted else "no_text", "text": extracted,
                                      "fragments": page_lines[:10000], "confidence": average_confidence}
            except RuntimeError:
                output[page_index] = {"status": "timeout"}
            except Exception:
                output[page_index] = {"status": "failed"}
    return output


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
        return {"materialId": mid, "versionId": vid,
                "uploadPath": f"/v1/materials/{mid}/versions/{vid}/content",
                "resumableUploadPath": f"/v1/materials/{mid}/versions/{vid}/uploads",
                "status": "uploaded", "courseId": course_id}

    def upload(self, owner, mid, vid, content):
        # Preserve the byte-based API for small internal imports while sharing
        # validation and immutable admission with streamed browser uploads.
        with tempfile.NamedTemporaryFile(prefix="openlearn-material-", delete=False) as output:
            path = Path(output.name)
            output.write(content)
        try:
            return self.upload_file(owner, mid, vid, path)
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def digest_file(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _inspect_upload(path, version):
        byte_count = 0
        digest = hashlib.sha256()
        prefix = bytearray()
        media_type = version["media_type"]
        decoder = codecs.getincrementaldecoder("utf-8-sig")() if not (media_type == "application/pdf" or media_type.startswith("image/")) else None
        has_text = False
        try:
            with Path(path).open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    byte_count += len(chunk)
                    if byte_count > MAX_MATERIAL_BYTES or byte_count > version["byte_count"]:
                        problem("upload_size_mismatch", "Uploaded size does not match the declared file")
                    digest.update(chunk)
                    if len(prefix) < 12:
                        prefix.extend(chunk[:12 - len(prefix)])
                    if decoder is not None:
                        decoded = decoder.decode(chunk, final=False)
                        if "\x00" in decoded:
                            problem("invalid_text", "Upload non-empty UTF-8 text")
                        has_text = has_text or bool(decoded.strip())
                if decoder is not None:
                    decoded = decoder.decode(b"", final=True)
                    if "\x00" in decoded:
                        problem("invalid_text", "Upload non-empty UTF-8 text")
                    has_text = has_text or bool(decoded.strip())
        except UnicodeError:
            problem("invalid_text", "Upload non-empty UTF-8 text")
        if byte_count != version["byte_count"]:
            problem("upload_size_mismatch", "Uploaded size does not match the declared file")
        header = bytes(prefix)
        if media_type == "application/pdf":
            if not header.startswith(b"%PDF-"):
                problem("invalid_pdf", "The file is not a PDF")
        elif media_type.startswith("image/"):
            if byte_count > MAX_DIRECT_MATERIAL_BYTES:
                problem("image_too_large", "Images must be 50 MiB or smaller.")
            signatures = {
                "image/png": header.startswith(b"\x89PNG\r\n\x1a\n"),
                "image/jpeg": header.startswith(b"\xff\xd8\xff"),
                "image/webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
                "image/gif": header.startswith((b"GIF87a", b"GIF89a")),
            }
            if not signatures.get(media_type, False):
                problem("invalid_image", "Uploaded bytes do not match the selected image format")
        elif not has_text:
            problem("invalid_text", "Upload non-empty UTF-8 text")
        return byte_count, digest.hexdigest()

    def upload_file(self, owner, mid, vid, path):
        v = self.version(owner, vid)
        if v["material_id"] != mid:
            problem("material_not_found", "Material is not available", 404)
        byte_count, digest = self._inspect_upload(path, v)
        if v["sha256"]:
            if v["sha256"] != digest:
                problem("immutable_version", "Create a new material for changed content", 409)
            return self.details(owner, mid)
        # Atomic exclusive version admission; simultaneous different bytes never
        # overwrite a committed version. Request bytes are spooled to disk and
        # copied to object storage in bounded chunks.
        with self.store.transaction() as c:
            self.version(owner, vid, c)
            changed = c.execute(text("UPDATE material_versions SET sha256=:hash WHERE id=:id AND sha256 IS NULL"), {"hash": digest, "id": vid}).rowcount
            if not changed:
                problem("upload_conflict", "Upload already completed; reload its status", 409)
            put_file = getattr(self.objects, "put_file", None)
            if put_file is None:
                raise RuntimeError("Configured object storage does not support streamed material uploads")
            put_file(v['object_key'], Path(path), byte_count=byte_count, sha256=digest)
            jid = uid("job")
            c.execute(text("INSERT INTO material_jobs(id,owner_id,kind,target_id,status,attempt,payload) VALUES(:id,:owner,'ingest',:target,'queued',0,'{}')"), {"id": jid, "owner": owner, "target": vid})
            c.execute(text("UPDATE material_versions SET status='queued' WHERE id=:id"), {"id": vid})
        return self.details(owner, mid)

    def _upload_session_row(self, owner, upload_id, connection=None, lock=False):
        suffix = " FOR UPDATE" if lock and connection is not None and connection.dialect.name == "postgresql" else ""
        query = text(
            "SELECT u.*,v.object_key,v.sha256 AS version_sha256,m.title,m.role,m.deleted "
            "FROM material_upload_sessions u JOIN material_versions v ON v.id=u.version_id AND v.material_id=u.material_id "
            "JOIN materials m ON m.id=u.material_id "
            "WHERE u.id=:id AND u.owner_id=:owner AND m.owner_id=:owner AND m.deleted=false" + suffix
        )
        if connection is not None:
            row = connection.execute(query, {"id": upload_id, "owner": owner}).mappings().first()
        else:
            with self.store.engine.connect() as conn:
                row = conn.execute(query, {"id": upload_id, "owner": owner}).mappings().first()
        if not row:
            problem("upload_not_found", "This upload is unavailable.", 404)
        return dict(row)

    def _upload_session_receipt(self, row, connection=None):
        if connection is not None:
            parts = connection.execute(
                text("SELECT part_index FROM material_upload_parts WHERE version_id=:version ORDER BY part_index"),
                {"version": row["version_id"]},
            ).scalars().all()
        else:
            with self.store.engine.connect() as conn:
                parts = conn.execute(
                    text("SELECT part_index FROM material_upload_parts WHERE version_id=:version ORDER BY part_index"),
                    {"version": row["version_id"]},
                ).scalars().all()
        return {
            "uploadId": row["id"], "versionId": row["version_id"],
            "totalBytes": row["total_bytes"], "chunkBytes": row["chunk_bytes"],
            "chunkCount": row["chunk_count"], "receivedParts": list(parts),
            "status": row["status"], "expiresAt": row["expires_at"],
        }

    def create_upload_session(self, owner, mid, vid, *, class_context=None):
        version = self.version(owner, vid)
        if version["material_id"] != mid:
            problem("material_not_found", "Material is not available", 404)
        total = version["byte_count"]
        if total <= MAX_DIRECT_MATERIAL_BYTES:
            problem("resumable_upload_not_required", "Use the direct upload route for files up to 50 MiB.", 409)
        if version["media_type"].startswith("image/"):
            problem("image_too_large", "Images must be 50 MiB or smaller.")
        class_id, intake_id = class_context if class_context else (None, None)
        if bool(class_id) != bool(intake_id):
            problem("invalid_upload_context", "This class upload context is invalid.", 400)
        now = time.time()
        # Keep abandoned-part storage bounded without a separate maintenance worker.
        # The current version is excluded so its caller can resume after expiry.
        expired_keys = []
        with self.store.transaction() as conn:
            expired = conn.execute(text(
                "SELECT version_id FROM material_upload_sessions "
                "WHERE expires_at<:now AND (status IN ('open','completed') OR (status='assembling' AND lease_expires<:now)) AND version_id<>:version "
                "ORDER BY expires_at LIMIT 20"
            ), {"now": now, "version": vid}).scalars().all()
            for expired_version in expired:
                expired_keys.extend(conn.execute(
                    text("SELECT object_key FROM material_upload_parts WHERE version_id=:version"),
                    {"version": expired_version},
                ).scalars().all())
                conn.execute(text("DELETE FROM material_upload_sessions WHERE version_id=:version"), {"version": expired_version})
            row = conn.execute(text(
                "SELECT * FROM material_upload_sessions WHERE version_id=:version"
                + (" FOR UPDATE" if conn.dialect.name == "postgresql" else "")
            ), {"version": vid}).mappings().first()
            if row is None:
                if version["sha256"]:
                    problem("material_already_uploaded", "This material version already has content.", 409)
                upload_id = uid("matup")
                chunk_count = (total + MATERIAL_UPLOAD_CHUNK_BYTES - 1) // MATERIAL_UPLOAD_CHUNK_BYTES
                conn.execute(text(
                    "INSERT INTO material_upload_sessions(id,owner_id,material_id,version_id,class_id,intake_id,total_bytes,chunk_bytes,"
                    "chunk_count,status,expires_at,created_at) VALUES(:id,:owner,:material,:version,:class,:intake,:total,:chunk,:count,'open',:expiry,:now)"
                ), {"id": upload_id, "owner": owner, "material": mid, "version": vid, "class": class_id, "intake": intake_id, "total": total,
                    "chunk": MATERIAL_UPLOAD_CHUNK_BYTES, "count": chunk_count, "expiry": now + 86400, "now": now})
            else:
                if (row["owner_id"] != owner or row["material_id"] != mid or row["total_bytes"] != total
                        or row["class_id"] != class_id or row["intake_id"] != intake_id):
                    problem("upload_conflict", "This material version already has a different upload session.", 409)
                upload_id = row["id"]
                if row["status"] == "assembling" and (row["lease_expires"] or 0) > now and not version["sha256"]:
                    pass
                elif row["status"] != "completed":
                    conn.execute(text(
                        "UPDATE material_upload_sessions SET status='open',lease_token=NULL,lease_expires=NULL,expires_at=:expiry WHERE id=:id"
                    ), {"expiry": now + 86400, "id": upload_id})
            result = conn.execute(text("SELECT * FROM material_upload_sessions WHERE id=:id"), {"id": upload_id}).mappings().one()
            receipt = self._upload_session_receipt(dict(result), conn)
        for key in expired_keys:
            try:
                self.objects.delete(key)
            except Exception:
                pass
        return receipt

    def upload_session(self, owner, upload_id):
        row = self._upload_session_row(owner, upload_id)
        return self._upload_session_receipt(row)

    def expected_upload_part_bytes(self, owner, upload_id, part_index):
        row = self._upload_session_row(owner, upload_id)
        if part_index < 0 or part_index >= row["chunk_count"]:
            problem("invalid_upload_part", "This upload part number is invalid.", 404)
        return min(row["chunk_bytes"], row["total_bytes"] - part_index * row["chunk_bytes"])

    def upload_part(self, owner, upload_id, part_index, path, *, class_context=None):
        row = self._upload_session_row(owner, upload_id)
        if part_index < 0 or part_index >= row["chunk_count"]:
            problem("invalid_upload_part", "This upload part number is invalid.", 404)
        expected_bytes = min(row["chunk_bytes"], row["total_bytes"] - part_index * row["chunk_bytes"])
        byte_count, digest = self._inspect_upload_part(path)
        if byte_count != expected_bytes:
            problem("upload_part_size_mismatch", "This upload part has the wrong size.")
        now = time.time()
        object_key = f"material-uploads/{upload_id}/part-{part_index}"
        with self.store.transaction() as conn:
            current = self._upload_session_row(owner, upload_id, conn, lock=True)
            if (current.get("class_id"), current.get("intake_id")) != (class_context or (None, None)):
                problem("upload_not_found", "This upload is unavailable.", 404)
            existing = conn.execute(text(
                "SELECT byte_count,sha256 FROM material_upload_parts WHERE version_id=:version AND part_index=:part"
            ), {"version": current["version_id"], "part": part_index}).mappings().first()
            if existing:
                if existing["byte_count"] != byte_count or existing["sha256"] != digest:
                    problem("upload_part_conflict", "This part number was already uploaded with different bytes.", 409)
                if current["status"] == "open" and current["expires_at"] >= now:
                    self.objects.put_file(object_key, Path(path), byte_count=byte_count, sha256=digest)
                return self._upload_session_receipt(current, conn)
            if current["status"] != "open" or current["expires_at"] < now:
                problem("upload_not_writable", "Resume this upload before sending more parts.", 409)
            self.objects.put_file(object_key, Path(path), byte_count=byte_count, sha256=digest)
            conn.execute(text(
                "INSERT INTO material_upload_parts(version_id,part_index,object_key,byte_count,sha256,created_at) "
                "VALUES(:version,:part,:key,:bytes,:hash,:now)"
            ), {"version": current["version_id"], "part": part_index, "key": object_key,
                "bytes": byte_count, "hash": digest, "now": now})
            conn.execute(text("UPDATE material_upload_sessions SET expires_at=:expiry WHERE id=:id AND status='open'"),
                         {"expiry": now + 86400, "id": upload_id})
            refreshed = self._upload_session_row(owner, upload_id, conn)
            return self._upload_session_receipt(refreshed, conn)

    @staticmethod
    def _inspect_upload_part(path):
        digest = hashlib.sha256()
        size = 0
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def complete_upload(self, owner, upload_id, completion=None, *, class_context=None):
        now = time.time()
        lease = uuid4().hex
        completed_material_id = None
        with self.store.transaction() as conn:
            row = self._upload_session_row(owner, upload_id, conn, lock=True)
            if (row.get("class_id"), row.get("intake_id")) != (class_context or (None, None)):
                problem("upload_not_found", "This upload is unavailable.", 404)
            if row["status"] == "completed":
                completed_material_id = row["material_id"]
            else:
                if row["status"] == "assembling" and (row["lease_expires"] or 0) > now and not row.get("version_sha256"):
                    problem("upload_in_progress", "This upload is already being finalized.", 409)
                if row["expires_at"] < now:
                    problem("upload_expired", "Resume this upload before finalizing it.", 409)
                parts = conn.execute(text(
                    "SELECT part_index,object_key,byte_count FROM material_upload_parts WHERE version_id=:version ORDER BY part_index"
                ), {"version": row["version_id"]}).mappings().all()
                if len(parts) != row["chunk_count"] or [part["part_index"] for part in parts] != list(range(row["chunk_count"])):
                    problem("upload_parts_missing", "Upload all remaining parts before finalizing.", 409)
                changed = conn.execute(text(
                    "UPDATE material_upload_sessions SET status='assembling',lease_token=:lease,lease_expires=:expiry "
                    "WHERE id=:id AND (status='open' OR (status='assembling' AND (lease_expires<:now OR :committed=true)))"
                ), {"lease": lease, "expiry": now + 1800, "id": upload_id, "now": now,
                    "committed": bool(row.get("version_sha256"))}).rowcount
                if not changed:
                    problem("upload_in_progress", "This upload is already being finalized.", 409)
                material = {**row, "parts": [dict(part) for part in parts]}
        if completed_material_id:
            return self.details(owner, completed_material_id)
        path = None
        keys = [part["object_key"] for part in material["parts"]]
        try:
            with tempfile.NamedTemporaryFile(prefix="openlearn-assembled-material-", delete=False) as output:
                path = Path(output.name)
                total = 0
                for part in material["parts"]:
                    total += self.objects.stream_to(part["object_key"], output)
                output.flush()
                os.fsync(output.fileno())
            if total != material["total_bytes"]:
                problem("upload_assembly_mismatch", "The assembled upload has the wrong size.")
            if completion:
                result = completion(material, path)
            else:
                result = self.upload_file(owner, material["material_id"], material["version_id"], path)
            with self.store.transaction() as conn:
                changed = conn.execute(text(
                    "UPDATE material_upload_sessions SET status='completed',lease_token=NULL,lease_expires=NULL,completed_at=:now "
                    "WHERE id=:id AND status='assembling' AND lease_token=:lease"
                ), {"now": time.time(), "id": upload_id, "lease": lease}).rowcount
                if not changed:
                    problem("upload_lease_lost", "This upload must be resumed before finalizing it.", 409)
                conn.execute(text("DELETE FROM material_upload_parts WHERE version_id=:version"), {"version": material["version_id"]})
            for key in keys:
                try:
                    self.objects.delete(key)
                except Exception:
                    # The completed ledger no longer references these parts;
                    # a storage cleanup failure must not make completion fail.
                    pass
            return result
        except Exception:
            with self.store.transaction() as conn:
                conn.execute(text(
                    "UPDATE material_upload_sessions SET status='open',lease_token=NULL,lease_expires=NULL "
                    "WHERE id=:id AND status='assembling' AND lease_token=:lease"
                ), {"id": upload_id, "lease": lease})
            raise
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

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
        # Keep material-library listings compact. Detailed PDF page labels,
        # bookmarks, and OCR per-page records are fetched only by the class
        # reference manifest endpoint when a student opens that PDF.
        public_payload = {key: value for key, value in payload.items()
                          if key not in {"pageLabels", "outline", "ocrPages"}}
        return {"id": mid, "title": v["title"], "role": v["role"], "courseId": course_id, "versionId": v["id"], "revision": v["version"], "status": v["status"], "mediaType": v["media_type"], "byteCount": v["byte_count"], "jobId": job["id"] if job else None, **public_payload}

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
            inserted=False
            if not c.execute(text("SELECT 1 FROM material_attachments WHERE session_id=:sid AND version_id=:vid"), {"sid": sid, "vid": vid}).first():
                c.execute(text("INSERT INTO material_attachments(session_id,version_id) VALUES(:sid,:vid)"), {"sid": sid, "vid": vid})
                inserted=True
            if inserted:
                from .in_class_service import invalidate_material_access
                invalidate_material_access(c,session_id=sid,owner=owner)
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
            removed=c.execute(text("DELETE FROM material_attachments WHERE session_id=:sid AND version_id=:vid"), {"sid": sid, "vid": vid}).rowcount
            if removed:
                from .in_class_service import invalidate_material_access
                invalidate_material_access(c,session_id=sid,owner=owner)

    def blocks(self, owner, vid):
        self.version(owner, vid)
        with self.store.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM material_blocks WHERE version_id=:id ORDER BY ordinal"), {"id": vid}).mappings().all()
        return [{"id": r["id"], "versionId": vid, "pageIndex": r["page_index"], "kind": r["kind"], "text": r["text"], **json.loads(r["payload"])} for r in rows]

    def pdf_manifest(self, owner, vid, version=None):
        version = version or self.version(owner, vid)
        if version["media_type"] != "application/pdf" or version["status"] not in {"ready", "partially_ready"}:
            problem("pdf_unavailable", "This PDF reference is not available.", 404)
        payload = json.loads(version["payload"] or "{}")
        page_count = max(0, min(1000, int(payload.get("pageCount", 0) or 0)))
        labels = payload.get("pageLabels")
        if not isinstance(labels, list) or len(labels) != page_count:
            labels = [str(index + 1) for index in range(page_count)]
        labels = [str(label)[:64] or str(index + 1) for index, label in enumerate(labels)]
        outline = payload.get("outline")
        if not isinstance(outline, list):
            outline = []
        ocr_status = payload.get("ocrStatus")
        if ocr_status not in {"not_needed", "complete", "partial", "disabled", "no_text", "unavailable"}:
            ocr_status = "not_needed"
        ocr_deferred = max(0, min(1000, int(payload.get("ocrDeferredPageCount", 0) or 0)))
        from .material_index import MaterialIndexService
        return {"versionId": vid, "pageCount": page_count, "pageLabels": labels,
                "outline": outline[:500], "outlineStatus": "available" if outline else "empty",
                "ocrStatus": ocr_status, "ocrDeferredPageCount": ocr_deferred,
                "indexProgress": MaterialIndexService(self.store).progress(owner, vid)}

    def source(self, owner, span_id):
        with self.store.engine.connect() as c:
            row = c.execute(text("SELECT * FROM material_blocks WHERE id=:id"), {"id": span_id}).mappings().first()
        if not row:
            problem("source_not_found", "Source is not available", 404)
        self.version(owner, row['version_id'])
        return {'id':row['id'],'versionId':row['version_id'],'pageIndex':row['page_index'],
                'kind':row['kind'],'text':row['text'],**json.loads(row['payload'])}

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
            from .material_index import MaterialIndexService
            return MaterialIndexService(self.store).process_one()
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

    @staticmethod
    def _read_text_file(path, max_chars=5_000_000):
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        pieces = []
        char_count = 0
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                decoded = decoder.decode(chunk, final=False)
                char_count += len(decoded)
                if char_count > max_chars:
                    problem("extraction_budget", "Extracted text exceeds the processing budget")
                pieces.append(decoded)
            decoded = decoder.decode(b"", final=True)
            char_count += len(decoded)
            if char_count > max_chars:
                problem("extraction_budget", "Extracted text exceeds the processing budget")
            pieces.append(decoded)
        return "".join(pieces)

    def ingest(self, job):
        v = self.version(job["owner_id"], job["target_id"])
        pages = []
        page_labels = []
        page_fragments = []
        page_ocr = []
        page_layout = []
        remaining_geometry_fragments = 20000
        outline = []
        ocr_enabled = os.getenv("OPENLEARN_OCR_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
        ocr_deferred_pages = 0
        issues = []
        layout_document = None
        with tempfile.NamedTemporaryFile(prefix="openlearn-material-index-", delete=False) as downloaded:
            raw_path = Path(downloaded.name)
        try:
            download = getattr(self.objects, "download_to_file", None)
            if download is None:
                raw_path.write_bytes(self.objects.read(v["object_key"]))
            else:
                downloaded_bytes = download(v["object_key"], raw_path)
                if downloaded_bytes != v["byte_count"]:
                    problem("object_integrity", "Stored material length does not match its manifest.", 500)
            if self.digest_file(raw_path) != v["sha256"]:
                problem("object_integrity", "Stored material checksum does not match its manifest.", 500)
            if v["media_type"] == "application/pdf":
                try:
                    from pypdf import PdfReader
                except ImportError:
                    PdfReader = None
                try:
                    import fitz
                    layout_document = fitz.open(raw_path)
                except (ImportError, RuntimeError):
                    pass
                with raw_path.open("rb") as source:
                    if PdfReader is not None:
                        reader = PdfReader(source)
                    elif layout_document is not None:
                        from .material_index import FitzReader
                        reader = FitzReader(layout_document)
                    else:
                        problem('pdf_parser_unavailable', 'Install the configured PDF parser to process this file.', 503)
                    if reader.is_encrypted or len(reader.pages) > 1000:
                        problem("unsupported_pdf", "PDF must be unencrypted and at most 1,000 pages")
                    try:
                        candidate_labels = list(reader.page_labels)
                    except Exception:
                        candidate_labels = []
                    if len(candidate_labels) != len(reader.pages):
                        candidate_labels = [str(index + 1) for index in range(len(reader.pages))]
                    page_labels = [str(label or index + 1)[:64] for index, label in enumerate(candidate_labels)]
                    outline = _outline_manifest(reader, page_labels)
                    for index, page in enumerate(reader.pages):
                        from .material_index import MaterialIndexService
                        index_service = MaterialIndexService(self.store)
                        saved = index_service.checkpoint(v, index)
                        if saved:
                            pages.append(saved['text'])
                            page_fragments.append(saved['fragments'])
                            page_layout.append(saved['layout'])
                            page_ocr.append(None)
                            remaining_geometry_fragments = max(0, remaining_geometry_fragments-len(saved['fragments']))
                            continue
                        # Keep embedded text extraction distinct from the bounded OCR pass below.
                        if page.get_contents() and len(page.get_contents().get_data()) > 10 * 1024 * 1024:
                            problem("page_too_large", "A PDF page exceeds the extraction budget")
                        extracted, fragments, geometry_fragments_used = _pdf_text_fragments(page, max_fragments=remaining_geometry_fragments)
                        from .material_index import pdf_layout
                        layout, measured = pdf_layout(raw_path, index, document=layout_document)
                        page_layout.append(layout)
                        if measured:
                            normalized = _normalized_pdf_text(extracted)
                            cursor = 0
                            aligned = []
                            for fragment in measured[:remaining_geometry_fragments]:
                                value = _normalized_pdf_text(fragment['text'])
                                start = normalized.find(value, cursor)
                                if start >= 0:
                                    aligned.append({**fragment, 'start': start, 'end': start+len(value)})
                                    cursor = start+len(value)
                            if aligned:
                                fragments = aligned
                        remaining_geometry_fragments -= geometry_fragments_used
                        if len(extracted) > 200000:
                            problem("page_too_large", "A PDF page exceeds the text budget")
                        index_service.checkpoint(v, index, {'text': extracted, 'fragments': fragments, 'layout': layout}, job)
                        pages.append(extracted)
                        page_fragments.append(fragments)
                        page_ocr.append(None)
                    blank_pages = [index for index, page_text in enumerate(pages) if not page_text.strip()]
                    if blank_pages and ocr_enabled:
                        selected_pages = blank_pages[:20]
                        ocr_deferred_pages = max(0, len(blank_pages) - len(selected_pages))
                        try:
                            ocr_results = _ocr_pdf_pages(raw_path, selected_pages)
                        except Exception:
                            ocr_results = {index: {"status": "unavailable"} for index in selected_pages}
                        for index in selected_pages:
                            result = ocr_results.get(index, {"status": "failed"})
                            page_ocr[index] = {"status": result.get("status", "failed"),
                                               "confidence": result.get("confidence"),
                                               "recognizedChars": len(result.get("text", ""))}
                            if result.get("status") == "completed" and result.get("text", "").strip():
                                pages[index] = result["text"]
                                page_fragments[index] = result.get("fragments", [])
                            elif result.get("status") == "completed":
                                page_ocr[index]["status"] = "no_text"
                        for index in blank_pages[len(selected_pages):]:
                            page_ocr[index] = {"status": "skipped_budget", "confidence": None, "recognizedChars": 0}
                    elif blank_pages:
                        for index in blank_pages:
                            page_ocr[index] = {"status": "disabled", "confidence": None, "recognizedChars": 0}
            elif v["media_type"].startswith("image/"):
                issues.append({"pageIndex": 0, "message": "Image is ready for visual analysis by a vision-capable model. No searchable OCR text was produced."})
            else:
                pages = [self._read_text_file(raw_path)]
        finally:
            if layout_document is not None:
                layout_document.close()
            raw_path.unlink(missing_ok=True)
        blocks = []
        total_chars = 0
        for index, page_text in enumerate(pages):
            total_chars += len(page_text)
            if total_chars > 5_000_000:
                problem("extraction_budget", "Extracted text exceeds the processing budget")
            if not page_text.strip():
                ocr_status = page_ocr[index]["status"] if index < len(page_ocr) and page_ocr[index] else "not_attempted"
                issues.append({"pageIndex": index, "message": f"No readable text; OCR status: {ocr_status}. Visual review may be required."})
                continue
            if index < len(page_ocr) and page_ocr[index] and page_ocr[index].get("status") == "completed" and (page_ocr[index].get("confidence") or 0) < 45:
                issues.append({"pageIndex": index, "message": "OCR confidence is low; verify this passage against the original page."})
            # Bounded passages preserve order and complete paragraph when possible.
            chunks = re.split(r"\n\s*\n", page_text)
            normalized_page = _normalized_pdf_text(page_text)
            passage_cursor = 0
            fragments = page_fragments[index] if index < len(page_fragments) else []
            for chunk in chunks:
                chunk = chunk.strip()
                while chunk:
                    end = min(len(chunk), 3500)
                    if end < len(chunk):
                        boundary = chunk.rfind("\n", 0, end)
                        if boundary > 1000:
                            end = boundary
                    passage, chunk = chunk[:end], chunk[end:].strip()
                    normalized_passage = _normalized_pdf_text(passage)
                    passage_start = normalized_page.find(normalized_passage, passage_cursor) if normalized_passage else -1
                    passage_end = passage_start + len(normalized_passage) if passage_start >= 0 else -1
                    if passage_end >= 0:
                        passage_cursor = passage_end
                    regions = []
                    region_confidences = []
                    if passage_start >= 0:
                        for fragment in fragments:
                            if fragment["start"] < passage_end and fragment["end"] > passage_start:
                                region = dict(fragment["box"])
                                if fragment.get('quad'):
                                    region['quad'] = fragment['quad']
                                if fragment.get("confidence") is not None:
                                    region["confidence"] = round(float(fragment["confidence"]), 1)
                                    region_confidences.append(float(fragment["confidence"]))
                                regions.append(region)
                                if len(regions) >= 12:
                                    break
                    is_ocr = index < len(page_ocr) and page_ocr[index] and page_ocr[index].get("status") == "completed"
                    measured = not is_ocr and index < len(page_layout) and page_layout[index].get('geometryStatus') == 'measured' and any(region.get('quad') for region in regions)
                    geometry = {"status": "measured" if measured else "estimated" if regions else "unavailable",
                                "coordinateSpace": "normalized_rendered_page_top_left" if is_ocr or measured else "normalized_cropbox_top_left",
                                "pageSpace": page_layout[index] if measured else None,
                                "confidence": "tesseract_line_boxes" if region_confidences else "coarse_font_metrics", "regions": regions}
                    from .material_index import stable
                    blocks.append({"id": stable(v["id"], index, len(blocks), hashlib.sha256(passage.encode()).hexdigest()), "page": index, "pageLabel": page_labels[index] if index < len(page_labels) else str(index + 1),
                                   "geometry": geometry, "extractionStatus": "ocr_extracted_estimated" if is_ocr else "text_extracted_not_layout_verified",
                                   "ocrConfidence": round(sum(region_confidences) / len(region_confidences), 1) if region_confidences else None,
                                   "text": passage,
                                   "kind": "private_solution" if v["role"] == "answer_key" else "passage"})
        status = "ready" if v["media_type"].startswith("image/") else "partially_ready" if issues and blocks else "needs_attention" if not blocks else "ready"
        with self.store.transaction() as c:
            self.version(job["owner_id"], v["id"], c)
            changed = c.execute(text("UPDATE material_jobs SET status='completed',payload=:payload WHERE id=:id AND lease=:lease AND status='running' AND expires>:now"), {"now": time.time(), "id": job["id"], "lease": job["lease"], "payload": encoded({"blockCount": len(blocks), "issues": issues})}).rowcount
            if not changed:
                return
            from .material_index import MaterialIndexService
            MaterialIndexService(self.store).erase(c, v["id"])
            c.execute(text("DELETE FROM material_blocks WHERE version_id=:id"), {"id": v["id"]})
            for ordinal, b in enumerate(blocks):
                c.execute(text("INSERT INTO material_blocks(id,version_id,page_index,ordinal,kind,text,payload) VALUES(:id,:vid,:page,:ordinal,:kind,:text,:payload)"), {"id": b["id"], "vid": v["id"], "page": b["page"], "ordinal": ordinal, "kind": b["kind"], "text": b["text"], "payload": encoded({"extractionStatus": b["extractionStatus"], "textHash": hashlib.sha256(b["text"].encode()).hexdigest(), "pageLabel": b.get("pageLabel"), "geometry": b.get("geometry"), "ocrConfidence": b.get("ocrConfidence")})})
            parser = "pypdf-text-v1" if v["media_type"] == "application/pdf" else "vision-context-v1" if v["media_type"].startswith("image/") else "utf8-v1"
            version_payload = {"pageCount": len(pages), "blockCount": len(blocks), "issues": issues, "parser": parser, "searchMode": "lexical"}
            if v["media_type"] == "application/pdf":
                attempted_ocr = [item for item in page_ocr if item]
                completed_ocr = sum(1 for item in attempted_ocr if item.get("status") == "completed")
                if not any(not page_text.strip() for page_text in pages):
                    ocr_status = "not_needed"
                elif attempted_ocr and all(item.get("status") == "disabled" for item in attempted_ocr):
                    ocr_status = "disabled"
                elif completed_ocr == len(attempted_ocr) and attempted_ocr and not ocr_deferred_pages:
                    ocr_status = "complete"
                elif completed_ocr or ocr_deferred_pages:
                    ocr_status = "partial"
                elif any(item.get("status") in {"unavailable", "failed", "timeout"} for item in attempted_ocr):
                    ocr_status = "unavailable"
                elif any(item.get("status") == "no_text" for item in attempted_ocr):
                    ocr_status = "no_text"
                else:
                    ocr_status = "unavailable"
                version_payload.update({"ocrStatus": ocr_status,
                                        "ocrPages": [{"pageIndex": index, **item} for index, item in enumerate(page_ocr) if item][:20],
                                        "ocrDeferredPageCount": ocr_deferred_pages})
                version_payload.update({"pageLabels": page_labels, "outline": outline,
                                        "outlineStatus": "available" if outline else "empty",
                                        "geometryStatus": "estimated" if any(block["geometry"]["regions"] for block in blocks) else "unavailable"})
            c.execute(text("UPDATE material_versions SET status=:status,payload=:payload WHERE id=:id"), {"id": v["id"], "status": status, "payload": encoded(version_payload)})
            from .material_index import MaterialIndexService
            MaterialIndexService(self.store).publish(c, v, pages, page_labels, outline, page_ocr, page_layout)

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
        upload_objects = []
        with self.store.transaction() as c:
            versions = c.execute(text("SELECT id,object_key FROM material_versions WHERE material_id=:id"), {"id": mid}).mappings().all()
            course_id=c.execute(text("SELECT course_id FROM materials WHERE id=:id AND owner_id=:owner"),{"id":mid,"owner":owner}).scalar_one_or_none()
            affected_sessions=set(c.execute(text("SELECT DISTINCT session_id FROM material_attachments WHERE version_id IN (SELECT id FROM material_versions WHERE material_id=:id)"),{"id":mid}).scalars().all())
            upload_objects = c.execute(text(
                "SELECT p.object_key FROM material_upload_parts p JOIN material_upload_sessions u ON u.version_id=p.version_id WHERE u.material_id=:id"
            ), {"id": mid}).scalars().all()
            c.execute(text("DELETE FROM material_upload_sessions WHERE material_id=:id"), {"id": mid})
            from .agent_execution.research_sources import ResearchSources
            ResearchSources.erase_material_versions(c, owner, {v["id"] for v in versions})
            from .agent_execution.sandbox_inputs import erase_versions
            erase_versions(c,owner,{v['id'] for v in versions})
            c.execute(text("UPDATE materials SET deleted=true WHERE id=:id AND owner_id=:owner"), {"id": mid, "owner": owner})
            from .flashcards.class_adapter import invalidate_source
            for v in versions:
                invalidate_source(self.store,c,owner,v["id"])
                from .material_index import MaterialIndexService
                MaterialIndexService(self.store).erase(c, v['id'])
                c.execute(text("DELETE FROM material_blocks WHERE version_id=:id"), {"id": v["id"]})
                c.execute(text("DELETE FROM material_attachments WHERE version_id=:id"), {"id": v["id"]})
                c.execute(text("UPDATE material_jobs SET status='cancelled' WHERE target_id=:id"), {"id": v["id"]})
                c.execute(text("UPDATE material_versions SET status='deleted',payload='{}' WHERE id=:id"), {"id": v["id"]})
            from .in_class_service import invalidate_material_access
            for session_id in affected_sessions:
                invalidate_material_access(c,session_id=session_id,owner=owner)
            if course_id:
                invalidate_material_access(c,course_id=course_id,owner=owner)
        for v in versions:
            self.objects.delete(v["object_key"])
        for key in upload_objects:
            try:
                self.objects.delete(key)
            except Exception:
                pass
        return {"status": "deleted"}
