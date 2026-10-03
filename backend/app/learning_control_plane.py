"""Typed coordination of existing workflows, context and durable decisions."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Literal

from pydantic import Field
from sqlalchemy import text

from .shared_contracts import Contract, Identifier, DecisionSnapshot, SnapshotInput, RevisionRef, new_id
from .decision_store import DecisionStore
from .identity import assert_owner_active
from .material_service import MaterialService, problem
from .workflow_store import WorkflowStore


class LearningDecision(Contract):
    id: Identifier
    owner_id: Identifier
    session_id: Identifier
    workflow: Literal["ask", "learn", "quiz"]
    gear: Literal["quick", "guided", "deep"]
    target_id: Identifier | None = None
    selected_action: Literal["direct_explanation", "guided_instruction", "worked_example", "independent_check", "minimal_hint", "guided_reasoning", "prerequisite_repair", "contrastive_explanation", "self_explanation", "independent_retrieval_check", "transfer_check"]
    reason_codes: tuple[str, ...]
    required_context_id: Identifier
    event_watermark: int = Field(ge=0)
    constraints: tuple[str, ...]
    confirmation: Literal["not_required", "proposal_only"] = "not_required"
    snapshot_id: Identifier


class LearningControlPlane:
    def __init__(self, store):
        self.store = store

    def prepare(self, owner, session_id, workflow, gear, request, target_id=None, *, token_budget=12000, required_source_ids=(), quiz_scope=None):
        gear = str(gear).lower()
        if os.getenv("OPENLEARN_CONTEXT_COMPILER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
            return None
        try:
            from .context_compiler import ContextCompiler
        except ImportError:
            problem("context_compiler_unavailable", "The shared context compiler is not installed yet.", 503)
        session = MaterialService(self.store).session(owner, session_id)
        course_id = session.get("course_id") if isinstance(session, dict) else getattr(session, "course_id", None)
        stable_target = target_id
        if target_id:
            # Resolve before compiling so the shared packet contains the same
            # canonical learner projection used by policy and the decision trace.
            from .stable_concept_service import StableConceptService
            graph = self.store.get_graph(session.graph_id if not isinstance(session, dict) else session["graph_id"])
            with self.store.engine.connect() as conn:
                resolved = StableConceptService(self.store).resolve_legacy(
                    owner, graph.id, graph.version, target_id, connection=conn)
            stable_target = resolved.get("concept_id") or target_id
        compiled = ContextCompiler(self.store).compile(owner, session_id,
            "assessment" if workflow == "quiz" else "teaching", request,
            required_source_ids=required_source_ids, token_budget=token_budget, quiz_scope=quiz_scope,
            course_id=course_id, target_concept_ids=(stable_target,) if stable_target else ())
        if compiled["status"] == "insufficient_context":
            problem("required_context_unavailable", "The required source context is unavailable. Clarify the topic or select an available source.", 409)
        watermarks = compiled.get("watermarks") or {}
        watermark = int(watermarks.get("eventWatermark") or 0)
        explicit = bool(request.strip())
        from .pedagogical_actions import select_teaching_action
        from .unified_learner_state import UnifiedLearnerState
        from .hypothesis_service import HypothesisService
        with self.store.engine.connect() as conn:
            states = UnifiedLearnerState(self.store).read(conn, owner, stable_target)["states"] if target_id else []
        hypothesis = HypothesisService(self.store).recommendation(owner, target_id) if target_id else None
        previous = [r for r in WorkflowStore(self.store).listing(owner, "teaching_intervention") if r.get("sessionId") == session_id and (not target_id or r.get("conceptId") == target_id)]
        previous.sort(key=lambda r: r.get("createdAt", ""))
        attempts = WorkflowStore(self.store).listing(owner, "attempt")
        history = []
        for delivered in previous[-3:]:
            outcomes = [a for a in attempts if a.get("interventionId") == delivered["id"] and a.get("status") == "evaluated" and not a.get("retryOf")]
            history.append({"productive": any(a.get("score") == 1 for a in outcomes) if outcomes else None})
        declined = bool(previous and (previous[-1].get("policy") or {}).get("optional_follow_up") is None)
        intervention = select_teaching_action(request, workflow, states, hypothesis, history, declined)
        action = "independent_check" if workflow == "quiz" else intervention.action
        decision = LearningDecision(id=new_id("learning_decision"), owner_id=owner, session_id=session_id,
            workflow=workflow, gear=gear, target_id=target_id, selected_action=action,
            reason_codes=tuple(intervention.reason_codes) + ("explicit_learner_request" if explicit else "continue_selected_workflow", "shared_learner_evidence"),
            required_context_id=compiled["id"], event_watermark=watermark,
            constraints=("gear_controls_presentation_only", "never_infer_mastery_from_exposure", "diagnostics_are_optional",
                         "publish_assessment_only_after_validation", "note_approval_is_separate"), snapshot_id=new_id("decision_snapshot"))
        refs = tuple(RevisionRef(kind=d["kind"], id=d.get("record_id") or d.get("id"), revision=d["revision"]) for d in compiled.get("dependencies", []))
        def input_for(kind):
            reference = next((r for r in refs if r.kind == kind), None)
            return SnapshotInput(state="available", reference=reference) if reference else SnapshotInput(state="unavailable", reason="input_not_yet_available")
        snapshot = DecisionSnapshot(owner_id=owner, id=decision.snapshot_id, revision=1, created_at=datetime.now(timezone.utc),
            purpose="assessment" if workflow == "quiz" else "teaching",
            learner_projection=input_for("learner_projection"), academic_snapshot=input_for("academic_snapshot"),
            concept_graph=input_for("concept_graph"), policy=RevisionRef(kind="policy", id="learning_control_plane", revision=1),
            context_manifest=SnapshotInput(state="available", reference=RevisionRef(kind="context_manifest", id=compiled["id"], revision=1)),
            sources=tuple(r for r in refs if r.kind == "source_revision"),
            additional_dependencies=tuple(r for r in refs if r.kind not in {"source_revision", "context_manifest", "learner_projection", "academic_snapshot", "concept_graph", "policy"}),
            reason_codes=decision.reason_codes)
        with self.store.transaction() as conn:
            assert_owner_active(conn, owner)
            DecisionStore.save(conn, owner, snapshot)
            WorkflowStore(self.store).put(conn, owner, "learning_decision", decision.model_dump(mode="json"), session_id)
        return {"decision": decision.model_dump(mode="json"), "context": compiled, "intervention": intervention.model_dump()}

    def validate_commit(self, conn, owner, prepared):
        if prepared is None:
            return
        assert_owner_active(conn, owner)
        decision = LearningDecision.model_validate(prepared["decision"])
        if decision.owner_id != owner:
            problem("owner_scope_mismatch", "This decision belongs to another account.", 403)
        current = conn.execute(text("SELECT sequence FROM learning_event_sequences WHERE owner_id=:owner"), {"owner": owner}).scalar_one_or_none() or 0
        if current != decision.event_watermark:
            problem("learning_context_changed", "Your learning evidence changed while this response was prepared. Please retry using the latest context.", 409)
        saved = DecisionStore.read(conn, owner, decision.snapshot_id)
        if not saved or saved.status == "invalidated":
            problem("learning_context_invalidated", "A source or evaluation changed. Please retry with current context.", 409)
        from .context_compiler import ContextCompiler
        # Compiler owns source-revision freshness; authorization is rechecked at
        # preparation and account/evidence fences at commit.
        ContextCompiler(self.store).validate_commit(conn, owner, prepared["context"])

    @staticmethod
    def prompt_constraints(prepared):
        if prepared is None:
            return None
        decision = prepared["decision"]
        return {"action": decision["selected_action"], "workflow": decision["workflow"],
            "intervention": prepared.get("intervention"),
            "gear": decision["gear"], "reasons": decision["reason_codes"], "constraints": decision["constraints"],
            "instruction": "Honor the learner's explicit request. Offer a diagnostic only as an optional next step; never require it before answering. Teaching depth does not set assessment difficulty."}

    def record_delivery(self, conn, owner, prepared, content_id, concept_id):
        if not prepared or not content_id:
            return
        decision = prepared["decision"]
        record = {"id": "intervention_" + decision["id"], "decisionId": decision["id"],
            "sessionId": decision["session_id"], "conceptId": concept_id,
            "contentId": content_id, "contentRevision": 1, "action": decision["selected_action"],
            "beforeEventWatermark": decision["event_watermark"], "status": "delivered_exposure",
            "policy": prepared.get("intervention"), "createdAt": datetime.now(timezone.utc).isoformat()}
        WorkflowStore(self.store).put(conn, owner, "teaching_intervention", record, decision["session_id"])
