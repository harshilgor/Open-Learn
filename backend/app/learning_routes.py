"""Local authorized workflow endpoints; jobs survive process and page restarts."""
from .execution import schedule_local
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
import logging
from .assessment_models import AnswerCommand, ChallengeCommand, JourneyCommand, QuizCreate, RevisionCommand
from .material_routes import material_owner
from .material_service import MaterialService, problem
from .model_provider import ModelProviderError
from .workflow_store import WorkflowStore, uid
from .quiz_service import QuizService
from .journey_service import JourneyService
from .note_draft_models import CreateNoteDraft, NoteDraftReplaceCommand
from .note_draft_service import NoteDraftService
from .study_note_models import ProposalCreate
from .study_note_service import StudyNoteService
from .mode_transition_models import ModeClassificationRequest, ModeTransitionInteraction, ModeTransitionResponse
from .mode_transition_service import ModeTransitionService


def run_job(store, provider, job_id):
    from sqlalchemy import text
    with store.engine.connect() as conn:
        kind = conn.execute(text('SELECT kind FROM learning_jobs WHERE id=:id'), {'id': job_id}).scalar_one_or_none()
    records = WorkflowStore(store)
    job = records.claim(job_id)
    if not job:
        return
    from .execution import LeaseHeartbeat
    heartbeat = LeaseHeartbeat(store, job)
    owner, target, payload, kind = job["owner_id"], job["target_id"], job["payload"], job["kind"]
    quiz, journey, drafts = QuizService(store, provider), JourneyService(store, provider), NoteDraftService(store, provider)
    synthesis = StudyNoteService(store, provider)
    try:
        prepared = None
        if kind == "journey":
            prepared = journey.prepare(owner, target, JourneyCommand.model_validate(payload))
        elif kind == "note_synthesis":
            prepared = synthesis.prepare(owner, target, ProposalCreate.model_validate(payload))
        elif kind == "note_draft":
            prepared = drafts.prepare(owner, target, CreateNoteDraft.model_validate(payload))
        elif kind == "next":
            prepared = quiz.prepare(owner, target, payload["expected_revision"])
        elif kind == "answer":
            prepared = quiz.grade(owner, target, AnswerCommand.model_validate(payload))
        elif kind == "adjudicate":
            from .assessment_adjudication import ChallengeService
            prepared = ChallengeService(store, provider).prepare(owner, target)
        with store.transaction() as conn:
            records.validate_lease(conn, job)
            records.validate_input(conn, job)
            if kind == "create":
                created = quiz.create(owner, QuizCreate.model_validate(payload), conn, uid("quiz"))
                result = {"quizId": created["id"]}
            elif kind == "journey":
                result = journey.commit(conn, owner, prepared)
            elif kind == "note_synthesis":
                result = synthesis.commit(conn, owner, prepared)
            elif kind == "note_draft":
                result = drafts.commit(conn, owner, prepared)
            elif kind == "next":
                result = quiz.commit_prepared(conn, owner, prepared)
            elif kind == "answer":
                result = quiz.commit_grade(conn, owner, prepared)
            elif kind == "hint":
                result = quiz.hint(owner, target, conn)
            elif kind == "retry":
                result = quiz.retry(conn, owner, target, payload["expected_revision"])
            elif kind == "resume":
                result = quiz.resume(conn, owner, target, payload["expected_revision"])
            elif kind == "pause":
                result = quiz.pause(conn, owner, target, payload["expected_revision"])
            elif kind == "challenge":
                attempt = records.read(owner, target, "attempt", conn)
                result = quiz.challenge(conn, owner, attempt["presentationId"], payload["reason"])
            elif kind == "flag":
                result = quiz.challenge(conn, owner, target, payload["reason"])
            elif kind == "adjudicate":
                from .assessment_adjudication import ChallengeService
                result = ChallengeService(store, provider).commit(conn, owner, prepared)
            else:
                raise ValueError("Unsupported job")
            records.finish(conn, job, result)
            from .execution import Outbox
            Outbox.emit(conn, owner, "learning.command.completed", target, job["id"],
                        {"jobId": job["id"], "kind": kind, "result": result})
    except Exception as exc:
        # Do not log learner answers, source passages, or provider payloads.
        safe_code = exc.detail.get("code", "http_error") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else type(exc).__name__
        logging.getLogger(__name__).warning("Learning job %s failed (%s)", job["id"], safe_code)
        message = str(exc) if isinstance(exc, ModelProviderError) else (exc.detail.get("message", "Please reload and try again.") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else "This operation could not be completed. Reload and retry; your previous work is saved.")
        try:
            from .execution import failure_policy
            code, retryable = failure_policy(exc)
            records.fail(job, code, retryable=retryable)
        except HTTPException:
            pass  # Cancellation or a replacement worker already owns the outcome.
    finally:
        heartbeat.close()


