"""Review session orchestration on WorkflowStore practice_records."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..material_service import problem
from ..models import utc_now
from ..state_models import EvidenceCreate
from ..state_service import LearnerStateService
from ..workflow_store import WorkflowStore, uid
from . import memory as memory_store
from .composer import compose_session
from .evaluation_service import evaluate_answer
from .models import (
    ReviewAnswerCommand,
    ReviewAskTutorResponse,
    ReviewConfidenceCommand,
    ReviewDashboard,
    ReviewDashboardConcept,
    ReviewItemPublic,
    ReviewOption,
    ReviewSessionCreate,
    ReviewSessionPublic,
)
from .question_service import generate_question, new_item_id
from .remediation_service import generate_remediation
from .scheduler import SCHEDULER_VERSION, estimate_minutes, schedule_after_outcome
from .memory import snapshot_from_memory

log = logging.getLogger(__name__)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


class ReviewSessionService:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider
        self.records = WorkflowStore(store)

    def dashboard(self, owner: str) -> ReviewDashboard:
        with self.store.engine.connect() as conn:
            memories = memory_store.list_memories(conn, owner)
            preparing = conn.execute(text("""
                SELECT 1 FROM concept_sync_runs WHERE learner_id=:owner AND status='running' LIMIT 1
            """), {"owner": owner}).first() is not None
        unfinished = None
        for session in self.records.listing(owner, "review_session"):
            if session.get("status") in {"ready", "in_progress"}:
                unfinished = session["id"]
                break
        if not memories:
            return ReviewDashboard(empty=True, preparing=preparing, unfinished_session_id=unfinished)

        moment = _utc()
        due = weak = new = 0
        needs: list[ReviewDashboardConcept] = []
        strong: list[ReviewDashboardConcept] = []
        learned: list[ReviewDashboardConcept] = []
        titles = self._concept_titles(owner, memories)

        for memory in memories:
            next_at = _utc(memory["nextReviewAt"] if not isinstance(memory["nextReviewAt"], str) else datetime.fromisoformat(memory["nextReviewAt"]))
            is_due = next_at <= moment
            title = titles.get(memory["conceptId"], memory["conceptId"].replace("_", " "))
            reason = (memory.get("provenance") or {}).get("dueReason") or ("Due for review" if is_due else memory["masteryEstimate"].replace("_", " "))
            card = ReviewDashboardConcept(
                concept_id=memory["conceptId"], title=title, reason=reason,
                mastery_estimate=memory["masteryEstimate"], last_reviewed_at=memory.get("lastReviewedAt"),
                next_review_at=memory["nextReviewAt"], source_lesson_id=memory.get("sourceLessonId"),
            )
            if is_due:
                due += 1
            if memory["masteryEstimate"] == "needs_reinforcement" or memory["needsRemediation"]:
                weak += 1
                if len(needs) < 5:
                    needs.append(card)
            if memory["masteryEstimate"] == "recently_learned":
                new += 1
                if len(learned) < 5:
                    learned.append(card)
            if memory["masteryEstimate"] == "strong" and memory.get("lastReviewedAt") and len(strong) < 5:
                strong.append(card)

        if not needs:
            for memory in memories:
                next_at = _utc(memory["nextReviewAt"] if not isinstance(memory["nextReviewAt"], str) else datetime.fromisoformat(memory["nextReviewAt"]))
                if next_at <= moment and len(needs) < 5:
                    title = titles.get(memory["conceptId"], memory["conceptId"].replace("_", " "))
                    needs.append(ReviewDashboardConcept(
                        concept_id=memory["conceptId"], title=title,
                        reason=(memory.get("provenance") or {}).get("dueReason") or "Due for review",
                        mastery_estimate=memory["masteryEstimate"], last_reviewed_at=memory.get("lastReviewedAt"),
                        next_review_at=memory["nextReviewAt"], source_lesson_id=memory.get("sourceLessonId"),
                    ))

        reviewable = due + weak + new
        caught_up = reviewable == 0 and not unfinished
        return ReviewDashboard(
            due_count=due, weak_count=weak, new_count=new, total_concepts=len(memories),
            estimated_minutes=estimate_minutes(min(6, max(due + weak, 1)) if reviewable else 0),
            streak_days=self._streak_days(owner), preparing=preparing, unfinished_session_id=unfinished,
            needs_attention=needs, recently_strengthened=strong, recently_learned=learned,
            empty=False, caught_up=caught_up,
        )

    def _streak_days(self, owner: str) -> int:
        from datetime import timedelta
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT date(last_reviewed_at) AS day FROM concept_memory_states
                WHERE learner_id=:owner AND last_reviewed_at IS NOT NULL
                ORDER BY day DESC LIMIT 30
            """), {"owner": owner}).all()
        if not rows:
            return 0
        days = []
        for row in rows:
            day = row[0]
            days.append(day if hasattr(day, "toordinal") else datetime.fromisoformat(str(day)).date())
        streak = 0
        expected = utc_now().date()
        for current in days:
            if current == expected:
                streak += 1
                expected = current - timedelta(days=1)
            elif streak == 0 and current == expected - timedelta(days=1):
                streak = 1
                expected = current - timedelta(days=1)
            else:
                break
        return streak

    def _concept_titles(self, owner: str, memories: list[dict[str, Any]]) -> dict[str, str]:
        titles: dict[str, str] = {}
        graph_ids = {m["graphId"] for m in memories}
        for graph_id in graph_ids:
            graph = self.store.get_graph(graph_id)
            if graph:
                for concept in graph.concepts:
                    titles[concept.id] = concept.title
        return titles

    def create(self, owner: str, request: ReviewSessionCreate) -> dict[str, Any]:
        if request.resume_session_id:
            session = self.records.read(owner, request.resume_session_id, "review_session")
            if session["status"] in {"ready", "in_progress"}:
                return {"sessionId": session["id"]}
            problem("session_not_resumable", "That review session is already finished.", 409)

        for existing in self.records.listing(owner, "review_session"):
            if existing.get("status") in {"ready", "in_progress"}:
                return {"sessionId": existing["id"]}

        with self.store.engine.connect() as conn:
            memories = memory_store.list_memories(conn, owner)
        if not memories:
            problem("nothing_to_review", "Learn something first and we will build your review memory from it.", 404)

        picks, minutes = compose_session(
            memories, length=request.length, concept_ids=request.concept_ids or None, optional=request.optional,
        )
        if not picks:
            problem("nothing_due", "Nothing is due right now. Try an optional mixed review.", 404)

        graph_id = picks[0]["graphId"]
        graph_version = picks[0]["graphVersion"]
        learn_session = request.session_id
        session_id = uid("review_session")
        items = []
        recent_types: list[str] = []
        for pick in picks:
            concept = self._resolve_concept(pick["conceptId"], pick["graphId"])
            excerpt = self._source_excerpt(owner, pick)
            generated = generate_question(
                self.provider,
                concept_title=concept["title"],
                concept_summary=concept["summary"],
                source_excerpt=excerpt,
                memory=pick,
                recent_types=recent_types,
            )
            recent_types.append(generated.question_type)
            item_id = new_item_id()
            item = {
                "id": item_id,
                "sessionId": session_id,
                "conceptId": pick["conceptId"],
                "conceptTitle": concept["title"],
                "graphId": pick["graphId"],
                "graphVersion": pick["graphVersion"],
                "questionType": generated.question_type,
                "prompt": generated.prompt,
                "expectedAnswer": generated.expected_answer,
                "options": generated.options,
                # Review multiple choice is disabled until generation supplies
                # an independently validated private answer-key contract.
                "correctOptionIds": [],
                "sourceExcerpt": excerpt[:4000],
                "sourceLessonId": pick.get("sourceLessonId"),
                "dueReason": pick.get("dueReason"),
                "status": "pending",
                "attempt": None,
                "remediation": None,
                "revision": 1,
            }
            items.append(item)

        now = utc_now()
        session = {
            "id": session_id,
            "status": "ready",
            "length": request.length,
            "optional": request.optional,
            "itemIds": [item["id"] for item in items],
            "currentIndex": 0,
            "estimatedMinutes": minutes,
            "graphId": graph_id,
            "graphVersion": graph_version,
            "learnSessionId": learn_session,
            "summary": None,
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
            "revision": 1,
        }
        with self.store.transaction() as conn:
            memory_store.ensure_learner(conn, owner)
            self.records.put(conn, owner, "review_session", session)
            for item in items:
                self.records.put(conn, owner, "review_item", item, session_id)
            self._event(conn, owner, "review_started", None, {"sessionId": session_id, "itemCount": len(items), "length": request.length})
        return {"sessionId": session_id}

    def public(self, owner: str, session_id: str) -> ReviewSessionPublic:
        session = self.records.read(owner, session_id, "review_session")
        items = [self._public_item(self.records.read(owner, item_id, "review_item")) for item_id in session["itemIds"]]
        return ReviewSessionPublic(
            id=session["id"], status=session["status"], length=session["length"], revision=session["revision"],
            item_count=len(items), current_index=session.get("currentIndex", 0),
            estimated_minutes=session.get("estimatedMinutes") or estimate_minutes(len(items)),
            items=items, summary=session.get("summary"),
            created_at=datetime.fromisoformat(session["createdAt"]) if isinstance(session["createdAt"], str) else session["createdAt"],
            updated_at=datetime.fromisoformat(session["updatedAt"]) if isinstance(session["updatedAt"], str) else session["updatedAt"],
        )

    def _public_item(self, item: dict[str, Any]) -> ReviewItemPublic:
        attempt = item.get("attempt")
        # Never leak ideal answer before evaluation.
        public_attempt = None
        if attempt:
            public_attempt = {k: v for k, v in attempt.items() if k != "idealAnswer" or item.get("status") in {"evaluated", "remediating"}}
            if item.get("status") in {"evaluated", "remediating"}:
                public_attempt = attempt
        return ReviewItemPublic(
            id=item["id"], concept_id=item["conceptId"], concept_title=item["conceptTitle"],
            question_type=item["questionType"], prompt=item["prompt"],
            options=[ReviewOption(**opt) for opt in item.get("options") or []],
            status=item["status"], due_reason=item.get("dueReason"),
            source_lesson_id=item.get("sourceLessonId"),
            attempt=public_attempt, remediation=item.get("remediation"),
        )

    def _resolve_concept(self, concept_id: str, graph_id: str) -> dict[str, str]:
        graph = self.store.get_graph(graph_id)
        if graph:
            for concept in graph.concepts:
                if concept.id == concept_id:
                    return {"title": concept.title, "summary": concept.summary or concept.objective or concept.title}
        return {"title": concept_id.replace("_", " "), "summary": ""}

    def _source_excerpt(self, owner: str, memory: dict[str, Any]) -> str:
        concept = self._resolve_concept(memory["conceptId"], memory["graphId"])
        parts = [concept["title"], concept["summary"]]
        lesson_id = memory.get("sourceLessonId")
        if lesson_id:
            with self.store.engine.connect() as conn:
                row = conn.execute(text("SELECT payload FROM lesson_artifacts WHERE id=:id"), {"id": lesson_id}).mappings().first()
            if row:
                try:
                    import json
                    payload = json.loads(row["payload"])
                    for block in payload.get("blocks") or []:
                        if memory["conceptId"] in (block.get("conceptIds") or block.get("concept_ids") or []) or True:
                            parts.append(str(block.get("body") or ""))
                            if len("\n".join(parts)) > 2500:
                                break
                except Exception:
                    pass
        return "\n\n".join(p for p in parts if p)[:4000]

    def grade(self, owner: str, session_id: str, item_id: str, command: ReviewAnswerCommand):
        session = self.records.read(owner, session_id, "review_session")
        item = self.records.read(owner, item_id, "review_item")
        if item["sessionId"] != session_id:
            problem("invalid_item", "This review item is not part of the session.", 404)
        if session["revision"] != command.expected_revision:
            problem("revision_conflict", "Reload this review before continuing.", 409)
        if item.get("attempt") and item["status"] in {"evaluated", "answered"}:
            problem("already_answered", "This item was already submitted.", 409)
        if item["status"] == "skipped":
            problem("already_skipped", "This item was skipped.", 409)

        # Legacy Review MC records may contain a key inferred from option order.
        # They are not assessment-grade, so preserve the response but admit no
        # evidence. New Review generation replaces MC with free response.
        evaluation = None if item["questionType"] == "multiple_choice" else evaluate_answer(
            self.provider,
            concept_title=item["conceptTitle"],
            source_excerpt=item.get("sourceExcerpt") or "",
            prompt=item["prompt"],
            expected_answer=item.get("expectedAnswer") or "",
            response=command.response,
            selected_ids=command.selected_ids,
            correct_option_ids=item.get("correctOptionIds") or None,
        )
        if evaluation is None:
            attempt = {
                "id": uid("review_attempt"),
                "status": "evaluation_failed",
                "response": command.response,
                "selectedIds": command.selected_ids,
                "feedback": "We could not evaluate that answer right now. Your response has been saved. Try again.",
                "correctness": None,
                "score": None,
                "evidenceId": None,
                "confidence": None,
            }
            return session, item, attempt, None

        attempt = {
            "id": uid("review_attempt"),
            "status": "evaluated",
            "response": command.response,
            "selectedIds": command.selected_ids,
            "feedback": evaluation.feedback,
            "correctness": evaluation.correctness,
            "score": evaluation.score,
            "idealAnswer": evaluation.ideal_answer,
            "missingConcepts": evaluation.missing_concepts,
            "misconceptions": evaluation.misconceptions,
            "needsRemediation": evaluation.needs_remediation,
            "prerequisiteGap": evaluation.prerequisite_gap,
            "evidenceId": None,
            "confidence": None,
            "assisted": bool(item.get("remediation")),
        }
        return session, item, attempt, evaluation

    def commit_grade(self, conn, owner: str, graded) -> dict[str, Any]:
        session, item, attempt, evaluation = graded
        item["attempt"] = attempt
        item["status"] = "evaluated" if evaluation else "answered"
        self.records.put(conn, owner, "review_item", item, expected=item["revision"])
        item = self.records.read(owner, item["id"], "review_item", conn)
        item["attempt"] = attempt
        attempt_record = {**attempt, "itemId": item["id"], "sessionId": session["id"]}
        self.records.put(conn, owner, "review_attempt", attempt_record, session["id"])

        if evaluation is not None:
            code = None
            if evaluation.misconceptions:
                code = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in evaluation.misconceptions[0])[:80]
            admitted = LearnerStateService(self.store).admit_evidence(owner, EvidenceCreate(
                evidence_key=attempt["id"],
                concept_id=item["conceptId"],
                graph_id=item["graphId"],
                graph_version=item["graphVersion"],
                kind="review",
                outcome=evaluation.correctness,
                condition="assisted" if attempt.get("assisted") else "independent",
                score=evaluation.score,
                evaluator="review-eval-v1",
                reliability=0.45,
                misconception_code=code or None,
                provenance={
                    "reviewSessionId": session["id"],
                    "reviewItemId": item["id"],
                    "questionType": item["questionType"],
                    "schedulerPendingConfidence": True,
                    "uncalibrated": True,
                },
            ), connection=conn)
            attempt["evidenceId"] = admitted.evidence.id
            item["attempt"] = attempt
            self.records.put(conn, owner, "review_item", item, expected=item["revision"])
            item = self.records.read(owner, item["id"], "review_item", conn)
            stored = self.records.read(owner, attempt["id"], "review_attempt", conn)
            self.records.put(conn, owner, "review_attempt", {**stored, **attempt, "itemId": item["id"], "sessionId": session["id"]}, expected=stored["revision"])

        session = self.records.read(owner, session["id"], "review_session", conn)
        session["status"] = "in_progress"
        session["updatedAt"] = utc_now().isoformat()
        self.records.put(conn, owner, "review_session", session, expected=session["revision"])
        self._event(conn, owner, "review_answer_evaluated", item["conceptId"], {
            "sessionId": session["id"], "itemId": item["id"],
            "result": attempt.get("correctness"), "evaluationFailed": evaluation is None,
        })
        from ..evidence_ledger import EvidenceLedger
        from ..shared_contracts import RevisionRef
        EvidenceLedger(self.store).emit(conn, owner, "attempt:" + attempt["id"], "REVIEW_RESPONSE",
            concept_id=item["conceptId"], attempt_id=attempt["id"], activity_id=session["id"],
            session_id=session["id"], graph=RevisionRef(kind="graph", id=item["graphId"], revision=item["graphVersion"]),
            admission="excluded", exclusion_reasons=("review_rubric_admission_pending",),
            assistance="assisted" if attempt.get("assisted") else "unknown",
            outcome=attempt.get("correctness") or "ungraded")
        return {"sessionId": session["id"], "itemId": item["id"], "attemptId": attempt["id"]}

    def record_confidence(self, owner: str, session_id: str, item_id: str, command: ReviewConfidenceCommand) -> ReviewSessionPublic:
        session = self.records.read(owner, session_id, "review_session")
        item = self.records.read(owner, item_id, "review_item")
        if item["sessionId"] != session_id:
            problem("invalid_item", "This review item is not part of the session.", 404)
        if session["revision"] != command.expected_revision:
            problem("revision_conflict", "Reload this review before continuing.", 409)
        attempt = item.get("attempt")
        if not attempt or attempt.get("correctness") is None:
            problem("answer_required", "Submit an answer before recording confidence.", 409)
        if attempt.get("confidence"):
            return self.public(owner, session_id)

        with self.store.transaction() as conn:
            attempt["confidence"] = command.confidence
            item["attempt"] = attempt
            self.records.put(conn, owner, "review_item", item, expected=item["revision"])
            memory = memory_store.get_memory(conn, owner, item["conceptId"])
            from .scheduling_authority import apply_timing, decide_timing
            decision = decide_timing(
                outcome=attempt["correctness"],
                confidence=command.confidence,
                condition="assisted" if attempt.get("assisted") else "independent",
                memory=memory,
            )
            apply_timing(
                conn,
                learner_id=owner,
                concept_id=item["conceptId"],
                decision=decision,
                outcome=attempt["correctness"],
                confidence=command.confidence,
                score=attempt.get("score"),
                question_type=item.get("questionType"),
                evidence_id=attempt.get("evidenceId"),
                activity_type=item.get("questionType"),
                apply_memory=bool(memory),
                mirror_schedule=True,
                source="memory",
            )
            now = utc_now()
            # Advance index when confidence recorded.
            ids = session["itemIds"]
            try:
                index = ids.index(item_id)
                session["currentIndex"] = min(index + 1, len(ids) - 1)
            except ValueError:
                pass
            session["updatedAt"] = now.isoformat()
            self.records.put(conn, owner, "review_session", session, expected=session["revision"])
            self._event(conn, owner, "review_confidence_submitted", item["conceptId"], {
                "sessionId": session_id, "itemId": item_id, "confidence": command.confidence,
            })
        return self.public(owner, session_id)

    def skip(self, owner: str, session_id: str, item_id: str, expected_revision: int) -> ReviewSessionPublic:
        session = self.records.read(owner, session_id, "review_session")
        item = self.records.read(owner, item_id, "review_item")
        if item["sessionId"] != session_id:
            problem("invalid_item", "This review item is not part of the session.", 404)
        if session["revision"] != expected_revision:
            problem("revision_conflict", "Reload this review before continuing.", 409)
        if item.get("attempt"):
            problem("already_answered", "This item was already submitted.", 409)
        with self.store.transaction() as conn:
            item["status"] = "skipped"
            item["attempt"] = {"id": uid("review_attempt"), "status": "skipped", "correctness": None, "score": None}
            self.records.put(conn, owner, "review_item", item, expected=item["revision"])
            memory = memory_store.get_memory(conn, owner, item["conceptId"])
            from .scheduling_authority import apply_timing, decide_timing
            decision = decide_timing(outcome="skip", confidence=None, condition="independent", memory=memory)
            apply_timing(
                conn,
                learner_id=owner,
                concept_id=item["conceptId"],
                decision=decision,
                outcome="skip",
                confidence=None,
                score=None,
                question_type=item.get("questionType"),
                evidence_id=None,
                activity_type=item.get("questionType"),
                apply_memory=bool(memory),
                mirror_schedule=True,
                source="memory",
            )
            try:
                index = session["itemIds"].index(item_id)
                session["currentIndex"] = min(index + 1, len(session["itemIds"]) - 1)
            except ValueError:
                pass
            session["status"] = "in_progress"
            session["updatedAt"] = utc_now().isoformat()
            self.records.put(conn, owner, "review_session", session, expected=session["revision"])
        return self.public(owner, session_id)

    def remediate(self, owner: str, session_id: str, item_id: str, expected_revision: int) -> ReviewSessionPublic:
        session = self.records.read(owner, session_id, "review_session")
        item = self.records.read(owner, item_id, "review_item")
        if item["sessionId"] != session_id:
            problem("invalid_item", "This review item is not part of the session.", 404)
        if session["revision"] != expected_revision:
            problem("revision_conflict", "Reload this review before continuing.", 409)
        attempt = item.get("attempt")
        if not attempt or attempt.get("correctness") not in {"incorrect", "partial"}:
            problem("remediation_unavailable", "Remediation is available after a weak recall.", 409)
        lesson = generate_remediation(
            self.provider,
            concept_title=item["conceptTitle"],
            source_excerpt=item.get("sourceExcerpt") or "",
            missing_concepts=attempt.get("missingConcepts") or [],
            feedback=attempt.get("feedback"),
        )
        retry = generate_question(
            self.provider,
            concept_title=item["conceptTitle"],
            concept_summary=item.get("expectedAnswer") or item["conceptTitle"],
            source_excerpt=item.get("sourceExcerpt") or "",
            recent_types=[item["questionType"]],
        )
        with self.store.transaction() as conn:
            item["remediation"] = {
                "heading": lesson.heading,
                "body": lesson.body,
                "followUpPrompt": lesson.follow_up_prompt,
            }
            item["status"] = "remediating"
            # Replace prompt for retry without counting prior attempt as success.
            item["prompt"] = lesson.follow_up_prompt or retry.prompt
            item["questionType"] = "free_recall"
            item["expectedAnswer"] = retry.expected_answer or item.get("expectedAnswer")
            item["options"] = []
            item["correctOptionIds"] = []
            item["attempt"] = None  # allow a fresh retrieval after remediation
            item["priorAttempt"] = attempt
            self.records.put(conn, owner, "review_item", item, expected=item["revision"])
            session["updatedAt"] = utc_now().isoformat()
            self.records.put(conn, owner, "review_session", session, expected=session["revision"])
            self._event(conn, owner, "review_remediation_started", item["conceptId"], {"sessionId": session_id, "itemId": item_id})
        return self.public(owner, session_id)

    def complete(self, owner: str, session_id: str, expected_revision: int) -> ReviewSessionPublic:
        session = self.records.read(owner, session_id, "review_session")
        if session["revision"] != expected_revision:
            problem("revision_conflict", "Reload this review before continuing.", 409)
        items = [self.records.read(owner, item_id, "review_item") for item_id in session["itemIds"]]
        strengthened, improving, needs = [], [], []
        for item in items:
            attempt = item.get("attempt") or item.get("priorAttempt")
            title = item["conceptTitle"]
            if not attempt or attempt.get("correctness") is None:
                continue
            if attempt["correctness"] == "correct":
                strengthened.append(title)
            elif attempt["correctness"] == "partial":
                improving.append(title)
            else:
                needs.append(title)
        summary = {
            "reviewed": len(items),
            "strengthened": strengthened,
            "improving": improving,
            "needsPractice": needs,
            "message": "We'll adjust your next reviews automatically.",
        }
        with self.store.transaction() as conn:
            session["status"] = "completed"
            session["summary"] = summary
            session["updatedAt"] = utc_now().isoformat()
            self.records.put(conn, owner, "review_session", session, expected=session["revision"])
            self._event(conn, owner, "review_completed", None, {"sessionId": session_id, "reviewed": len(items)})
        return self.public(owner, session_id)

    def ask_tutor(self, owner: str, session_id: str, item_id: str) -> ReviewAskTutorResponse:
        session = self.records.read(owner, session_id, "review_session")
        item = self.records.read(owner, item_id, "review_item")
        if item["sessionId"] != session_id:
            problem("invalid_item", "This review item is not part of the session.", 404)
        attempt = item.get("attempt") or item.get("priorAttempt") or {}
        context = {
            "concept": item["conceptTitle"],
            "conceptId": item["conceptId"],
            "sourceLessonId": item.get("sourceLessonId"),
            "question": item["prompt"],
            "studentAnswer": attempt.get("response"),
            "evaluation": attempt.get("correctness"),
            "feedback": attempt.get("feedback"),
            "missingConcepts": attempt.get("missingConcepts") or [],
            "tutorTask": "Explain the missing idea clearly and prepare the student for another retrieval attempt.",
        }
        prompt = (
            f"I was reviewing “{item['conceptTitle']}” and still don't understand it.\n\n"
            f"Question: {item['prompt']}\n"
            f"My answer: {attempt.get('response') or '(none)'}\n"
            f"Feedback: {attempt.get('feedback') or '(none)'}\n\n"
            "Please explain the missing idea clearly, then help me try retrieving it again."
        )
        with self.store.transaction() as conn:
            self._event(conn, owner, "review_ask_tutor_clicked", item["conceptId"], {"sessionId": session_id, "itemId": item_id})
        return ReviewAskTutorResponse(
            session_id=session.get("learnSessionId"),
            prompt=prompt,
            context=context,
            return_review_session_id=session_id,
        )

    def concept_history(self, owner: str, concept_id: str):
        from .models import ReviewConceptHistory, ReviewHistoryEntry
        with self.store.engine.connect() as conn:
            memory = memory_store.get_memory(conn, owner, concept_id)
            rows = conn.execute(text("""
                SELECT reviewed_at, outcome, evidence_id FROM review_history
                WHERE learner_id=:owner AND schedule_id IN (
                    SELECT id FROM review_schedules WHERE learner_id=:owner AND concept_id=:concept
                ) ORDER BY reviewed_at ASC
            """), {"owner": owner, "concept": concept_id}).mappings().all()
        title = concept_id.replace("_", " ")
        if memory:
            resolved = self._resolve_concept(concept_id, memory["graphId"])
            title = resolved["title"]
        return ReviewConceptHistory(
            concept_id=concept_id, title=title,
            first_learned_at=memory.get("firstLearnedAt") if memory else None,
            last_outcome=memory.get("lastOutcome") if memory else None,
            next_review_at=memory.get("nextReviewAt") if memory else None,
            mastery_estimate=memory.get("masteryEstimate") if memory else None,
            reviews=[ReviewHistoryEntry(reviewed_at=row["reviewed_at"], outcome=row["outcome"], evidence_id=row["evidence_id"]) for row in rows],
        )

    def _event(self, conn, owner: str, kind: str, concept_id: str | None, payload: dict[str, Any]) -> None:
        now = utc_now()
        from ..evidence_ledger import EvidenceLedger
        category = {"review_confidence_submitted": "SELF_REPORT", "review_item_skipped": "SKIP"}.get(kind)
        if category:
            EvidenceLedger(self.store).emit(conn, owner, kind + ":" + str(payload.get("itemId")), category,
                concept_id=concept_id, activity_id=payload.get("sessionId"), detail=str(payload.get("confidence")) if category == "SELF_REPORT" else None)
        conn.execute(text("""
            INSERT INTO state_events
            (id, learner_id, kind, concept_id, session_id, action_id, correlation_id, causation_id,
             idempotency_key, schema_version, payload_json, provenance_json, occurred_at, recorded_at)
            VALUES (:id, :owner, :kind, :concept, NULL, NULL, NULL, NULL, NULL, 1, :payload, :prov, :now, :now)
        """), {
            "id": f"state_event_{uuid4().hex}", "owner": owner, "kind": kind, "concept": concept_id,
            "payload": __import__("json").dumps(payload, default=str),
            "prov": __import__("json").dumps({"owner": "review_session_service"}),
            "now": now,
        })
