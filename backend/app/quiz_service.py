"""Shared inline/standalone assessment with private keys and atomic evidence."""
from datetime import datetime, timedelta
import base64
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
from .quiz_policy import session_plan, deferred, public_presentation, public_attempt, is_answering_timer, remaining_seconds, start_answering, stop_answering


class QuizService:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.records = WorkflowStore(store)
        self.lifecycle = AssessmentLifecycle(store, provider)

    def _effective_attempt(self, owner, attempt, pending_presentations=None):
        try:
            resolution = self.records.read(owner, "attempt_resolution_" + attempt["id"], "attempt_resolution")
            return {**attempt, **{k: v for k, v in resolution.items() if k in {"score", "status", "feedback", "criteria", "resolutionId", "solution"}}}
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        if pending_presentations is None:
            pending_presentations = self._pending_challenge_presentations(owner, attempt.get("quizId"))
        if attempt.get("presentationId") in pending_presentations:
            return {**attempt, "score": None, "status": "contested", "feedback": "This question is awaiting review and excluded from your score."}
        return attempt

    def _save_quiz(self, conn, owner, quiz, expected):
        quiz["updatedAt"] = utc_now().isoformat()
        self.records.put(conn, owner, "quiz", quiz, expected=expected)

    @staticmethod
    def _encode_history_cursor(created_at, quiz_id):
        raw = json.dumps({"createdAt": created_at, "id": quiz_id}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_history_cursor(cursor):
        try:
            if len(cursor) > 512:
                raise ValueError("cursor too long")
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get("createdAt"), str) or not isinstance(value.get("id"), str) or not value["id"]:
                raise ValueError("invalid cursor fields")
            return value["createdAt"], value["id"]
        except (ValueError, TypeError, json.JSONDecodeError):
            problem("invalid_cursor", "This quiz history page cursor is invalid. Reload quiz history.", 422)

    def _pending_challenge_presentations(self, owner, quiz_id):
        if not quiz_id:
            return set()
        with self.store.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT payload FROM practice_records
                WHERE owner_id=:owner AND kind='challenge' AND parent_id=:quiz
            """), {"owner": owner, "quiz": quiz_id}).scalars().all()
        return {payload.get("presentationId") for raw in rows if (payload := json.loads(raw)).get("status") == "excluded_pending_review"}

    def history(self, owner, *, session_id=None, lesson_note_id=None, limit=25, cursor=None):
        limit = max(1, min(int(limit), 100))
        if session_id:
            MaterialService(self.store).session(owner, session_id)
        if lesson_note_id:
            note = WorkspaceNoteService(self.store).get(owner, lesson_note_id)
            if (note.frontmatter or {}).get("study_note") is not True:
                problem("invalid_lesson", "This is not a lesson note.", 422)
        clauses = ["owner_id=:owner", "kind='quiz'", "history_created_at IS NOT NULL"]
        params = {"owner": owner, "limit": limit + 1}
        if session_id:
            clauses.append("history_session_id=:session_id")
            params["session_id"] = session_id
        if lesson_note_id:
            clauses.append("history_lesson_note_id=:lesson_note_id")
            params["lesson_note_id"] = lesson_note_id
        if cursor:
            cursor_time, cursor_id = self._decode_history_cursor(cursor)
            clauses.append("(history_created_at<:cursor_time OR (history_created_at=:cursor_time AND id<:cursor_id))")
            params.update({"cursor_time": cursor_time, "cursor_id": cursor_id})
        with self.store.engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id,payload,history_created_at FROM practice_records
                WHERE {' AND '.join(clauses)}
                ORDER BY history_created_at DESC,id DESC LIMIT :limit
            """), params).mappings().all()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        result = []
        for row in page_rows:
            quiz = json.loads(row["payload"])
            quiz_id = row["id"]
            pending_presentations = self._pending_challenge_presentations(owner, quiz_id)
            attempts = [self._effective_attempt(owner, self.records.read(owner, aid, "attempt"), pending_presentations) for aid in quiz.get("attempts", [])]
            first = [attempt for attempt in attempts if not attempt.get("retryOf")]
            evaluated = [attempt for attempt in first if attempt.get("score") is not None and attempt.get("status") != "contested"]
            result.append({
                "id": quiz_id, "title": quiz["title"], "sessionId": quiz["sessionId"],
                "lessonNoteId": quiz.get("lessonNoteId"), "origin": quiz.get("origin", "quiz"),
                "status": quiz["status"], "count": quiz["count"],
                "attempted": len(first), "score": round(100 * sum(a["score"] for a in evaluated) / len(evaluated)) if evaluated and not deferred(quiz) else None,
                "assisted": sum(bool(a.get("assisted")) for a in first),
                "skipped": sum(a.get("status") == "skipped" for a in first),
                "dontKnow": sum(a.get("outcome") == "dont_know" for a in first),
                "contested": sum(a.get("status") == "contested" for a in first),
                "createdAt": quiz.get("createdAt"), "updatedAt": quiz.get("updatedAt"),
            })
        next_cursor = self._encode_history_cursor(page_rows[-1]["history_created_at"], page_rows[-1]["id"]) if has_more and page_rows else None
        return {"quizzes": result, "nextCursor": next_cursor}

    def study_context(self, owner, quiz_id):
        quiz = self.records.read(owner, quiz_id, "quiz")
        session = MaterialService(self.store).session(owner, quiz["sessionId"])
        graph = self.store.get_graph(quiz["graphId"])
        concepts = [concept for concept in graph.concepts if concept.id in quiz.get("conceptIds", [])]
        if quiz.get('lectureOnly'):
            return {'spanId':f'quiz-context:{quiz_id}','versionId':f'quiz-context:{quiz_id}','pageIndex':0,'title':'Covered lecture transcript (not independently verified)','text':(quiz.get('lessonSnapshot') or '')[:12000],'retrieval':'study_context'}
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
        requested_scope = request.concept_ids or request.canonical_concept_ids
        concepts = requested_scope or [best.id if best_score else session.current_concept_id or graph.concepts[0].id]
        from .stable_concept_service import StableConceptService
        concepts, canonical_concepts = StableConceptService(self.store).resolve_quiz_scope(owner, graph, concepts, connection)
        if request.canonical_concept_ids and set(canonical_concepts) != set(request.canonical_concept_ids):
            problem("task_scope_mapping_conflict", "The requested stable learning scope does not match this session's reviewed concept mappings.", 409)
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
        quiz = {"id": quiz_id, "sessionId": session.id, "taskId": request.task_id,
                "conceptIds": concepts, "canonicalConceptIds": canonical_concepts, "graphId": graph.id,
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
        plan = session_plan(request, concepts, canonical_concepts, graph)
        if plan:
            quiz["sessionPlan"] = plan
            quiz["answeringStartedAt"] = None
        elif request.feedback_policy == "exam_deferred":
            problem("quiz_v2_disabled", "Exam practice is not enabled yet.", 409)
        self.records.put(connection, owner, "quiz", quiz, session.id)
        return quiz

    def public(self, owner, quiz_id):
        quiz = self.records.read(owner, quiz_id, "quiz")
        MaterialService(self.store).session(owner, quiz["sessionId"])
        submission = self._submission(owner, quiz)
        if is_answering_timer(quiz) and quiz["status"] not in {"completed", "paused"} and not submission and remaining_seconds(quiz) <= 0:
            with self.store.transaction() as conn:
                self.finish(conn, owner, quiz_id, quiz["revision"])
            quiz = self.records.read(owner, quiz_id, "quiz")
        current = self.records.read(owner, quiz["current"], "presentation") if quiz["current"] else None
        pending_presentations = self._pending_challenge_presentations(owner, quiz_id)
        history = [self._effective_attempt(owner, self.records.read(owner, aid, "attempt"), pending_presentations) for aid in quiz["attempts"]]
        for attempt in history:
            question = self.records.read(owner, attempt["presentationId"], "presentation")
            attempt["question"] = question["stem"]
        first = [a for a in history if not a.get("retryOf")]
        evaluated = [a for a in first if a["score"] is not None and a["status"] != "contested"]
        quiz["summary"] = {"score": round(100 * sum(a["score"] for a in evaluated) / len(evaluated)) if evaluated else None,
                           "evaluated": len(evaluated), "attempted": len(first), "total": quiz["count"],
                           "assisted": sum(a["assisted"] for a in first), "skipped": sum(a["status"] == "skipped" for a in first),
                           "dontKnow": sum(a["outcome"] == "dont_know" for a in first),
                           "independentCorrect": sum(a["score"] == 1 and not a["assisted"] for a in evaluated),
                           "retries": sum(bool(a.get("retryOf")) for a in history),
                           "contested": sum(a["status"] == "contested" for a in first)}
        if is_answering_timer(quiz):
            quiz["remainingSeconds"] = submission["remainingSeconds"] if submission else remaining_seconds(quiz)
            if submission:
                quiz["deadlineAt"] = None
        elif quiz.get("mode") == "timed_short_quiz" and quiz.get("deadlineAt"):
            quiz["remainingSeconds"] = max(0, int((datetime.fromisoformat(quiz["deadlineAt"]) - utc_now()).total_seconds()))
        challenges = self.records.listing_by_parent(owner, "challenge", quiz_id)
        hidden = deferred(quiz)
        if hidden:
            quiz["summary"].update(score=None, evaluated=0, independentCorrect=0)
        public_fields = {"id", "sessionId", "taskId", "conceptIds", "canonicalConceptIds", "title", "requestedTopic", "lessonNoteId", "origin", "createdAt", "updatedAt", "count", "difficulty", "status", "revision", "mode", "modeConfig", "deadlineAt", "remainingSeconds", "contextSource", "sourceSuperseded", "summary", "answeringStartedAt", "agentResultProvenance"}
        plan = quiz.get("sessionPlan") or {}
        try:
            usefulness = self.records.read(owner, f"quiz_feedback:{quiz_id}", "quiz_feedback")["useful"]
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            usefulness = None
        return {**{key: value for key, value in quiz.items() if key in public_fields},
            "usefulness": usefulness,
            "sessionPlan": {key: plan[key] for key in ("schemaVersion", "challengePreference", "feedbackPolicy", "timingPolicy", "coverageTargets") if key in plan},
            "checkingAnswer": bool(submission), "current": public_presentation(current, hidden), "attempts": [public_attempt(a, hidden) for a in history],
            "challenges": [{key: c[key] for key in ("id", "presentationId", "status", "explanation", "outcome") if key in c and (not hidden or key not in {"explanation", "outcome"})} for c in challenges], "quality": {"approvedOnly": True}}

    def _ensure_active_time(self, quiz):
        if is_answering_timer(quiz):
            if remaining_seconds(quiz) <= 0:
                problem("quiz_time_elapsed", "Time is up for this quiz. Your saved answers remain available.", 409)
            return
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
        candidate_id = f"quiz_candidate:{quiz_id}:{revision}"
        try:
            candidate = self.records.read(owner, candidate_id, "quiz_candidate")
            graph = self.store.get_graph(quiz["graphId"])
            if candidate["stateWatermark"] == canonical_evidence(self.store, owner, graph).state_version:
                from .assessment_models import Candidate
                with self.store.engine.connect() as conn:
                    self._validate_sources(conn, owner, quiz, candidate["presentation"])
                quiz["_controlPlane"] = candidate.get("controlPlane")
                if quiz.get("sessionPlan"):
                    quiz["sessionPlan"]["sourceRevisionRefs"] = candidate.get("sourceRevisionRefs", [])
                quiz["_candidateId"] = candidate_id
                return quiz, Candidate.model_validate(candidate["item"]), candidate["itemRecord"], candidate["presentation"]
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        from .assessment_profiles import resolve_provider
        profiles = (quiz.get("sessionPlan") or {}).get("modelProfiles", {})
        if resolve_provider(self.provider, "quiz_author", profiles) is None:
            problem("provider_required", "Connect a model to generate checked questions.", 503)
        session = MaterialService(self.store).session(owner, quiz["sessionId"])
        graph = self.store.get_graph(quiz["graphId"])
        if graph.version != quiz["graphVersion"]:
            problem("curriculum_changed", "The source graph changed. Start a new quiz.", 409)
        recent = next((a for a in reversed(first) if a["status"] != "contested"), None)
        from .adaptive_question_planner import choose_question_plan
        from .unified_learner_state import UnifiedLearnerState
        previous = self.records.listing(owner, "item")
        if quiz.get("sessionPlan"):
            previous = sorted(self.records.listing_by_parent(owner, "item", quiz_id), key=lambda item: item.get("createdAt", ""))
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
        if quiz.get('lectureOnly'):
            sources = [self.study_context(owner, quiz_id)]
        else:
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
        context["modelProfiles"] = profiles
        context["feedbackPolicy"] = (quiz.get("sessionPlan") or {}).get("feedbackPolicy", "practice_immediate")
        if quiz.get("sessionPlan"):
            quiz["sessionPlan"]["sourceRevisionRefs"] = plan.source_revisions
        if plan.parent_attempt_id:
            context["diagnosticAnswer"] = {"response": recent.get("response", ""), "uncertaintyReason": recent.get("uncertaintyReason")}
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
        presentation["uiVersion"] = (quiz.get("sessionPlan") or {}).get("uiVersion", 1)
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
        self._validate_sources(conn, owner, quiz, presentation)
        from .learning_control_plane import LearningControlPlane
        LearningControlPlane(self.store).validate_commit(conn, owner, quiz.pop("_controlPlane", None))
        if item is None:
            quiz["status"] = "completed"
            self._release_exam(conn, owner, quiz)
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
            if is_answering_timer(quiz):
                start_answering(quiz)
            elif quiz.get("mode") == "timed_short_quiz" and not quiz.get("deadlineAt"):
                quiz["deadlineAt"] = (utc_now() + timedelta(seconds=int(quiz["remainingSeconds"]))).isoformat()
        quiz.pop("_candidateId", None)
        self._save_quiz(conn, owner, quiz, quiz["revision"])
        # Advancing consumes or discards the one private candidate. Billing receipts
        # remain in the ledger even when generated content is no longer useful.
        conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND parent_id=:qid AND kind='quiz_candidate'"), {"owner": owner, "qid": quiz["id"]})
        return {"quizId": quiz["id"]}

    def private_item(self, owner, presentation_id):
        return self.lifecycle.load_private(owner, presentation_id)

    def grade(self, owner, quiz_id, command: AnswerCommand, *, job_id=None):
        quiz = self.records.read(owner, quiz_id, "quiz")
        if quiz["status"] == "paused":
            problem("quiz_paused", "Resume this quiz before answering.", 409)
        presentation, _item = self.private_item(owner, command.presentation_id)
        if presentation.get("quizId") != quiz_id or quiz["current"] != presentation["id"]:
            problem("invalid_presentation", "Answer the current question.", 409)
        if presentation["attemptId"] or quiz["revision"] != command.expected_revision:
            problem("revision_conflict", "This answer was already submitted or the quiz changed.", 409)
        self.lifecycle.validate_response(_item, command.model_dump())
        accepted_at = utc_now()
        if quiz.get("sessionPlan"):
            command_hash = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
            with self.store.transaction() as conn:
                self._lock_quiz(conn, owner, quiz_id)
                fresh = self.records.read(owner, quiz_id, "quiz", conn)
                if fresh["revision"] != command.expected_revision or fresh["status"] in {"completed", "paused"}:
                    problem("revision_conflict", "The quiz changed before accepting this answer.", 409)
                submission = self._submission(owner, fresh, conn)
                if submission:
                    if submission["commandHash"] != command_hash or submission.get("jobId") != job_id:
                        problem("answer_checking", "An answer is already being checked.", 409)
                    accepted_at = datetime.fromisoformat(submission["acceptedAt"])
                else:
                    self._ensure_active_time(fresh)
                    identifier = f"quiz_submission:{quiz_id}:{presentation['id']}"
                    conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND id=:id AND kind='quiz_submission'"), {"owner": owner, "id": identifier})
                    self.records.put(conn, owner, "quiz_submission", {"id": identifier, "commandHash": command_hash, "jobId": job_id,
                        "quizRevision": fresh["revision"], "acceptedAt": accepted_at.isoformat(),
                        "remainingSeconds": remaining_seconds(fresh, accepted_at), "status": "checking"}, quiz_id)
        else:
            self._ensure_active_time(quiz)
        presentation, item, attempt = self.lifecycle.evaluate_response(
            owner, command.presentation_id, command.model_dump(),
        )
        attempt["quizId"] = quiz_id
        quiz["_acceptedAt"] = accepted_at.isoformat()
        return quiz, presentation, item, attempt

    def commit_grade(self, conn, owner, graded):
        quiz, presentation, item, attempt = graded
        if quiz.get("sessionPlan"):
            self._validate_sources(conn, owner, quiz, presentation)
        stop_answering(quiz, datetime.fromisoformat(quiz.pop("_acceptedAt", utc_now().isoformat())))
        attempt["parentAttemptId"] = (presentation.get("questionPlan") or {}).get("parent_attempt_id")
        if attempt["parentAttemptId"]:
            parent_attempt = self.records.read(owner, attempt["parentAttemptId"], "attempt", conn)
            # Practice reveals the parent's explanation before a diagnostic follow-up.
            # Retain that teaching lineage instead of calling the follow-up independent.
            if not parent_attempt.get("examPending"):
                attempt["assisted"] = True
                attempt["assistanceLineage"] = {**attempt.get("assistanceLineage", {}),
                    "condition": "assisted", "parentAttemptId": parent_attempt["id"],
                    "reason": "diagnostic_after_parent_feedback"}
        attempt["lessonNoteId"] = quiz.get("lessonNoteId")
        attempt["uiVersion"] = presentation.get("uiVersion", 1)
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
        if quiz["status"] == "completed":
            self._release_exam(conn, owner, quiz)
        self._save_quiz(conn, owner, quiz, quiz["revision"])
        conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND id=:id AND kind='quiz_submission'"),
            {"owner": owner, "id": f"quiz_submission:{quiz['id']}:{presentation['id']}"})
        if ((quiz.get("sessionPlan") or {}).get("prefetchEnabled") and quiz["status"] == "feedback"
                and attempt["status"] != "uncertain"):
            self.records.enqueue(owner, quiz["id"], "quiz_prefetch", {"expected_revision": quiz["revision"] + 1},
                f"quiz-prefetch:{quiz['id']}:{quiz['revision'] + 1}", connection=conn, priority=5, max_attempts=1)
        return {"quizId": quiz["id"], "attemptId": attempt["id"]}

    def hint(self, owner, presentation_id, conn):
        current = self.records.read(owner, presentation_id, "presentation", conn)
        if current.get("quizId") and self._submission(owner, self.records.read(owner, current["quizId"], "quiz", conn), conn):
            problem("answer_checking", "Wait for the answer check before requesting a hint.", 409)
        presentation = self.lifecycle.record_hint(conn, owner, presentation_id)
        if presentation.get("quizId"):
            quiz = self.records.read(owner, presentation["quizId"], "quiz", conn)
            self._save_quiz(conn, owner, quiz, quiz["revision"])
        return {"quizId": presentation.get("quizId")}

    def retry(self, conn, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if deferred(quiz):
            problem("exam_retry_disabled", "Finish exam practice before retrying an answer.", 409)
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
        start_answering(quiz)
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
        self._lock_quiz(conn, owner, quiz_id)
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if self._submission(owner, quiz, conn):
            problem("answer_checking", "Wait for the answer check before pausing.", 409)
        if deferred(quiz):
            problem("exam_pause_disabled", "Exam practice cannot be paused. You can finish and review your saved answers.", 409)
        if quiz["status"] == "completed":
            problem("quiz_completed", "This quiz is complete. Start a new quiz to practice again.", 409)
        if is_answering_timer(quiz):
            stop_answering(quiz)
        elif quiz.get("mode") == "timed_short_quiz" and quiz.get("deadlineAt"):
            remaining = max(0, int((datetime.fromisoformat(quiz["deadlineAt"]) - utc_now()).total_seconds()))
            quiz["remainingSeconds"], quiz["deadlineAt"] = remaining, None
        quiz["status"] = "paused"
        self._save_quiz(conn, owner, quiz, revision)
        return {"quizId": quiz_id}

    def resume(self, conn, owner, quiz_id, revision):
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if quiz["status"] != "paused":
            problem("quiz_not_paused", "This quiz is not paused.", 409)
        if quiz.get("mode") == "timed_short_quiz" and not is_answering_timer(quiz):
            if not quiz.get("remainingSeconds"):
                problem("quiz_time_elapsed", "This timed quiz has no remaining time.", 409)
            quiz["deadlineAt"] = (utc_now() + timedelta(seconds=int(quiz["remainingSeconds"]))).isoformat()
        current = self.records.read(owner, quiz["current"], "presentation", conn) if is_answering_timer(quiz) and quiz.get("current") else None
        quiz["status"] = ("in_progress" if current and not current.get("attemptId") else "feedback" if current else "ready") if is_answering_timer(quiz) else "in_progress" if quiz["current"] else "ready"
        if quiz["status"] == "in_progress":
            start_answering(quiz)
        self._save_quiz(conn, owner, quiz, revision)
        return {"quizId": quiz_id}

    def _validate_sources(self, conn, owner, quiz, presentation):
        if self.store.get_graph(quiz["graphId"]).version != quiz["graphVersion"]:
            problem("curriculum_changed", "The curriculum changed while preparing this question.", 409)
        for source in (presentation or {}).get("sources", []):
            if str(source.get("spanId", "")).startswith("quiz-context:"):
                if quiz.get("lessonNoteId") and WorkspaceNoteService(self.store).get(owner, quiz["lessonNoteId"]).revision != quiz.get("lessonRevisionAtStart"):
                    problem("source_changed", "The lesson changed. Start a new quiz for the updated material.", 409)
                continue
            block = MaterialService(self.store).source(owner, source["spanId"])
            version = MaterialService(self.store).version(owner, source["versionId"], conn)
            attached = set(MaterialService(self.store).attachments(owner, quiz["sessionId"]))
            if block.get("versionId") != source.get("versionId") or block.get("text") != source.get("text") or version["status"] not in {"ready", "partially_ready"} or source["versionId"] not in attached:
                problem("source_changed", "This question's source is no longer available.", 409)

    def _release_exam(self, conn, owner, quiz):
        for payload in conn.execute(text("SELECT payload FROM practice_records WHERE owner_id=:owner AND kind='challenge' AND parent_id=:qid"), {"owner": owner, "qid": quiz["id"]}).scalars():
            challenge = json.loads(payload)
            if challenge["status"] == "excluded_pending_review":
                self.records.enqueue(owner, challenge["id"], "adjudicate", {}, "adjudicate:" + challenge["id"], connection=conn)
        for identifier in quiz.get("attempts", []):
            attempt = self.records.read(owner, identifier, "attempt", conn)
            if not attempt.get("examPending"):
                continue
            presentation = self.records.read(owner, attempt["presentationId"], "presentation", conn)
            self._validate_sources(conn, owner, quiz, presentation)
            raw = conn.execute(text("SELECT payload FROM item_solutions WHERE item_id=:id"), {"id": presentation["itemId"]}).scalar_one()
            from .assessment_models import Candidate
            presentation["examFinalized"] = True
            self.lifecycle.commit_attempt(conn, owner, presentation=presentation, item=Candidate.model_validate_json(raw),
                attempt=attempt, graph_id=quiz["graphId"], graph_version=quiz["graphVersion"],
                parent_id=quiz["id"], provenance_extra={"sessionId": quiz["sessionId"], "quizId": quiz["id"]})

    @staticmethod
    def _lock_quiz(conn, owner, quiz_id):
        # Serialize state transitions with answer acceptance and recovery.
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT id FROM practice_records WHERE owner_id=:owner AND id=:id FOR UPDATE"), {"owner": owner, "id": quiz_id}).first()
        else:
            conn.execute(text("UPDATE practice_records SET revision=revision WHERE owner_id=:owner AND id=:id"), {"owner": owner, "id": quiz_id})

    def record_usefulness(self, conn, owner, quiz_id, useful):
        self._lock_quiz(conn, owner, quiz_id)
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if quiz["status"] != "completed":
            problem("quiz_not_completed", "Finish the quiz before sharing feedback.", 409)
        identifier = f"quiz_feedback:{quiz_id}"
        revision = conn.execute(text("SELECT revision FROM practice_records WHERE owner_id=:owner AND id=:id AND kind='quiz_feedback'"), {"owner": owner, "id": identifier}).scalar_one_or_none()
        self.records.put(conn, owner, "quiz_feedback", {"id": identifier, "useful": useful,
            "createdAt": utc_now().isoformat()}, quiz_id, expected=revision)
        return {"useful": useful}

    def finish(self, conn, owner, quiz_id, revision):
        self._lock_quiz(conn, owner, quiz_id)
        quiz = self.records.read(owner, quiz_id, "quiz", conn)
        if self._submission(owner, quiz, conn):
            problem("answer_checking", "Wait for the answer check before finishing.", 409)
        if quiz["status"] == "completed":
            return {"quizId": quiz_id}
        stop_answering(quiz)
        quiz["deadlineAt"] = None
        quiz["status"] = "completed"
        self._release_exam(conn, owner, quiz)
        self._save_quiz(conn, owner, quiz, revision)
        conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND parent_id=:qid AND kind='quiz_candidate'"), {"owner": owner, "qid": quiz_id})
        return {"quizId": quiz_id}

    def _submission(self, owner, quiz, conn=None):
        if not quiz.get("current") or not quiz.get("sessionPlan"):
            return None
        try:
            value = self.records.read(owner, f"quiz_submission:{quiz['id']}:{quiz['current']}", "quiz_submission", conn)
            return value if value["status"] == "checking" and value["quizRevision"] == quiz["revision"] else None
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return None

    def release_submission(self, owner, quiz_id):
        with self.store.transaction() as conn:
            self._lock_quiz(conn, owner, quiz_id)
            quiz = self.records.read(owner, quiz_id, "quiz", conn)
            submission = self._submission(owner, quiz, conn)
            if not submission:
                return
            active = conn.execute(text("SELECT id FROM learning_jobs WHERE owner_id=:owner AND target_id=:target AND kind='answer' AND status IN ('queued','running') AND cancellation_requested=false"), {"owner": owner, "target": quiz_id}).first()
            if active:
                return
            submission["status"] = "released"
            self.records.put(conn, owner, "quiz_submission", submission, quiz_id, expected=submission["revision"])
            if is_answering_timer(quiz) and quiz["status"] not in {"paused", "completed"}:
                quiz["remainingSeconds"] = submission["remainingSeconds"]
                start_answering(quiz)
            self._save_quiz(conn, owner, quiz, quiz["revision"])

    def commit_prefetch(self, conn, owner, prepared):
        quiz, item, item_record, presentation = prepared
        if item is None or quiz["status"] != "feedback":
            return {"quizId": quiz["id"], "skipped": "not_eligible"}
        self._validate_sources(conn, owner, quiz, presentation)
        from .learning_control_plane import LearningControlPlane
        LearningControlPlane(self.store).validate_commit(conn, owner, quiz.get("_controlPlane"))
        graph = self.store.get_graph(quiz["graphId"])
        identifier = f"quiz_candidate:{quiz['id']}:{quiz['revision']}"
        conn.execute(text("DELETE FROM practice_records WHERE owner_id=:owner AND parent_id=:qid AND kind='quiz_candidate' AND id<>:id"), {"owner": owner, "qid": quiz["id"], "id": identifier})
        self.records.put(conn, owner, "quiz_candidate", {"id": identifier,
            "stateWatermark": canonical_evidence(self.store, owner, graph).state_version,
            "item": item.model_dump(), "itemRecord": item_record, "presentation": presentation,
            "sourceRevisionRefs": (quiz.get("sessionPlan") or {}).get("sourceRevisionRefs", []),
            "controlPlane": quiz.get("_controlPlane"), "createdAt": utc_now().isoformat()}, quiz["id"])
        return {"quizId": quiz["id"]}