def build_learning_router(store_provider, provider_getter):
    router = APIRouter(prefix="/v1")

    def enqueue(tasks, db, owner, target, kind, payload, key):
        job = WorkflowStore(db).enqueue(owner, target, kind, payload, key)
        schedule_local(tasks, run_job, db, provider_getter(), job["id"])
        return job

    @router.get("/learning-jobs/{job_id}")
    def get_job(job_id: str, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider)):
        job = WorkflowStore(db).job(owner, job_id)
        if job["status"] in {"queued", "running"}:
            schedule_local(tasks, run_job, db, provider_getter(), job_id)
        return job

    @router.post("/learning-jobs/{job_id}/cancel")
    def cancel_job(job_id: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return WorkflowStore(db).cancel(owner, job_id)

    @router.get("/sessions/{sid}/journey")
    def get_journey(sid: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return JourneyService(db, provider_getter()).get(owner, sid)

    @router.post("/sessions/{sid}/mode-classification")
    def classify_mode(sid: str, command: ModeClassificationRequest, owner=Depends(material_owner), db=Depends(store_provider)):
        session = MaterialService(db).session(owner, sid)
        journey = JourneyService(db, None).get(owner, sid)
        transitions = ModeTransitionService(db)
        provider = provider_getter() if __import__("os").getenv("AI_TUTOR_MODE_CLASSIFICATION", "rules").lower() == "provider" else None
        if command.bypass_suggestion_id:
            if not transitions.valid_bypass(owner, sid, command.bypass_suggestion_id):
                problem("transition_unavailable", "This transition request has expired.", 409)
            # A bypass only suppresses the same one-shot classification after the
            # learner chose to continue in the current mode. It does not change mode.
            result = transitions.classify(command.message, journey.get("turns", []),
                command.current_mode, session_id=sid, owner=owner, concept_title=journey.get("steps", [{}])[journey.get("position", 0)].get("title") if journey.get("steps") else session.goal,
                course_id=session.course_id, provider=provider, bypass_suggestion_id=command.bypass_suggestion_id)
        else:
            graph = db.get_graph(session.graph_id)
            step = journey.get("steps", [])
            position = min(journey.get("position", 0), max(0, len(step) - 1))
            concept_title = step[position].get("title") if step else (graph.title if graph else session.goal)
            concept_id = step[position].get("conceptId") if step else session.current_concept_id
            result = transitions.classify(command.message, journey.get("turns", []),
                command.current_mode, session_id=sid, owner=owner, concept_title=concept_title,
                concept_id=concept_id, course_id=session.course_id, provider=provider)
        if result.suggestion:
            suggestion = result.suggestion.model_copy(update={"source_turn_id": f"request:{sid}:{journey.get('revision', 1)}",
                "mode_revision": journey.get("modeRevision", 1)})
            result.suggestion = suggestion
            transitions.attach_suggestion_metadata(owner, sid, suggestion)
        return result.model_dump(mode="json", by_alias=True)

    @router.get("/sessions/{sid}/mode-transition")
    def pending_mode_transition(sid: str, owner=Depends(material_owner), db=Depends(store_provider)):
        MaterialService(db).session(owner, sid)
        return {"pending": ModeTransitionService(db).pending(owner, sid)}

    @router.post("/sessions/{sid}/journey", status_code=202)
    def journey(sid: str, command: JourneyCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        MaterialService(db).session(owner, sid)
        return enqueue(tasks, db, owner, sid, "journey", command.model_dump(mode="json"), key)

    @router.post("/sessions/{sid}/transition-interaction")
    def transition_interaction(sid: str, interaction: ModeTransitionResponse, owner=Depends(material_owner), db=Depends(store_provider)):
        MaterialService(db).session(owner, sid)
        try:
            result = ModeTransitionService(db).transition_interaction(owner, sid, ModeTransitionInteraction(
                suggestion_id=interaction.suggestion_id, action=interaction.action,
                target_mode=interaction.target_mode, session_id=sid),
                expected_mode_revision=interaction.expected_mode_revision)
        except ValueError as exc:
            problem("transition_unavailable", str(exc), 409)
        return result

    @router.get("/sessions/{sid}/transition-gap")
    def transition_gap(sid: str, concept_id: str, concept_title: str, consecutive_misses: int = 2, owner=Depends(material_owner), db=Depends(store_provider)):
        session = MaterialService(db).session(owner, sid)
        suggestion = ModeTransitionService(db).evaluate_quiz_gap(
            owner=owner,
            session_id=sid,
            concept_id=concept_id,
            concept_title=concept_title,
            consecutive_misses=consecutive_misses,
            course_id=session.course_id,
        )
        return {"suggestion": suggestion.model_dump(mode="json", by_alias=True) if suggestion else None}


    @router.post("/sessions/{sid}/note-drafts", status_code=202)
    def create_note_draft(sid: str, command: CreateNoteDraft, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        MaterialService(db).session(owner, sid)
        return enqueue(tasks, db, owner, sid, "note_draft", command.model_dump(mode="json"), key)

    @router.get("/note-drafts/{draft_id}")
    def get_note_draft(draft_id: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return NoteDraftService(db, provider_getter()).get(owner, draft_id)

    @router.post("/note-drafts/{draft_id}/save")
    def save_note_draft(draft_id: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return NoteDraftService(db, provider_getter()).save_new(owner, draft_id)

    @router.post("/note-drafts/{draft_id}/replace")
    def replace_note_draft(draft_id: str, command: NoteDraftReplaceCommand, owner=Depends(material_owner), db=Depends(store_provider)):
        return NoteDraftService(db, provider_getter()).replace(owner, draft_id, command.expected_note_revision, command.start_offset, command.end_offset)

    @router.post("/note-drafts/{draft_id}/discard")
    def discard_note_draft(draft_id: str, owner=Depends(material_owner), db=Depends(store_provider)):
        service = NoteDraftService(db, provider_getter())
        with db.transaction() as conn:
            return service.discard(conn, owner, draft_id)
    @router.get("/quizzes")
    def listing(session_id: str | None = None, lesson_note_id: str | None = None,
                limit: int = Query(25, ge=1, le=100), cursor: str | None = Query(None, max_length=512),
                owner=Depends(material_owner), db=Depends(store_provider)):
        return QuizService(db, None).history(owner, session_id=session_id, lesson_note_id=lesson_note_id, limit=limit, cursor=cursor)

    @router.post("/quizzes", status_code=202)
    def create(command: QuizCreate, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        MaterialService(db).session(owner, command.session_id)
        return enqueue(tasks, db, owner, command.session_id, "create", command.model_dump(mode="json"), key)

    @router.get("/quizzes/{qid}")
    @router.get("/quizzes/{qid}/results")
    def get_quiz(qid: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return QuizService(db, provider_getter()).public(owner, qid)

    @router.get("/quizzes/{qid}/study-context")
    def quiz_study_context(qid: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return QuizService(db, None).study_context(owner, qid)

    @router.post("/quizzes/{qid}/next", status_code=202)
    def next_question(qid: str, command: RevisionCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, qid, "quiz")
        return enqueue(tasks, db, owner, qid, "next", command.model_dump(), key)

    @router.post("/quizzes/{qid}/attempts", status_code=202)
    def answer(qid: str, command: AnswerCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, qid, "quiz")
        WorkflowStore(db).read(owner, command.presentation_id, "presentation")
        return enqueue(tasks, db, owner, qid, "answer", command.model_dump(), key)

    @router.post("/presentations/{pid}/hints", status_code=202)
    def hint(pid: str, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, pid, "presentation")
        return enqueue(tasks, db, owner, pid, "hint", {}, key)

    @router.post("/quizzes/{qid}/pause", status_code=202)
    def pause(qid: str, command: RevisionCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, qid, "quiz")
        return enqueue(tasks, db, owner, qid, "pause", command.model_dump(), key)

    @router.post("/quizzes/{qid}/resume", status_code=202)
    def resume(qid: str, command: RevisionCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, qid, "quiz")
        return enqueue(tasks, db, owner, qid, "resume", command.model_dump(), key)

    @router.post("/quizzes/{qid}/retry", status_code=202)
    def retry(qid: str, command: RevisionCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, qid, "quiz")
        return enqueue(tasks, db, owner, qid, "retry", command.model_dump(), key)

    @router.post("/attempts/{aid}/challenges", status_code=202)
    def challenge(aid: str, command: ChallengeCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, aid, "attempt")
        return enqueue(tasks, db, owner, aid, "challenge", command.model_dump(), key)

    @router.post("/presentations/{pid}/challenges", status_code=202)
    def flag(pid: str, command: ChallengeCommand, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, pid, "presentation")
        return enqueue(tasks, db, owner, pid, "flag", command.model_dump(), key)

    @router.get("/challenges/{cid}")
    def read_challenge(cid: str, owner=Depends(material_owner), db=Depends(store_provider)):
        return WorkflowStore(db).read(owner, cid, "challenge")

    @router.post("/challenges/{cid}/review", status_code=202)
    def adjudicate(cid: str, tasks: BackgroundTasks, owner=Depends(material_owner), db=Depends(store_provider), key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200)):
        WorkflowStore(db).read(owner, cid, "challenge")
        return enqueue(tasks, db, owner, cid, "adjudicate", {}, key)

    return router
