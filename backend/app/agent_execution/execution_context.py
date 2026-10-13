"""Bounded, revision-fenced context for resumable agent execution."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import text

from ..context_compiler import ContextCompiler


def _stable_hash(value):
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


class ExecutionContextService:
    """Compacts model-facing context while retaining exact durable task anchors.

    Conversation history is not copied wholesale. The shared compiler selects
    authorized, revisioned context under a budget; exact task state remains in
    the compact anchor envelope and the task's own checkpoint.
    """

    def __init__(self, store, *, token_budget=12_000, output_reserve=2_500):
        self.store = store
        self.compiler = ContextCompiler(store)
        self.token_budget = token_budget
        self.output_reserve = output_reserve

    @staticmethod
    def anchors(task):
        return {
            "taskId": task["id"],
            "inputRevision": task["desired_input_revision"],
            "kind": task["kind"],
            "message": task["message"],
            "constraints": task.get("constraints", {}),
            "pendingRequests": task.get("pendingRequests", []),
            "waitReason": task.get("waitReason"),
            "dependencies": task.get("dependencies", []),
            "requirements": task.get("requirements", {}),
            "approvals": task.get("pendingApprovals", []),
            "artifacts": [
                {key: item.get(key) for key in ("id", "name", "sha256", "inputRevision", "lineage")}
                for item in task.get("artifacts", [])
            ],
            "sources": [
                {key: item.get(key) for key in ("id", "sourceId", "revision", "canonicalUrl", "title")}
                for item in task.get("sources", [])
            ],
            "operationalNoteRefs": task.get("operationalNoteRefs", []),
        }

    def _load_packet(self, owner, manifest_id):
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT payload FROM context_manifests WHERE owner_id=:owner AND id=:id"),
                               {"owner": owner, "id": manifest_id}).scalar_one_or_none()
        if row is None:
            raise HTTPException(409, {"code": "execution_context_expired", "message": "Execution context needs to be rebuilt."})
        return json.loads(row)

    def compile_or_load(self, task):
        anchors = self.anchors(task)
        anchor_hash = _stable_hash(anchors)
        saved = task.get("executionContext")
        if saved and saved.get("inputRevision") == task["desired_input_revision"] and saved.get("anchorDigest") == anchor_hash:
            packet = self._load_packet(task["owner_id"], saved["manifestId"])
            return {"descriptor": saved, "packet": packet, "text": packet["text"]}

        request = json.dumps({
            "task": task["message"],
            "capability": task["kind"],
            "constraints": task.get("constraints", {}),
            "openQuestions": task.get("pendingRequests", []),
            "dependencies": task.get("dependencies", []),
            "requiredOutputs": task.get("requirements", {}).get("requestedOutputs", []),
        }, sort_keys=True, ensure_ascii=False)
        packet = self.compiler.compile(
            task["owner_id"], task.get("sessionId"), "execution", request,
            operational_note_refs=task.get("operationalNoteRefs", []),
            token_budget=self.token_budget, reserve_output_tokens=self.output_reserve,
        )
        if packet["status"] != "ready":
            raise HTTPException(409, {"code": "execution_context_insufficient", "message": "Required execution context could not fit or is no longer available."})
        descriptor = {
            "schemaVersion": 1,
            "manifestId": packet["id"],
            "inputRevision": task["desired_input_revision"],
            "anchorDigest": anchor_hash,
            "anchors": anchors,
            "dependencies": packet["dependencies"],
            "omissions": packet["omissions"],
            "warnings": packet["warnings"],
        }
        return {"descriptor": descriptor, "packet": packet, "text": packet["text"]}

    def validate_commit(self, conn, owner, task, descriptor):
        if not descriptor or descriptor.get("inputRevision") != task.get("desired_input_revision"):
            raise HTTPException(409, {"code": "execution_context_revision_conflict", "message": "Execution context belongs to an earlier task revision."})
        if descriptor.get("anchorDigest") != _stable_hash(self.anchors(task)):
            raise HTTPException(409, {"code": "execution_context_anchor_conflict", "message": "A required question, constraint, dependency, or output changed during execution."})
        packet_row = conn.execute(text("SELECT payload FROM context_manifests WHERE owner_id=:owner AND id=:id"),
                                  {"owner": owner, "id": descriptor.get("manifestId")}).scalar_one_or_none()
        if packet_row is None:
            raise HTTPException(409, {"code": "execution_context_expired", "message": "Execution context is no longer available."})
        self.compiler.validate_commit(conn, owner, json.loads(packet_row))
