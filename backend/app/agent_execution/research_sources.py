"""Durable research provenance. Response-local W/M aliases never become IDs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text

from ..identity import assert_owner_active, fail
from ..material_service import MaterialService
from ..web_evidence.clock import SystemClock
from ..web_evidence.models import AuthScope, EvidencePacket
from ..workflow_store import encoded
from .research_contracts import ResearchUnavailable


class ResearchSources:
    def __init__(self, store, *, clock=None, retention_seconds=2592000):
        if not 60 <= retention_seconds <= 2592000:
            raise ValueError("Research retention must be between 60 seconds and 30 days")
        self.store, self.clock, self.retention_seconds = store, clock or SystemClock(), retention_seconds

    def task(self, conn, owner, task_id):
        assert_owner_active(conn, owner)
        row = conn.execute(text("SELECT * FROM assistant_runs WHERE id=:id AND owner_id=:owner AND runtime_owner='agent_v2'"),
                           {"id": task_id, "owner": owner}).mappings().first()
        if row is None:
            fail("not_found", "Research task unavailable.", 404)
        return row

    def save(self, auth: AuthScope, task_id: str, input_revision: int, packets: list[EvidencePacket]):
        now = self.clock.now().timestamp()
        sources = []
        # Snapshot content only after the existing service authorized the receipt.
        for packet in packets:
            content_hash = hashlib.sha256(packet.excerpt.encode()).hexdigest()
            identity = f"{task_id}:{input_revision}:{packet.evidence_id}:{content_hash}"
            source_id = "research_source_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
            payload = packet.model_dump(mode="json", by_alias=True)
            payload.update({"id": source_id, "tenantId": auth.tenant_id, "sessionId": auth.session_id,
                            "contentHash": content_hash,
                            "semanticSupport": "unverified"})
            if packet.source_kind.value == "material":
                try:
                    block = MaterialService(self.store).source(auth.learner_id, packet.span_id)
                    payload["blockHash"] = hashlib.sha256(block["text"].encode()).hexdigest()
                except HTTPException as exc:
                    raise ResearchUnavailable("source_unavailable") from exc
            with self.store.transaction() as conn:
                task = self.task(conn, auth.learner_id, task_id)
                if task["session_id"] != auth.session_id or task["desired_input_revision"] != input_revision:
                    raise ResearchUnavailable("stale_input")
                conn.execute(text("""INSERT INTO agent_research_sources
                    (id,owner_id,run_id,input_revision,evidence_id,content_hash,payload,content_expires_at,created_at)
                    VALUES(:id,:owner,:run,:revision,:evidence,:hash,:payload,:expiry,:now)
                    ON CONFLICT(run_id,input_revision,evidence_id,content_hash) DO NOTHING"""),
                    {"id": source_id, "owner": auth.learner_id, "run": task_id, "revision": input_revision,
                     "evidence": packet.evidence_id, "hash": content_hash, "payload": encoded(payload),
                     "expiry": now + self.retention_seconds, "now": now})
            sources.append(source_id)
        return sources

    def list(self, owner, task_id, input_revision=None):
        with self.store.engine.connect() as conn:
            task = self.task(conn, owner, task_id)
            revision = input_revision or task["desired_input_revision"]
            rows = conn.execute(text("SELECT id FROM agent_research_sources WHERE owner_id=:owner AND run_id=:run AND input_revision=:revision AND deleted_at IS NULL ORDER BY created_at,id"),
                                {"owner": owner, "run": task_id, "revision": revision}).scalars().all()
        return [self.read(owner, source_id) for source_id in rows]

    def read(self, owner, source_id, *, include_excerpt=False):
        with self.store.engine.connect() as conn:
            assert_owner_active(conn, owner)
            row = conn.execute(text("SELECT * FROM agent_research_sources WHERE id=:id AND owner_id=:owner"),
                               {"id": source_id, "owner": owner}).mappings().first()
            if row is None or row["deleted_at"] is not None:
                fail("not_found", "Research source unavailable.", 404)
            self.task(conn, owner, row["run_id"])
        payload = json.loads(row["payload"])
        unavailable = self.clock.now().timestamp() >= row["content_expires_at"]
        reason = "content_expired" if unavailable else None
        if payload["sourceKind"] == "material":
            try:
                svc = MaterialService(self.store)
                block = svc.source(owner, payload["spanId"])
                allowed = payload["versionId"] in svc.attachments(owner, payload["sessionId"])
                unavailable = not allowed or hashlib.sha256(block["text"].encode()).hexdigest() != payload.get("blockHash") or unavailable
                if unavailable and reason is None:
                    reason = "source_changed"
            except HTTPException:
                unavailable, reason = True, "source_unavailable"
        result = {key: payload.get(key) for key in ("id", "title", "canonicalUrl", "domain", "sourceKind", "provider",
                 "alias", "responseBundleId", "retrievedAt", "publishedDate", "sourceClassification", "trustLabel",
                 "versionId", "spanId", "contentHash", "semanticSupport")}
        result.update({"taskId": row["run_id"], "inputRevision": row["input_revision"],
                       "contentAvailable": not unavailable, "reasonCode": reason,
                       "contentExpiresAt": datetime.fromtimestamp(row["content_expires_at"], timezone.utc).isoformat()})
        if include_excerpt:
            if unavailable:
                raise ResearchUnavailable(reason)
            result["excerpt"] = payload["excerpt"]
        return result

    def delete(self, owner, source_id):
        self.read(owner, source_id)
        with self.store.transaction() as conn:
            # Erase content as well as denying access; keep a minimal deletion receipt.
            conn.execute(text("UPDATE agent_research_sources SET payload='{}',deleted_at=:now WHERE id=:id AND owner_id=:owner"),
                         {"now": self.clock.now().timestamp(), "id": source_id, "owner": owner})
            self._invalidate_content(conn, owner, {source_id})

    @staticmethod
    def erase_material_versions(conn, owner, version_ids):
        """Called in the material deletion transaction; erase derived snapshots."""
        from sqlalchemy import inspect
        if not inspect(conn).has_table("agent_research_sources"):
            return  # Supports legacy databases during staged migration checks.
        rows = conn.execute(text("SELECT id,payload FROM agent_research_sources WHERE owner_id=:owner AND deleted_at IS NULL"),
                            {"owner": owner}).mappings().all()
        affected = {row["id"] for row in rows if json.loads(row["payload"]).get("versionId") in version_ids}
        for identifier in affected:
            conn.execute(text("UPDATE agent_research_sources SET payload='{}',deleted_at=:now WHERE id=:id AND owner_id=:owner"),
                         {"id": identifier, "owner": owner, "now": datetime.now(timezone.utc).timestamp()})
        if affected:
            ResearchSources._invalidate_content(conn, owner, affected)

    @staticmethod
    def _invalidate_content(conn, owner, identifiers):
        artifacts = conn.execute(text("SELECT id,payload FROM agent_artifacts WHERE owner_id=:owner AND status IN ('prepared','published')"), {"owner": owner}).mappings().all()
        for artifact in artifacts:
            refs = json.loads(artifact["payload"]).get("lineage", {}).get("sourceIds", [])
            if identifiers.intersection(refs):
                conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE id=:id"), {"id": artifact["id"]})
        journals = conn.execute(text("SELECT id,payload FROM agent_research_runs WHERE owner_id=:owner"), {"owner": owner}).mappings().all()
        for row in journals:
            payload = json.loads(row["payload"])
            if identifiers.intersection(payload.get("selectedSources", [])):
                payload.pop("synthesis", None)
                payload["invalidatedSources"] = True
                conn.execute(text("UPDATE agent_research_runs SET payload=:payload WHERE id=:id"), {"id": row["id"], "payload": encoded(payload)})

    def purge_expired(self):
        now = self.clock.now().timestamp()
        with self.store.transaction() as conn:
            rows = conn.execute(text("SELECT id,owner_id,payload FROM agent_research_sources WHERE content_expires_at<=:now AND deleted_at IS NULL"), {"now": now}).mappings().all()
            purged = 0
            for row in rows:
                payload = json.loads(row["payload"])
                if "excerpt" not in payload:
                    continue
                payload.pop("excerpt", None)
                conn.execute(text("UPDATE agent_research_sources SET payload=:payload WHERE id=:id"),
                             {"id": row["id"], "payload": encoded(payload)})
                self._invalidate_content(conn, row["owner_id"], {row["id"]})
                purged += 1
        return purged
