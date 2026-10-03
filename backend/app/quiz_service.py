"""Shared inline/standalone assessment with private keys and atomic evidence."""
from datetime import datetime, timedelta
import json
import hashlib
import re
from sqlalchemy import text
from fastapi import HTTPException

from .assessment_lifecycle import AssessmentLifecycle
from .assessment_models import AnswerCommand, QuizCreate
from .context_service import canonical_evidence, retrieve, save_manifest
from .material_service import MaterialService, problem
from .models import utc_now
from .workflow_store import WorkflowStore, uid
from .workspace_note_service import WorkspaceNoteService


class QuizService:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.records = WorkflowStore(store)
        self.lifecycle = AssessmentLifecycle(store, provider)

    def _effective_attempt(self, owner, attempt):
        try:
            resolution = self.records.read(owner, "attempt_resolution_" + attempt["id"], "attempt_resolution")
            return {**attempt, **{k: v for k, v in resolution.items() if k in {"score", "status", "feedback", "criteria", "resolutionId", "solution"}}}
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        if self.records.listing(owner, "challenge"):
            pending = any(c.get("presentationId") == attempt.get("presentationId") and c.get("status") == "excluded_pending_review" for c in self.records.listing(owner, "challenge"))
            if pending:
                return {**attempt, "score": None, "status": "contested", "feedback": "This question is awaiting review and excluded from your score."}
        return attempt

    def _save_quiz(self, conn, owner, quiz, expected):
        quiz["updatedAt"] = utc_now().isoformat()
        self.records.put(conn, owner, "quiz", quiz, expected=expected)

    def history(self, owner, *, session_id=None, lesson_note_id=None):
        quizzes = self.records.listing(owner, "quiz")
        if session_id:
            MaterialService(self.store).session(owner, session_id)
            quizzes = [quiz for quiz in quizzes if quiz.get("sessionId") == session_id]
        if lesson_note_id:
            note = WorkspaceNoteService(self.store).get(owner, lesson_note_id)
            if (note.frontmatter or {}).get("study_note") is not True:
                problem("invalid_lesson", "This is not a lesson note.", 422)
            quizzes = [quiz for quiz in quizzes if quiz.get("lessonNoteId") == lesson_note_id]
        result = []
        for quiz in quizzes:
            attempts = [self._effective_attempt(owner, self.records.read(owner, aid, "attempt")) for aid in quiz.get("attempts", [])]
            first = [attempt for attempt in attempts if not attempt.get("retryOf")]
            evaluated = [attempt for attempt in first if attempt.get("score") is not None and attempt.get("status") != "contested"]
            result.append({
                "id": quiz["id"], "title": quiz["title"], "sessionId": quiz["sessionId"],
                "lessonNoteId": quiz.get("lessonNoteId"), "origin": quiz.get("origin", "quiz"),
                "status": quiz["status"], "count": quiz["count"],
                "attempted": len(first), "score": round(100 * sum(a["score"] for a in evaluated) / len(evaluated)) if evaluated else None,
                "assisted": sum(bool(a.get("assisted")) for a in first),
                "skipped": sum(a.get("status") == "skipped" for a in first),
                "dontKnow": sum(a.get("outcome") == "dont_know" for a in first),
                "contested": sum(a.get("status") == "contested" for a in first),
                "createdAt": quiz.get("createdAt"), "updatedAt": quiz.get("updatedAt"),
            })
        return sorted(result, key=lambda quiz: quiz.get("updatedAt") or quiz.get("createdAt") or "", reverse=True)

    def study_context(self, owner, quiz_id):
        quiz = self.records.read(owner, quiz_id, "quiz")
        session = MaterialService(self.store).session(owner, quiz["sessionId"])
        graph = self.store.get_graph(quiz["graphId"])
        concepts = [concept for concept in graph.concepts if concept.id in quiz.get("conceptIds", [])]
        text_value = "\n\n".join(part for part in [
            quiz.get("lessonSnapshot"),
            quiz.get("conversationSnapshot"),
            session.goal or graph.title,
            *[f"{concept.title}: {concept.summary}" for concept in concepts],
        ] if part)
        return {"spanId": f"quiz-context:{quiz_id}", "versionId": f"quiz-context:{quiz_id}",
                "pageIndex": 0, "title": "Study context (not independently verified)",
                "text": text_value[:12000], "retrieval": "study_context"}

    def create(self, owner, request: QuizCreate, connection, quiz_id):
        session = MaterialService(self.store).session(owner, request.session_id)
        lesson_note = None
        if request.lesson_note_id:
            lesson_note = WorkspaceNoteService(self.store).get(owner, request.lesson_note_id)
            frontmatter = lesson_note.frontmatter or {}
            if frontmatter.get("study_note") is not True or session.id not in (frontmatter.get("session_ids") or []):
                problem("invalid_lesson", "Choose the lesson linked to this conversation.", 422)
        if request.origin == "learn" and lesson_note is None:
            problem("lesson_required", "A lesson quiz needs its study note.", 422)
        if request.source_transition_id:
            row = connection.execute(text("SELECT payload FROM practice_records WHERE id=:id AND owner_id=:owner AND parent_id=:sid AND kind='mode_transition'"),
                {"id": f"transition_{request.source_transition_id}", "owner": owner, "sid": session.id}).first()
            payload = json.loads(row[0]) if row else {}
            if payload.get("status") != "accepted" or (payload.get("suggestion") or {}).get("targetMode") != "quiz":
                problem("invalid_transition", "Accept the quiz suggestion before starting it.", 409)
            quiz_id = "quiz_" + hashlib.sha256(f"{owner}:{session.id}:{request.source_transition_id}".encode()).hexdigest()[:32]
            existing = connection.execute(text("SELECT id FROM practice_records WHERE id=:id AND owner_id=:owner AND kind='quiz'"),
                {"id": quiz_id, "owner": owner}).first()
            if existing:
                return self.records.read(owner, quiz_id, "quiz", connection)
        graph = self.store.get_graph(session.graph_id)
        topic = (request.requested_topic or "").strip()
        topic_terms = set(re.findall(r"[a-z0-9]{4,}", topic.lower())) - {"quiz", "test", "with", "about", "some", "practice", "questions"}
        ranked = sorted(graph.concepts, key=lambda concept: len(topic_terms & set(re.findall(r"[a-z0-9]{4,}", f"{concept.title} {concept.summary}".lower()))), reverse=True)
        best = ranked[0] if ranked else None
        best_score = len(topic_terms & set(re.findall(r"[a-z0-9]{4,}", f"{best.title} {best.summary}".lower()))) if best else 0
        concepts = request.concept_ids or [best.id if best_score else session.current_concept_id or graph.concepts[0].id]
        if not set(concepts).issubset({c.id for c in graph.concepts}):
            problem("invalid_concept", "Choose concepts from this learning session.")
        now = utc_now().isoformat()
        title = topic or session.goal or graph.title
        try:
            journey = self.records.read(owner, f"journey_{session.id}", "journey", connection)
            recent_turns = journey.get("turns", [])[-4:]
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            recent_turns = []
        conversation_snapshot = "\n\n".join(
            "\n".join([str(turn.get("question") or "")[:500],
                " ".join(str(block.get("body") or "") for block in (turn.get("lesson") or {}).get("blocks", []))[:1000]])
            for turn in recent_turns if turn.get("status") in {None, "completed"}
        )[:6000]
        quiz = {"id": quiz_id, "sessionId": session.id, "conceptIds": concepts, "graphId": graph.id,
                "graphVersion": graph.version, "title": title, "requestedTopic": topic or None,
                "lessonNoteId": lesson_note.id if lesson_note else None,
                "lessonRevisionAtStart": lesson_note.revision if lesson_note else None,
                "lessonSnapshot": lesson_note.body[:12000] if lesson_note else None,
                "conversationSnapshot": conversation_snapshot or None,
                "sourceTransitionId": request.source_transition_id,
                "createdAt": now, "updatedAt": now, "count": request.count,
                "difficulty": request.difficulty, "origin": request.origin, "status": "ready", "current": None,
                "attempts": [], "presentations": [], "revision": 1, "mode": request.mode,
                "modeConfig": request.mode_config, "selectedSpanIds": request.selected_span_ids,
                "deadlineAt": None, "remainingSeconds": request.mode_config.get("duration_seconds")}
        self.records.put(connection, owner, "quiz", quiz, session.id)
        return quiz

    def public(self, owner, quiz_id):
        quiz = self.records.read(owner, quiz_id, "quiz")
        MaterialService(self.store).session(owner, quiz["sessionId"])
        current = self.records.read(owner, quiz["current"], "presentation") if quiz["current"] else None
        if current and current.get("questionPlan"):
            current["questionPlan"] = {key: current["questionPlan"][key] for key in ("objective", "capability", "reason_codes")}
        history = [self._effective_attempt(owner, self.records.read(owner, aid, "attempt")) for aid in quiz["attempts"]]
        first = [a for a in history if not a.get("retryOf")]
        evaluated = [a for a in first if a["score"] is not None and a["status"] != "contested"]
        quiz["summary"] = {"score": round(100 * sum(a["score"] for a in evaluated) / len(evaluated)) if evaluated else None,
                           "evaluated": len(evaluated), "attempted": len(first), "total": quiz["count"],
                           "assisted": sum(a["assisted"] for a in first), "skipped": sum(a["status"] == "skipped" for a in first),
                           "dontKnow": sum(a["outcome"] == "dont_know" for a in first),
                           "independentCorrect": sum(a["score"] == 1 and not a["assisted"] for a in evaluated),
                           "retries": sum(bool(a.get("retryOf")) for a in history),
                           "contested": sum(a["status"] == "contested" for a in first)}
        if quiz.get("mode") == "timed_short_quiz" and quiz.get("deadlineAt"):
            quiz["remainingSeconds"] = max(0, int((datetime.fromisoformat(quiz["deadlineAt"]) - utc_now()).total_seconds()))
        challenges = [c for c in self.records.listing(owner, "challenge") if c.get("presentationId") in quiz.get("presentations", [])]
        return {**{key: value for key, value in quiz.items() if key not in {"lessonSnapshot", "conversationSnapshot"}}, "current": current, "attempts": history, "challenges": challenges, "quality": {"approvedOnly": True}}

    def _ensure_active_time(self, quiz):
        if quiz.get("mode") != "timed_short_quiz" or not quiz.get("deadlineAt"):
            return
        deadline = datetime.fromisoformat(quiz["deadlineAt"])
        if utc_now() >= deadline:
            problem("quiz_time_elapsed", "Time is up for this quiz. Your saved answers remain available.", 409)

    def _exposure_count(self, owner, stem):
        return self.lifecycle.exposure_count(owner, stem)

    def _record_exposure(self, conn, owner, item_id, stem):
        self.lifecycle.record_exposure(conn, owner, item_id, stem, origin="quiz")

    def persist_rejections(self, owner, quiz_id, artifacts: list[dict]):
        self.lifecycle.persist_rejections(owner, quiz_id, artifacts)

    def prepare(self, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz")
        if quiz["status"] == "paused":
            problem("quiz_paused", "Resume this quiz before continuing.", 409)
        self._ensure_active_time(quiz)
        if quiz["revision"] != revision:
            problem("revision_conflict", "Reload this quiz before continuing.", 409)
        if quiz["current"]:
            current = self.records.read(owner, quiz["current"], "presentation")
            if not current.get("attemptId"):
                problem("answer_pending", "Answer or skip the current question first.", 409)
        first = [self.records.read(owner, aid, "attempt") for aid in quiz["attempts"]]
        if len([a for a in first if not a.get("retryOf")]) >= quiz["count"]:
            return quiz, None, None, None
        if self.provider is None:
            problem("provider_required", "Connect a model to generate checked questions.", 503)
        session = MaterialService(self.store).session(owner, quiz["sessionId"])
        graph = self.store.get_graph(quiz["graphId"])
        if graph.version != quiz["graphVersion"]:
            problem("curriculum_changed", "The source graph changed. Start a new quiz.", 409)
        recent = next((a for a in reversed(first) if a["status"] != "contested"), None)
        from .adaptive_question_planner import choose_question_plan
        from .unified_learner_state import UnifiedLearnerState
        previous = self.records.listing(owner, "item")
        with self.store.engine.connect() as conn:
            all_states = UnifiedLearnerState(self.store).read(conn, owner)["states"]
            from .stable_concept_service import StableConceptService
            stable = StableConceptService(self.store)
            states = []
            for scoped_id in quiz["conceptIds"]:
                resolved = stable.resolve_legacy(owner, graph.id, graph.version, scoped_id, connection=conn)
                stable_id = resolved.get("concept_id") or scoped_id
                states.extend({**state, "stableConceptId": stable_id, "conceptId": scoped_id} for state in all_states if state["conceptId"] == stable_id)
        plan = choose_question_plan(quiz, first, states, previous, quiz.get("diagnosticSpec"))
        concept_id = plan.concept_id
        concept = next(c for c in graph.concepts if c.id == concept_id)
        sources = retrieve(self.store, owner, session.id, f"{quiz.get('requestedTopic') or session.goal} {concept.title} {concept.summary}",
                           selected_span_ids=quiz.get("selectedSpanIds"),
                           metadata_scope={"conceptId": concept.id, "courseId": session.course_id})
        if not sources and not quiz.get("selectedSpanIds"):
            sources = [self.study_context(owner, quiz_id)]
            quiz["contextSource"] = True
        manifest = save_manifest(self.store, owner, session.id, concept.title, sources, selected_span_ids=quiz.get("selectedSpanIds"))
        difficulty = quiz["difficulty"]
        if difficulty == "adaptive":
            difficulty = "stretch" if plan.objective == "transfer_check" else "standard"
        plan.source_revisions = [{"spanId": s.get("spanId"), "versionId": s.get("versionId")} for s in sources]
        context = {"conceptIds": [concept_id], "concept": concept.title, "objective": quiz.get("requestedTopic") or session.goal,
                   "questionPlan": plan.model_dump(),
                   "lessonSnapshot": quiz.get("lessonSnapshot"), "conversationSnapshot": quiz.get("conversationSnapshot"),
                   "difficulty": difficulty, "sources": sources, "manifestId": manifest["id"], "evidence": canonical_evidence(self.store, owner, graph).model_dump(mode="json"),
                   "recentFeedback": recent["feedback"] if recent else None, "questionNumber": len(first) + 1}
        from .learning_control_plane import LearningControlPlane
        control = LearningControlPlane(self.store).prepare(owner, session.id, "quiz", "quick",
            quiz.get("requestedTopic") or session.goal or concept.title, target_id=concept_id,
            quiz_scope={"conceptIds": quiz["conceptIds"], "selectedSpanIds": quiz.get("selectedSpanIds", []), "graphVersion": quiz["graphVersion"]})
        if control:
            context["sharedContext"] = control["context"]
            context["controlDecision"] = LearningControlPlane.prompt_constraints(control)
            quiz["_controlPlane"] = control
        if plan.diagnostic_distinction:
            context["diagnosticSpec"] = quiz["diagnosticSpec"]
            context["objective"] = quiz["diagnosticSpec"]["objective"]
            context["diagnosticConstraints"] = "Measure only the distinguishing objective. Do not disclose the proposed explanation or teach the answer before the independent check. Reject questions that require unrelated capabilities."
        item, item_record, presentation = self.lifecycle.prepare_item(
            owner,
            context=context,
            previous=previous,
            origin=quiz.get("origin") or "quiz",
            parent_id=quiz_id,
            parent_kind="quiz",
        )
        presentation["lessonNoteId"] = quiz.get("lessonNoteId")
        item_record["questionPlan"] = plan.model_dump()
        presentation["questionPlan"] = plan.model_dump()
        interventions = [r for r in self.records.listing(owner, "teaching_intervention") if r.get("conceptId") == concept_id]
        if interventions:
            last = max(interventions, key=lambda r: r.get("createdAt", ""))
            presentation["interventionId"] = last["id"]
            presentation["interveningActivities"] = [a["id"] for a in first]
        return quiz, item, item_record, presentation

    def commit_prepared(self, conn, owner, prepared):
        quiz, item, item_record, presentation = prepared
        from .learning_control_plane import LearningControlPlane
        LearningControlPlane(self.store).validate_commit(conn, owner, quiz.pop("_controlPlane", None))
        if item is None:
            quiz["status"] = "completed"
        else:
            self.lifecycle.commit_presentation(
                conn, owner,
                item=item,
                item_record=item_record,
                presentation=presentation,
                parent_kind="quiz",
                parent_id=quiz["id"],
            )
            quiz["current"] = presentation["id"]
            quiz["presentations"].append(presentation["id"])
            quiz["status"] = "in_progress"
            if quiz.get("mode") == "timed_short_quiz" and not quiz.get("deadlineAt"):
                quiz["deadlineAt"] = (utc_now() + timedelta(seconds=int(quiz["remainingSeconds"]))).isoformat()
        self._save_quiz(conn, owner, quiz, quiz["revision"])
        return {"quizId": quiz["id"]}

    def private_item(self, owner, presentation_id):
        return self.lifecycle.load_private(owner, presentation_id)

    def grade(self, owner, quiz_id, command: AnswerCommand):
        quiz = self.records.read(owner, quiz_id, "quiz")
        if quiz["status"] == "paused":
            problem("quiz_paused", "Resume this quiz before answering.", 409)
        self._ensure_active_time(quiz)
        presentation, _item = self.private_item(owner, command.presentation_id)
        if presentation.get("quizId") != quiz_id or quiz["current"] != presentation["id"]:
            problem("invalid_presentation", "Answer the current question.", 409)
        if presentation["attemptId"] or quiz["revision"] != command.expected_revision:
            problem("revision_conflict", "This answer was already submitted or the quiz changed.", 409)
        presentation, item, attempt = self.lifecycle.evaluate_response(
            owner, command.presentation_id, command.model_dump(),
        )
        attempt["quizId"] = quiz_id
        return quiz, presentation, item, attempt

    def commit_grade(self, conn, owner, graded):
        quiz, presentation, item, attempt = graded
        attempt["lessonNoteId"] = quiz.get("lessonNoteId")
        attempt["questionPlan"] = presentation.get("questionPlan")
        attempt["interventionId"] = presentation.get("interventionId")
        attempt["interveningActivities"] = presentation.get("interveningActivities", [])
        self.lifecycle.commit_attempt(
            conn, owner,
            presentation=presentation,
            item=item,
            attempt=attempt,
            graph_id=quiz["graphId"],
            graph_version=quiz["graphVersion"],
            evidence_kind="assessment",
            provenance_extra={"sessionId": quiz["sessionId"], "quizId": quiz["id"], "lessonNoteId": quiz.get("lessonNoteId"), "origin": quiz.get("origin") or "quiz"},
            parent_id=quiz["id"],
        )
        quiz["attempts"].append(attempt["id"])
        first_count = sum(not self.records.read(owner, aid, "attempt", conn).get("retryOf") for aid in quiz["attempts"])
        quiz["status"] = "completed" if first_count >= quiz["count"] else "feedback"
        self._save_quiz(conn, owner, quiz, quiz["revision"])
        return {"quizId": quiz["id"], "attemptId": attempt["id"]}

    def hint(self, owner, presentation_id, conn):
        presentation = self.lifecycle.record_hint(conn, owner, presentation_id)
        if presentation.get("quizId"):
            quiz = self.records.read(owner, presentation["quizId"], "quiz", conn)
            self._save_quiz(conn, owner, quiz, quiz["revision"])
        return {"quizId": presentation.get("quizId")}

    def retry(self, conn, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        self._ensure_active_time(quiz)
        original = self.records.read(owner, quiz["current"], "presentation", conn) if quiz["current"] else None
        if not original or not original["attemptId"]:
            problem("answer_required", "Submit the current answer before retrying.", 409)
        presentation = {**original, "id": uid("presentation"), "attemptId": None,
                        "retryOf": original.get("retryOf") or original["attemptId"], "hints": []}
        self.records.put(conn, owner, "presentation", presentation, quiz_id)
        quiz["current"] = presentation["id"]
        quiz["presentations"].append(presentation["id"])
        quiz["status"] = "in_progress"
        self._save_quiz(conn, owner, quiz, revision)
        return {"quizId": quiz_id}

    def challenge(self, conn, owner, presentation_id, reason):
        challenge = self.lifecycle.challenge_presentation(conn, owner, presentation_id, reason)
        presentation = self.records.read(owner, presentation_id, "presentation", conn)
        if presentation.get("quizId"):
            quiz = self.records.read(owner, presentation["quizId"], "quiz", conn)
            self._save_quiz(conn, owner, quiz, quiz["revision"])
        return {"quizId": presentation.get("quizId"), "challengeId": challenge["id"]}

    def pause(self, conn, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if quiz["status"] == "completed":
            problem("quiz_completed", "This quiz is complete. Start a new quiz to practice again.", 409)
        if quiz.get("mode") == "timed_short_quiz" and quiz.get("deadlineAt"):
            remaining = max(0, int((datetime.fromisoformat(quiz["deadlineAt"]) - utc_now()).total_seconds()))
            quiz["remainingSeconds"], quiz["deadlineAt"] = remaining, None
        quiz["status"] = "paused"
        self._save_quiz(conn, owner, quiz, revision)
        return {"quizId": quiz_id}

    def resume(self, conn, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if quiz["status"] != "paused":
            problem("quiz_not_paused", "This quiz is not paused.", 409)
        if quiz.get("mode") == "timed_short_quiz":
            if not quiz.get("remainingSeconds"):
                problem("quiz_time_elapsed", "This timed quiz has no remaining time.", 409)
            quiz["deadlineAt"] = (utc_now() + timedelta(seconds=int(quiz["remainingSeconds"]))).isoformat()
        quiz["status"] = "in_progress" if quiz["current"] else "ready"
        self._save_quiz(conn, owner, quiz, revision)
        return {"quizId": quiz_id}
