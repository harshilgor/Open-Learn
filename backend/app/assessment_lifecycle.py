"""Shared validated assessment lifecycle used by Quiz and Review facades."""

from __future__ import annotations

import random
from typing import Any, Literal

from sqlalchemy import text

from .assessment_generation import QualityRejected, evaluate, fingerprint, generate_item
from .assessment_models import Candidate
from .evidence_ledger import EvidenceLedger, event_id
from .shared_contracts import RevisionRef, EventConceptLink
from .material_service import problem
from .models import utc_now
from .state_models import EvidenceCreate
from .state_service import LearnerStateService
from .workflow_store import WorkflowStore, uid

Origin = Literal["quiz", "review", "learn_inline", "fresh_check"]


class AssessmentLifecycle:
    """Author → approve → present → expose → evaluate → challenge without workflow UX."""

    def __init__(self, store, provider=None):
        self.store = store
        self.provider = provider
        self.records = WorkflowStore(store)

    def exposure_count(self, owner: str, stem: str) -> int:
        with self.store.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT presented_count FROM assessment_item_exposure
                WHERE owner_id=:owner AND fingerprint=:fingerprint
            """), {"owner": owner, "fingerprint": fingerprint(stem)}).first()
            return int(row[0]) if row else 0

    def record_exposure(
        self,
        conn,
        owner: str,
        item_id: str,
        stem: str,
        *,
        presentation_id: str | None = None,
        origin: Origin | str | None = None,
        item_version: int = 1,
    ) -> None:
        values = {
            "owner": owner,
            "fingerprint": fingerprint(stem),
            "item": item_id,
            "now": utc_now(),
            "presentation": presentation_id,
            "origin": origin,
            "version": item_version,
        }
        if self.store.engine.dialect.name == "postgresql":
            conn.execute(text("""
                INSERT INTO assessment_item_exposure(
                    owner_id, fingerprint, item_id, presented_count, last_presented_at,
                    item_version, last_presentation_id, origin
                ) VALUES (
                    :owner, :fingerprint, :item, 1, :now, :version, :presentation, :origin
                )
                ON CONFLICT(owner_id, fingerprint) DO UPDATE SET
                    presented_count=assessment_item_exposure.presented_count+1,
                    last_presented_at=EXCLUDED.last_presented_at,
                    item_id=EXCLUDED.item_id,
                    item_version=COALESCE(EXCLUDED.item_version, assessment_item_exposure.item_version),
                    last_presentation_id=COALESCE(EXCLUDED.last_presentation_id, assessment_item_exposure.last_presentation_id),
                    origin=COALESCE(EXCLUDED.origin, assessment_item_exposure.origin)
            """), values)
        else:
            conn.execute(text("""
                INSERT INTO assessment_item_exposure(
                    owner_id, fingerprint, item_id, presented_count, last_presented_at,
                    item_version, last_presentation_id, origin
                ) VALUES (
                    :owner, :fingerprint, :item, 1, :now, :version, :presentation, :origin
                )
                ON CONFLICT(owner_id, fingerprint) DO UPDATE SET
                    presented_count=presented_count+1,
                    last_presented_at=excluded.last_presented_at,
                    item_id=excluded.item_id,
                    item_version=COALESCE(excluded.item_version, item_version),
                    last_presentation_id=COALESCE(excluded.last_presentation_id, last_presentation_id),
                    origin=COALESCE(excluded.origin, origin)
            """), values)

    def persist_rejections(self, owner: str, parent_id: str, artifacts: list[dict]) -> None:
        with self.store.transaction() as conn:
            for artifact in artifacts:
                rejection_id = uid("rejected_item")
                self.records.put(conn, owner, "assessment_author", {"id": uid("author"), "rejectedItemId": rejection_id, **artifact["author"]}, parent_id)
                self.records.put(conn, owner, "assessment_checker", {"id": uid("checker"), "rejectedItemId": rejection_id, **artifact["checker"]}, rejection_id)

    def prepare_item(
        self,
        owner: str,
        *,
        context: dict[str, Any],
        previous: list[dict[str, Any]],
        origin: Origin | str,
        parent_id: str,
        parent_kind: Literal["quiz", "review"] = "quiz",
    ) -> tuple[Candidate, dict[str, Any], dict[str, Any]]:
        if self.provider is None:
            problem("provider_required", "Connect a model and attach reference material to generate checked questions.", 503)
        try:
            item, author, check = generate_item(self.provider, context, previous)
        except QualityRejected as rejected:
            self.persist_rejections(owner, parent_id, rejected.artifacts)
            raise
        if self.exposure_count(owner, item.stem) >= 3:
            problem("item_overexposed", "A similar question has already been shown often. Generate a new question.", 409)
        public = item.model_dump(exclude={"solution", "correct_ids", "criteria", "hints"})
        item_id, presentation_id = uid("item"), uid("presentation")
        options = public["options"][:]
        random.SystemRandom().shuffle(options)
        item_record = {
            **public,
            "id": item_id,
            "author": author,
            "checker": check,
            "qualityStatus": "approved",
            "contextId": context.get("manifestId"),
            "provider": getattr(self.provider, "provider_name", None),
            "itemVersion": 1,
            "origin": origin,
            "contentFingerprint": fingerprint(item.stem),
            "semanticCluster": fingerprint(item.stem),
        }
        presentation = {
            **public,
            "id": presentation_id,
            "itemId": item_id,
            "itemVersion": 1,
            "origin": origin,
            "options": options,
            "hints": [],
            "attemptId": None,
            "difficulty": context.get("difficulty"),
            "contextId": context.get("manifestId"),
            "sources": context.get("sources") or [],
            "hintCount": len(item.hints),
            "workflowKind": parent_kind,
            "workflowId": parent_id,
        }
        if parent_kind == "quiz":
            presentation["quizId"] = parent_id
        else:
            presentation["quizId"] = None
            presentation["reviewSessionId"] = parent_id
        return item, item_record, presentation

    def link_presentation(
        self,
        conn,
        *,
        presentation_id: str,
        workflow_kind: str,
        workflow_id: str,
        item_id: str,
        origin: str,
        review_item_id: str | None = None,
        item_version: int = 1,
    ) -> None:
        conn.execute(text("""
            INSERT INTO assessment_presentation_links(
                presentation_id, workflow_kind, workflow_id, review_item_id, item_id, item_version, origin, created_at
            ) VALUES (
                :presentation, :kind, :workflow, :review_item, :item, :version, :origin, :now
            )
            ON CONFLICT(presentation_id) DO NOTHING
        """), {
            "presentation": presentation_id,
            "kind": workflow_kind,
            "workflow": workflow_id,
            "review_item": review_item_id,
            "item": item_id,
            "version": item_version,
            "origin": origin,
            "now": utc_now(),
        })

    def commit_presentation(
        self,
        conn,
        owner: str,
        *,
        item: Candidate,
        item_record: dict[str, Any],
        presentation: dict[str, Any],
        parent_kind: Literal["quiz", "review"],
        parent_id: str,
        review_item_id: str | None = None,
    ) -> dict[str, Any]:
        if item_record.get("qualityStatus") != "approved" or item_record.get("checker", {}).get("status") != "approved":
            problem("item_not_approved", "This question did not pass quality checks.", 409)
        self.records.put(conn, owner, "item", item_record, parent_id)
        self.records.put(conn, owner, "assessment_author", {"id": uid("author"), "itemId": item_record["id"], **item_record["author"]}, item_record["id"])
        self.records.put(conn, owner, "assessment_checker", {"id": uid("checker"), "itemId": item_record["id"], **item_record["checker"]}, item_record["id"])
        conn.execute(text("INSERT INTO item_solutions(item_id,payload) VALUES(:id,:payload)"), {
            "id": item_record["id"],
            "payload": item.model_dump_json(),
        })
        self.records.put(conn, owner, "presentation", presentation, parent_id)
        self.record_exposure(
            conn, owner, item_record["id"], item.stem,
            presentation_id=presentation["id"],
            origin=presentation.get("origin") or parent_kind,
            item_version=int(presentation.get("itemVersion") or 1),
        )
        self.link_presentation(
            conn,
            presentation_id=presentation["id"],
            workflow_kind=parent_kind,
            workflow_id=parent_id,
            item_id=item_record["id"],
            origin=str(presentation.get("origin") or parent_kind),
            review_item_id=review_item_id,
            item_version=int(presentation.get("itemVersion") or 1),
        )
        if presentation.get("retryOf"):
            EvidenceLedger(self.store).emit(conn, owner, "retry:" + presentation["id"], "RETRY_SUBMITTED",
                concept_id=item.concept_id, family_id=item.family, activity_id=parent_id)
        return presentation

    def load_private(self, owner: str, presentation_id: str) -> tuple[dict[str, Any], Candidate]:
        presentation = self.records.read(owner, presentation_id, "presentation")
        item_record = self.records.read(owner, presentation["itemId"], "item")
        if item_record.get("qualityStatus") != "approved" or presentation.get("contested"):
            problem("item_not_approved", "This question is no longer available for assessment.", 409)
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT payload FROM item_solutions WHERE item_id=:id"), {"id": presentation["itemId"]}).one()
        return presentation, Candidate.model_validate_json(row[0])

    def evaluate_response(self, owner: str, presentation_id: str, command: dict[str, Any]) -> tuple[dict[str, Any], Candidate, dict[str, Any]]:
        presentation, item = self.load_private(owner, presentation_id)
        outcome = command.get("outcome") or "answer"
        response = command.get("response") or ""
        selected_ids = list(command.get("selected_ids") or command.get("selectedIds") or [])
        if outcome == "answer":
            if item.kind == "short" and (not str(response).strip() or selected_ids):
                problem("answer_required", "Write your reasoning before submitting.")
            if item.kind != "short" and (not selected_ids or not set(selected_ids).issubset({o.id for o in item.options}) or len(set(selected_ids)) != len(selected_ids)):
                problem("invalid_selection", "Select a valid answer.")
            if item.kind == "single" and len(selected_ids) != 1:
                problem("invalid_selection", "Select one answer.")
        from .assessment_assistance import assistance_for
        with self.store.engine.connect() as conn:
            assistance = assistance_for(conn, owner, presentation, item, bool(command.get("external_help") or command.get("externalHelp")))
        result = evaluate(self.provider, item, {"outcome": outcome, "response": response, "selected_ids": selected_ids})
        attempt = {
            **result,
            "id": uid("attempt"),
            "presentationId": presentation["id"],
            "quizId": presentation.get("quizId"),
            "reviewSessionId": presentation.get("reviewSessionId"),
            "conceptId": item.concept_id,
            "response": response,
            "selectedIds": selected_ids,
            "outcome": outcome,
            "assisted": assistance["condition"] == "assisted",
            "assistanceLineage": assistance,
            "solution": item.solution,
            "retryOf": presentation.get("retryOf"),
            "correctIds": item.correct_ids,
            "evidenceId": None,
            "conceptState": None,
            "createdAt": utc_now().isoformat(),
        }
        return presentation, item, attempt

    def commit_attempt(
        self,
        conn,
        owner: str,
        *,
        presentation: dict[str, Any],
        item: Candidate,
        attempt: dict[str, Any],
        graph_id: str,
        graph_version: int,
        evidence_kind: str = "assessment",
        provenance_extra: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        if presentation.get("contested"):
            attempt.update(
                status="contested",
                score=None,
                feedback="Question flagged. This response is excluded from scoring and learning evidence.",
            )
        presentation["attemptId"] = attempt["id"]
        self.records.put(conn, owner, "presentation", presentation, expected=presentation["revision"])
        if attempt["score"] is not None:
            provenance = {
                "attemptId": attempt["id"],
                "itemId": presentation["itemId"],
                "itemFamily": item.family,
                "presentationId": presentation["id"],
                "quizId": presentation.get("quizId"),
                "reviewSessionId": presentation.get("reviewSessionId"),
                "origin": presentation.get("origin") or evidence_kind,
                "hintIds": list(presentation.get("hints") or []),
                "retryOf": presentation.get("retryOf"),
                "outcome": attempt["outcome"],
                "uncalibrated": True,
                **(provenance_extra or {}),
            }
            admitted = LearnerStateService(self.store).admit_evidence(owner, EvidenceCreate(
                evidence_key=attempt["id"],
                concept_id=item.concept_id,
                graph_id=graph_id,
                graph_version=graph_version,
                kind=evidence_kind,  # type: ignore[arg-type]
                outcome="correct" if attempt["score"] == 1 else "partial" if attempt["score"] > 0 else "incorrect",
                condition="assisted" if attempt["assisted"] else "independent",
                score=attempt["score"],
                evaluator="quiz-rubric-v1",
                reliability=0.4,
                provenance=provenance,
            ), connection=conn)
            attempt["evidenceId"] = admitted.evidence.id
            attempt["conceptState"] = admitted.learner_state.status.value if admitted.learner_state else None
        parent = parent_id or presentation.get("quizId") or presentation.get("reviewSessionId") or presentation["id"]
        self.records.put(conn, owner, "attempt", attempt, parent)
        evaluation_id = uid("evaluation")
        self.records.put(conn, owner, "assessment_evaluation", {
            "id": evaluation_id,
            "attemptId": attempt["id"],
            "itemId": presentation["itemId"],
            "role": "evaluator",
            "status": attempt["status"],
            "score": attempt["score"],
            "assisted": attempt["assisted"],
            "criteria": attempt.get("criteria", []),
            "uncertaintyReason": attempt.get("uncertaintyReason"),
        }, attempt["id"])
        generated_basis = bool(presentation.get("sources")) and all(str(source.get("spanId", "")).startswith("quiz-context:") for source in presentation["sources"])
        EvidenceLedger(self.store).emit(conn, owner, "attempt:" + attempt["id"],
            "SKIP" if attempt["outcome"] == "skip" else "REVIEW_RESPONSE" if evidence_kind == "review" else "QUIZ_RESPONSE",
            concept_id=item.concept_id, occurred_at=attempt["createdAt"], attempt_id=attempt["id"], activity_id=parent,
            session_id=(provenance_extra or {}).get("sessionId"),
            concepts=(EventConceptLink(owner_id=owner, id=event_id(owner, "attempt:" + attempt["id"]) + "_target",
                revision=1, event_id=event_id(owner, "attempt:" + attempt["id"]), concept_id=item.concept_id,
                capability=(presentation.get("questionPlan") or {}).get("capability", "explain"), role="target", attribution_basis="rubric", uncertainty="resolved"),),
            family_id=item.family, graph=RevisionRef(kind="graph", id=graph_id, revision=graph_version),
            presentation=RevisionRef(kind="presentation", id=presentation["id"], revision=presentation["revision"]),
            evaluation=RevisionRef(kind="assessment_evaluation", id=evaluation_id, revision=1),
            rubric=RevisionRef(kind="item", id=presentation["itemId"], revision=1),
            assistance=attempt.get("assistanceLineage", {}).get("condition", "unknown"),
            outcome="ungraded" if attempt["score"] is None else "correct" if attempt["score"] == 1 else "partial" if attempt["score"] > 0 else "incorrect",
            admission="not_performance" if attempt["outcome"] == "skip" else "excluded" if attempt["score"] is None or generated_basis else "admitted",
            exclusion_reasons=("unverified_generated_study_context",) if generated_basis and attempt["outcome"] != "skip" else ("contested_or_incomplete_evaluation",) if attempt["score"] is None and attempt["outcome"] != "skip" else ())
        if attempt.get("solution") and attempt["outcome"] != "skip":
            EvidenceLedger(self.store).emit(conn, owner, "solution:" + attempt["id"], "ANSWER_EXPOSED",
                concept_id=item.concept_id, family_id=item.family, activity_id=parent, occurred_at=attempt["createdAt"])
        return attempt

    def record_hint(self, conn, owner: str, presentation_id: str) -> dict[str, Any]:
        presentation, item = self.load_private(owner, presentation_id)
        if presentation["attemptId"]:
            problem("already_answered", "Hints are only available before answering.", 409)
        index = len(presentation["hints"])
        if index < len(item.hints):
            presentation["hints"].append(item.hints[index])
            EvidenceLedger(self.store).emit(conn, owner, f"hint:{presentation_id}:{index}", "HINT_REQUESTED",
                concept_id=item.concept_id, family_id=item.family, activity_id=presentation.get("quizId") or presentation.get("reviewSessionId"))
            self.records.put(conn, owner, "presentation", presentation, expected=presentation["revision"])
        return presentation

    def challenge_presentation(self, conn, owner: str, presentation_id: str, reason: str) -> dict[str, Any]:
        presentation = self.records.read(owner, presentation_id, "presentation", conn)
        presentation["contested"] = True
        self.records.put(conn, owner, "presentation", presentation, expected=presentation["revision"])
        challenge = {"id": uid("challenge"), "presentationId": presentation_id, "reason": reason, "status": "excluded_pending_review"}
        item = self.records.read(owner, presentation["itemId"], "item", conn)
        item["qualityStatus"] = "withdrawn"
        item["withdrawalReason"] = "learner_challenged"
        self.records.put(conn, owner, "item", item, expected=item["revision"])
        if presentation["attemptId"]:
            attempt = self.records.read(owner, presentation["attemptId"], "attempt", conn)
            if attempt.get("evidenceId"):
                LearnerStateService(self.store).withdraw_evidence(owner, attempt["evidenceId"], "assessment_disputed", connection=conn)
            EvidenceLedger(self.store).backfill(conn, owner)
            EvidenceLedger(self.store).emit(conn, owner, "challenge:" + challenge["id"], "EVIDENCE_RETRACTED",
                concept_id=attempt.get("conceptId"), attempt_id=attempt["id"],
                target_event_id=event_id(owner, "attempt:" + attempt["id"]),
                admission="excluded", exclusion_reasons=("learner_challenged",))
            # Original response and grade remain immutable; the ledger carries validity.
        parent = presentation.get("quizId") or presentation.get("reviewSessionId") or presentation_id
        self.records.put(conn, owner, "challenge", challenge, parent)
        # The review runs as a separate durable command after exclusion commits.
        self.records.enqueue(owner, challenge["id"], "adjudicate", {}, "adjudicate:" + challenge["id"], connection=conn)
        return challenge
