from __future__ import annotations

import json
import os
import re
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .database import database_url
from .stable_concept_routes import build_stable_concept_router
from .hypothesis_routes import build_hypothesis_router
from .graph_generator import GraphGenerator
from .learner_graph import LearnerGraphRepository, build_learner_graph_router
from .learning_kernel import build_lesson, classify_intent, resolve_concept
from .model_provider import ModelProviderError, configured_lesson_provider
from .models import (
    CreateGraphJobResponse,
    GraphJob,
    GraphVersion,
    JobStatus,
    TopicScope,
    TopicScopeCreate,
    utc_now,
)
from .learning_policy import (
    assemble_action_context,
    choose_teaching_plan,
    resolve_prerequisites,
    validate_teaching_plan,
)
from .policy_models import TeachingPlan
from .session_models import (
    ActionEvent,
    ActionStatus,
    LearningSession,
    RunStatus,
    SessionCreate,
    SessionRenameInput,
    SessionSummary,
    TeachingActionInput,
    short_title,
)
from .state_models import BranchUpdate, Position, StateEventCreate
from .state_routes import build_state_router
from .state_service import LearnerStateService
from .storage import Store
from .material_routes import build_material_router, material_owner
from .context_service import canonical_evidence
from .learning_routes import build_learning_router
from .generation_routes import build_generation_router
from .privacy_routes import build_privacy_router
from .provider_key_routes import build_provider_key_router
from .workspace_note_routes import build_workspace_note_router
from .workspace_note_context import WorkspaceNoteContextService
from .workspace_note_service import WorkspaceNoteError
from .recommendation_routes import build_recommendation_router
from .backup_routes import build_backup_router
from .course_routes import build_course_router
from .study_note_routes import build_study_note_router
from .study_note_service import StudyNoteService
from .usage_routes import build_usage_router
from .usage_events_routes import build_usage_events_router
from .usage.policy import Policy
from .review_routes import build_review_router
from .session_snapshot_routes import build_session_snapshot_router
from .class_recording_routes import build_class_recording_router
from .lecture_routes import build_lecture_router
from .lecture_pipeline import LectureWorker
from .academic_routes import build_academic_router
from .canvas_reader import build_canvas_router
from threading import Thread

app = FastAPI(title="AI Tutor Harness API", version="0.1.0")
local_web_origin = os.getenv("FORMA_WEB_ORIGIN", "http://127.0.0.1:3000")



@app.middleware("http")
async def local_desktop_auth(request, call_next):
    """Protect a desktop-started loopback service without affecting dev/API use."""
    token = os.getenv("FORMA_API_TOKEN")
    if token and request.method != "OPTIONS" and request.url.path not in {"/health", "/health/web-evidence"}:
        if request.headers.get("X-Forma-Desktop-Token") != token:
            return JSONResponse(status_code=401, content={"code": "desktop_auth_required", "message": "The local desktop session is not authorized."})
    return await call_next(request)
from .identity import validate_identity_configuration
validate_identity_configuration()
store = Store(database_url())
from .identity_middleware import IdentityMiddleware
app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[local_web_origin, "http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"],
    allow_credentials=True,
)
generator = GraphGenerator()
lesson_provider = configured_lesson_provider()
# Fail before accepting traffic if an allowance or any enabled paid-provider
# route is missing its required policy and cost bounds.
usage_policy = Policy.load()


def apply_browser_provider(values: dict[str, str]) -> None:
    """Activate browser-saved keys for subsequent requests without a restart."""
    global lesson_provider
    for name in ("AI_TUTOR_PROVIDER", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        if name in values:
            os.environ[name] = values[name]
        else:
            os.environ.pop(name, None)
    lesson_provider = configured_lesson_provider()


def get_store() -> Store:
    return store


# The learner graph is a separate cross-topic projection.  Its routes use the
# same persistence connection, while its schema and projection logic remain
# isolated from the topic graph API above.
app.include_router(build_learner_graph_router(get_store))
app.include_router(build_stable_concept_router(get_store, lambda: lesson_provider))
app.include_router(build_hypothesis_router(get_store, lambda: lesson_provider))
app.include_router(build_state_router(get_store))
from .identity_routes import build_identity_router
app.include_router(build_identity_router(get_store))
from .memory_routes import build_memory_router
app.include_router(build_memory_router(get_store))
app.include_router(build_material_router(get_store, lambda: lesson_provider))
app.include_router(build_learning_router(get_store, lambda: lesson_provider))
app.include_router(build_generation_router(get_store, lambda: lesson_provider))
from .voice.routes import build_voice_router
app.include_router(build_voice_router(get_store, lambda: lesson_provider))
app.include_router(build_privacy_router(get_store))
app.include_router(build_provider_key_router(apply_browser_provider, lambda: lesson_provider))
app.include_router(build_workspace_note_router(get_store))
app.include_router(build_recommendation_router(get_store))
app.include_router(build_backup_router(get_store))
app.include_router(build_study_note_router(get_store, lambda: lesson_provider))
app.include_router(build_usage_router(get_store))
app.include_router(build_usage_events_router(get_store))
app.include_router(build_review_router(get_store, lambda: lesson_provider))
app.include_router(build_session_snapshot_router(get_store))
app.include_router(build_class_recording_router(get_store, lambda: lesson_provider))
app.include_router(build_lecture_router(get_store, lambda: lesson_provider))
from .flashcards.routes import build_flashcard_router
app.include_router(build_flashcard_router(get_store))
from .in_class_routes import build_in_class_router
app.include_router(build_in_class_router(get_store, lambda: lesson_provider))
from .class_youtube_routes import build_class_youtube_router
app.include_router(build_class_youtube_router(get_store))
app.include_router(build_academic_router(get_store))
app.include_router(build_canvas_router(get_store))
from .browser_assistant.routes import build_assistant_router
app.include_router(build_assistant_router(get_store, lambda: lesson_provider))
from .agent_execution.routes import build_agent_router
app.include_router(build_agent_router(get_store, lambda: lesson_provider))
from .mobile_routes import build_mobile_router
app.include_router(build_mobile_router(get_store))
from .dictation_routes import build_dictation_router
app.include_router(build_dictation_router(get_store))
from .buddy_routes import build_buddy_router
app.include_router(build_buddy_router(get_store))
from .reminder_routes import build_reminder_router
app.include_router(build_reminder_router(get_store,lambda:lesson_provider))
from .agent_execution.research_routes import build_research_router
app.include_router(build_research_router(get_store))
from .agent_execution.connected_routes import build_connected_router
app.include_router(build_connected_router(get_store))


@app.on_event('startup')
def start_agent_execution_worker():
    from .agent_execution.config import worker_mode
    if worker_mode() != 'embedded': return
    from threading import Event
    from .agent_execution.worker import AgentWorker
    app.state.agent_stop = Event()
    app.state.agent_thread = Thread(target=AgentWorker(store, lambda: lesson_provider).run,
                                   args=(app.state.agent_stop,), daemon=True)
    app.state.agent_thread.start()


@app.on_event('shutdown')
def stop_agent_execution_worker():
    if hasattr(app.state, 'agent_stop'):
        app.state.agent_stop.set()
        app.state.agent_thread.join(timeout=5)


@app.on_event('startup')
def start_in_class_worker():
    from .agent_execution.config import worker_mode
    if worker_mode() != 'embedded': return
    from threading import Event
    from .in_class_worker import InClassWorker
    app.state.class_stop = Event()
    app.state.class_thread = Thread(target=InClassWorker(store, lambda: lesson_provider).run,
                                    args=(app.state.class_stop,), daemon=True)
    app.state.class_thread.start()


@app.on_event('shutdown')
def stop_in_class_worker():
    if hasattr(app.state, 'class_stop'):
        app.state.class_stop.set()
        app.state.class_thread.join(timeout=5)


@app.on_event('startup')
def start_browser_assistant_worker():
    import threading
    if os.getenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'true') != 'true': return
    mode = os.getenv('OPENLEARN_WORKER_MODE', 'external' if os.getenv('AI_TUTOR_ENV', 'development') in {'production','deployed'} else 'embedded')
    if mode != 'embedded': return
    from .browser_assistant.workers import AssistantWorker
    app.state.assistant_stop = threading.Event()
    app.state.assistant_thread = Thread(target=AssistantWorker(store, lambda: lesson_provider).run,
                                       args=(app.state.assistant_stop,), daemon=True)
    app.state.assistant_thread.start()


@app.on_event('shutdown')
def stop_browser_assistant_worker():
    if hasattr(app.state, 'assistant_stop'):
        app.state.assistant_stop.set()
        app.state.assistant_thread.join(timeout=5)


@app.on_event("startup")
def resume_interrupted_class_recordings() -> None:
    """Recover legacy class recordings after an API process restart."""
    from .agent_execution.config import worker_mode
    if worker_mode() != 'embedded': return
    from sqlalchemy import text
    with store.engine.connect() as connection:
        pending = connection.execute(text("SELECT id, learner_id FROM class_recordings WHERE status IN ('queued','processing')")).all()
    with store.transaction() as connection:
        connection.execute(text("UPDATE class_recordings SET status='queued',error=NULL WHERE status='processing'"))
    from .class_recording_service import ClassRecordingService
    for recording_id, learner_id in pending:
        Thread(target=ClassRecordingService(store, lesson_provider).process,
               args=(recording_id, learner_id), daemon=True).start()


@app.on_event("startup")
def resume_lecture_pipeline() -> None:
    # Local installs retain automatic execution. Hosted API processes use an
    # independently supervised worker from this same application package.
    if os.getenv("OPENLEARN_WORKER_MODE", "external" if os.getenv("AI_TUTOR_ENV", "development").lower() in {"production", "deployed"} else "embedded") == "embedded":
        from threading import Event
        from .worker import run
        app.state.worker_stop = Event()
        app.state.worker_thread = Thread(target=run, args=(store, lambda: lesson_provider, app.state.worker_stop), daemon=True)
        app.state.worker_thread.start()


@app.on_event("shutdown")
def stop_execution_worker() -> None:
    if hasattr(app.state, "worker_stop"):
        app.state.worker_stop.set()
        app.state.worker_thread.join(timeout=5)
app.include_router(build_course_router(get_store, lambda: lesson_provider))


@app.get("/health")
def health() -> dict:
    payload: dict = {
        "status": "ok",
        "service": "learning-harness",
        "graph_provider": generator.provider_name,
        "lesson_provider": getattr(lesson_provider, "provider_name", "deterministic_baseline"),
    }
    try:
        from .web_evidence.readiness import evaluate_readiness

        report = evaluate_readiness(store)
        payload["webEvidence"] = report.as_dict()
        if report.blocking_errors and any(
            e != "web_evidence_retention_stale" for e in report.blocking_errors
        ) and report.feature_flag_enabled:
            payload["status"] = "degraded"
    except Exception as exc:  # noqa: BLE001 — health must stay available
        payload["webEvidence"] = {"status": "error", "error": type(exc).__name__}
    return payload


@app.get('/ready')
def ready():
    from sqlalchemy import text
    from .database import require_current_schema
    try:
        with store.engine.connect() as connection:connection.execute(text('SELECT 1'))
        require_current_schema(store.url)
    except Exception:
        return JSONResponse(status_code=503,content={'status':'unavailable'},headers={'Cache-Control':'no-store'})
    return JSONResponse(content={'status':'ready'},headers={'Cache-Control':'no-store'})


@app.get("/health/web-evidence")
def web_evidence_health() -> dict:
    """Dedicated readiness signal for web evidence schema, egress, and retention."""
    from .web_evidence.readiness import evaluate_readiness

    report = evaluate_readiness(store)
    body = report.as_dict()
    if report.feature_flag_enabled and any(
        e != "web_evidence_retention_stale" for e in report.blocking_errors
    ):
        return JSONResponse(status_code=503, content=body)
    return body



@app.post("/v1/topic-scopes", response_model=TopicScope, status_code=status.HTTP_201_CREATED)
def create_topic_scope(request: TopicScopeCreate, db: Store = Depends(get_store)) -> TopicScope:
    scope = TopicScope(
        id=f"scope_{uuid4().hex}",
        topic=request.topic,
        resolved_meaning=request.topic,
        objective=request.objective or f"Build a first-principles understanding of {request.topic}.",
        depth=request.depth,
        created_at=utc_now(),
    )
    db.save_scope(scope)
    return scope


@app.post("/v1/topic-scopes/{scope_id}/graph-jobs", response_model=CreateGraphJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_graph_job(
    scope_id: str,
    db: Store = Depends(get_store),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CreateGraphJobResponse:
    scope = db.get_scope(scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail={"code": "scope_not_found", "message": "Topic scope does not exist."})
    # The first slice completes synchronously for easy local development. The
    # persisted job shape is ready to move this work to a worker later.
    now = utc_now()
    job = GraphJob(
        id=f"job_{uuid4().hex}",
        scope_id=scope.id,
        status=JobStatus.running,
        stage="generating",
        progress=20,
        created_at=now,
        updated_at=now,
    )
    db.save_job(job)
    try:
        graph = generator.generate(scope)
        job = job.model_copy(update={"status": JobStatus.completed, "stage": "limited_graph_ready", "progress": 100, "graph_id": graph.id, "warnings": [graph.trust_summary], "updated_at": utc_now()})
        db.save_graph(graph)
        db.save_job(job)
        return CreateGraphJobResponse(job=job, graph=graph)
    except Exception as exc:
        job = job.model_copy(update={"status": JobStatus.failed, "stage": "failed", "progress": 0, "error_code": "graph_generation_failed", "warnings": [str(exc)], "updated_at": utc_now()})
        db.save_job(job)
        raise HTTPException(status_code=500, detail={"code": job.error_code, "message": "Graph generation failed; retry is safe."}) from exc


@app.get("/v1/graph-jobs/{job_id}", response_model=GraphJob)
def get_graph_job(job_id: str, db: Store = Depends(get_store)) -> GraphJob:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Graph job does not exist."})
    return job


@app.get("/v1/graphs/{graph_id}", response_model=GraphVersion)
def get_graph(graph_id: str, db: Store = Depends(get_store)) -> GraphVersion:
    graph = db.get_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "Graph does not exist."})
    return graph


def _event(db: Store, action_id: str, sequence: int, event_type: str, data: dict) -> ActionEvent:
    item = ActionEvent(
        id=f"event_{uuid4().hex}",
        action_id=action_id,
        sequence=sequence,
        type=event_type,
        data=data,
        created_at=utc_now(),
    )
    db.save_event(item)
    return item


@app.post("/v1/sessions", response_model=LearningSession, status_code=status.HTTP_201_CREATED)
def create_learning_session(
    request: SessionCreate,
    owner: str = Depends(material_owner),
    db: Store = Depends(get_store),
) -> LearningSession:
    """Pin a learning session to a graph revision for resumable actions."""
    graph_id = request.graph_id
    from .buddy_service import BuddyService
    with db.transaction() as buddy_connection:
        resolved_buddy = BuddyService(db).resolve(buddy_connection, owner, request.course_id, request.buddy_id)
    if request.domain_pack_id:
        from .domain_pack import get_pack, graph_for_pack
        pack = get_pack(request.domain_pack_id, request.domain_pack_version)
        graph = graph_for_pack(pack)
        from .identity import grant_resource
        with db.transaction() as connection:
            grant_resource(connection, "graph_versions", graph.id, owner)
        if db.get_graph(graph.id) is None:
            db.save_graph(graph)
        graph_id = graph.id
    if graph_id is None and request.topic:
        scope = TopicScope(
            id=f"scope_{uuid4().hex}",
            topic=request.topic,
            resolved_meaning=request.topic,
            objective=request.goal or f"Build a first-principles understanding of {request.topic}.",
            depth="introductory",
            created_at=utc_now(),
        )
        db.save_scope(scope)
        graph = generator.generate(scope)
        db.save_graph(graph)
        graph_id = graph.id
    if graph_id is None:
        raise HTTPException(status_code=422, detail={"code": "graph_required", "message": "Provide graph_id or topic to start a session."})
    graph = db.get_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "Graph does not exist."})
    effective_learner_id = owner
    session = LearningSession(
        id=f"session_{uuid4().hex}",
        buddy_id=resolved_buddy,
        learner_id=effective_learner_id,
        course_id=request.course_id,
        graph_id=graph.id,
        graph_revision=request.graph_revision or graph.version,
        domain_pack_id=request.domain_pack_id,
        domain_pack_version=pack["version"] if request.domain_pack_id else None,
        goal=request.goal,
        title=short_title(request.topic or request.goal),
        gear=request.gear,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    # Keep the learner's single cross-topic map current as soon as a session
    # starts. Repeated imports are deduplicated by LearnerGraphRepository.
    LearnerGraphRepository(db).import_topic_graph(session.learner_id, graph)
    db.save_session(session)
    BuddyService(db).bind(owner, session.id, resolved_buddy)
    LearnerStateService(db).append_event(
        session.learner_id,
        StateEventCreate(
            kind="session.started",
            session_id=session.id,
            concept_id=session.current_concept_id,
            idempotency_key=f"session-started:{session.id}",
            payload={"graphId": session.graph_id, "graphRevision": session.graph_revision},
            provenance={"source": "session_api"},
        ),
    )
    return session


@app.get("/v1/domain-packs")
def list_domain_packs():
    from .domain_pack import packs, validate_pack
    result = packs()
    for pack in result:
        validate_pack(pack)
    return {"packs": result}


@app.get("/v1/sessions/{session_id}", response_model=LearningSession)
def get_learning_session(session_id: str, db: Store = Depends(get_store)) -> LearningSession:
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    return session


@app.get("/v1/sessions")
def list_chat_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    owner: str = Depends(material_owner),
    db: Store = Depends(get_store),
) -> dict:
    """Newest-first conversation history. Metadata only; messages load on open."""
    sessions, total = db.list_sessions(owner, limit, offset)
    return {
        "sessions": [
            SessionSummary(
                id=item.id,
                title=item.title or short_title(item.goal),
                goal=item.goal,
                course_id=item.course_id,
                updated_at=item.updated_at,
                turn_count=db.journey_turn_count(owner, item.id),
            ).to_summary_dict()
            for item in sessions
        ],
        "total": total,
    }


@app.patch("/v1/sessions/{session_id}", response_model=LearningSession)
def rename_chat_session(
    session_id: str,
    request: SessionRenameInput,
    owner: str = Depends(material_owner),
    db: Store = Depends(get_store),
) -> LearningSession:
    previous = db.get_session(session_id)
    updated = db.rename_session(session_id, owner, request.title)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    try:
        StudyNoteService(db, lesson_provider).sync_session_title(owner, session_id, previous.title if previous else "", updated.title)
    except WorkspaceNoteError:
        pass
    return updated


@app.post("/v1/sessions/{session_id}/regenerate-title", response_model=LearningSession)
def regenerate_chat_title(
    session_id: str,
    automatic: bool = Query(default=False),
    owner: str = Depends(material_owner),
    db: Store = Depends(get_store),
) -> LearningSession:
    """Name a specific concept after the first tutor reply; explicit regeneration is always allowed."""
    session = db.get_session(session_id)
    if session is None or session.learner_id != owner:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    if automatic and (session.title or "") not in {"", "Untitled conversation", short_title(session.goal)}:
        return session
    from .journey_service import JourneyService
    journey = JourneyService(db, lesson_provider).get(owner, session_id)
    completed = next((turn for turn in journey.get("turns", []) if turn.get("lesson")), None)
    if not completed:
        raise HTTPException(status_code=409, detail={"code": "title_not_ready", "message": "Wait for the first tutor response before naming this chat."})
    if lesson_provider is None:
        raise HTTPException(status_code=503, detail={"code": "provider_unavailable", "message": "Connect a model provider to generate a chat title."})
    first_blocks = (completed.get("lesson") or {}).get("blocks") or []
    from .content_titles import generate_content_title
    title = generate_content_title(str(completed.get("question") or session.goal or ""), first_blocks, lesson_provider)
    updated = db.rename_session(session_id, owner, title)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    try:
        StudyNoteService(db, lesson_provider).sync_session_title(owner, session_id, session.title or "", updated.title)
    except WorkspaceNoteError:
        pass
    return updated


@app.delete("/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(
    session_id: str,
    owner: str = Depends(material_owner),
    db: Store = Depends(get_store),
) -> None:
    if not db.delete_session(session_id, owner):
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    return None


@app.post("/v1/sessions/{session_id}/actions", response_model=RunStatus, status_code=status.HTTP_202_ACCEPTED)
def create_teaching_action(
    session_id: str,
    request: TeachingActionInput,
    db: Store = Depends(get_store),
    owner: str = Depends(material_owner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunStatus:
    """Run the first complete learning-kernel action synchronously.

    The response is immediately useful for a local prototype. Every stage is
    persisted and emitted as an event, so a worker and live provider can be
    introduced without changing this command boundary.
    """
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    # A missing development identity represents the local single-user shell.
    # When an identity is supplied, preserve strict learner ownership.
    if session.learner_id != owner:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    if request.expected_state_version is not None and request.expected_state_version != session.state_version:
        raise HTTPException(status_code=409, detail={"code": "stale_session", "message": "The session changed; reload it before sending this action."})
    if idempotency_key:
        existing = db.get_action_by_idempotency(session_id, idempotency_key)
        if existing is not None:
            return existing
    graph = db.get_graph(session.graph_id)
    if graph is None:
        raise HTTPException(status_code=409, detail={"code": "graph_unavailable", "message": "The session's graph is no longer available."})
    try:
        note_manifest = WorkspaceNoteContextService(db).resolve(
            owner,
            request.note_context,
        )
    except WorkspaceNoteError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    active_branch = None
    if request.branch_id:
        try:
            active_branch = LearnerStateService(db).get_branch(session.learner_id, request.branch_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail={"code": "branch_not_found", "message": "The exploration branch does not exist."}) from exc
        if active_branch.session_id != session.id:
            raise HTTPException(status_code=409, detail={"code": "branch_session_mismatch", "message": "The exploration belongs to another learning session."})
        if active_branch.lifecycle != "open":
            raise HTTPException(status_code=409, detail={"code": "branch_closed", "message": "This exploration is closed; reopen it before continuing."})

    action_id = f"run_{uuid4().hex}"
    now = utc_now()
    action = RunStatus(
        run_id=action_id,
        session_id=session.id,
        status=ActionStatus.received,
        progress=0,
        message="Action received.",
        created_at=now,
        updated_at=now,
    )
    db.save_action(action, idempotency_key)
    _event(db, action_id, 0, "action.started", {"session_id": session.id})
    try:
        intent = classify_intent(request)
        action = action.model_copy(update={"status": ActionStatus.authorized, "progress": 10, "intent": intent, "message": "Intent classified.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 1, "intent.classified", {"intent": intent.value})
        concept = resolve_concept(graph, request.concept_id or (active_branch.anchor.concept_id if active_branch else None))
        selected_gear = request.gear or session.gear
        learner_projection = LearnerGraphRepository(db).get_graph(session.learner_id)
        action_context = assemble_action_context(
            action_id=action_id,
            graph=graph,
            session=session,
            target_concept_id=concept.id,
            intent=intent,
            gear=selected_gear,
            learner_graph=learner_projection,
        )
        branch_anchor = active_branch.anchor.model_dump(mode="json", by_alias=True) if active_branch else (request.anchor.model_dump(mode="json", by_alias=True) if request.anchor else None)
        if active_branch and branch_anchor is not None:
            # Carry only the anchored parent lesson excerpt into this isolated
            # branch. The parent's full transcript remains in its own session.
            lesson_id = active_branch.anchor.lesson_id
            parent_lesson = db.get_artifact(lesson_id) if lesson_id else None
            if parent_lesson and parent_lesson.session_id == session.id:
                parent_block = next((block for block in parent_lesson.blocks
                                     if block.id == active_branch.anchor.block_id), None)
                if parent_block is None and parent_lesson.blocks:
                    parent_block = parent_lesson.blocks[0]
                branch_anchor["parentLesson"] = {
                    "id": parent_lesson.id, "title": parent_lesson.title,
                    "conceptId": parent_lesson.concept_id,
                    "heading": parent_block.heading if parent_block else None,
                    "excerpt": parent_block.body[:1600] if parent_block else None,
                }
            if active_branch.summary:
                branch_anchor["branchSummary"] = active_branch.summary[:2000]
        action_context = action_context.model_copy(update={
            "learner_evidence": canonical_evidence(db, session.learner_id, graph),
            "request_message": request.message or (active_branch.anchor.selected_text if active_branch else concept.title),
            "branch_id": active_branch.id if active_branch else None,
            "parent_branch_id": active_branch.parent_branch_id if active_branch else None,
            "anchor": branch_anchor,
        })
        action = action.model_copy(update={"status": ActionStatus.context_ready, "progress": 30, "action_context": action_context, "message": "Graph, position, gear, evidence, and intent context assembled.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 2, "context.ready", {
            "graph_id": graph.id,
            "concept_id": concept.id,
            "graph_revision": graph.version,
            "learner_state_version": action_context.learner_evidence.state_version,
            "profile": action_context.teaching_profile.model_dump(mode="json", by_alias=True),
            "note_context_count": len(note_manifest.notes),
        })
        prerequisite_resolution = resolve_prerequisites(graph, action_context)
        plan = choose_teaching_plan(graph, action_context, prerequisite_resolution, intent)
        db.save_teaching_plan(plan)
        action = action.model_copy(update={"status": ActionStatus.planned, "progress": 45, "teaching_plan": plan, "message": "Typed teaching plan prepared.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 3, "plan.created", {
            "plan_id": plan.id,
            "gear": selected_gear.value,
            "concept_id": concept.id,
            "strategy": plan.strategy.value,
            "gap_classification": plan.gap_classification.value,
            "prerequisite_outcomes": [item.value for item in prerequisite_resolution.outcomes],
            "representation_sequence": plan.representation_sequence,
        })
        validation = validate_teaching_plan(graph, action_context, plan)
        db.save_policy_validation(validation)
        action = action.model_copy(update={"policy_validation": validation, "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 4, "plan.validated", validation.model_dump(mode="json", by_alias=True))
        if not validation.accepted:
            raise RuntimeError("Teaching plan failed deterministic policy validation.")
        artifact = build_lesson(
            graph, concept, request, session.id, intent, session.graph_revision, action_id, action_context, plan, lesson_provider,
            [item.model_dump(mode="json") for item in note_manifest.notes] or None,
        )
        db.save_artifact(artifact)
        _event(db, action_id, 5, "artifact.created", {"lesson_id": artifact.id, "plan_id": plan.id, "block_count": len(artifact.blocks)})
        action = action.model_copy(update={"status": ActionStatus.generated, "progress": 70, "lesson": artifact, "message": "AI-assisted lesson created." if lesson_provider else "Structured lesson created.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 6, "verification.completed", {
            "status": "qualified_not_verified",
            "trust": "insufficient",
            "provider": artifact.generated_by,
            "source_backed_correctness": False,
            "model_verified": False,
            "calibrated_mastery": False,
        })
        action = action.model_copy(update={"status": ActionStatus.qualified_response, "progress": 100, "lesson": artifact, "message": "Lesson ready as a limited deterministic scaffold; no correctness or mastery claim was made.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 7, "lesson.completed", {"lesson_id": artifact.id, "qualified": True, "evidence_created": False, "mastery_updated": False})
        updated_session = session.model_copy(update={
            "current_concept_id": session.current_concept_id if active_branch else concept.id,
            "current_lesson_id": session.current_lesson_id if active_branch else artifact.id,
            "gear": selected_gear,
            "state_version": session.state_version + 1,
            "updated_at": utc_now(),
        })
        db.save_session(updated_session)
        LearnerStateService(db).append_event(
            session.learner_id,
            StateEventCreate(
                kind="lesson.completed",
                concept_id=concept.id,
                session_id=session.id,
                action_id=action_id,
                idempotency_key=f"lesson-completed:{action_id}",
                payload={"lessonId": artifact.id, "qualified": True},
                provenance={"source": "learning_kernel", "provider": artifact.generated_by},
            ),
        )
        if active_branch:
            LearnerStateService(db).update_branch(
                session.learner_id,
                active_branch.id,
                BranchUpdate(
                    expected_revision=active_branch.revision,
                    return_position=Position(concept_id=concept.id, lesson_id=artifact.id),
                    summary=artifact.title,
                ),
            )
        return action
    except HTTPException:
        raise
    except Exception as exc:
        failed = action.model_copy(update={"status": ActionStatus.failed, "progress": 0, "message": "Teaching action failed; retry is safe.", "updated_at": utc_now()})
        db.save_action(failed, idempotency_key)
        _event(db, action_id, 99, "action.failed", {"code": "teaching_action_failed", "detail": str(exc)})
        raise HTTPException(status_code=502 if isinstance(exc, ModelProviderError) else 500, detail={"code": "teaching_action_failed", "message": str(exc) if isinstance(exc, ModelProviderError) else "Teaching action failed; retry is safe."}) from exc


@app.get("/v1/runs/{run_id}", response_model=RunStatus)
def get_teaching_action(run_id: str, db: Store = Depends(get_store)) -> RunStatus:
    action = db.get_action(run_id)
    if action is None:
        raise HTTPException(status_code=404, detail={"code": "action_not_found", "message": "Teaching action does not exist."})
    return action


@app.get("/v1/teaching-plans/{plan_id}", response_model=TeachingPlan)
def get_teaching_plan(plan_id: str, db: Store = Depends(get_store)) -> TeachingPlan:
    plan = db.get_teaching_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "teaching_plan_not_found", "message": "Teaching plan does not exist."})
    return plan


@app.get("/v1/actions/{action_id}/events")
def get_action_events(action_id: str, db: Store = Depends(get_store)) -> StreamingResponse:
    if db.get_action(action_id) is None:
        raise HTTPException(status_code=404, detail={"code": "action_not_found", "message": "Teaching action does not exist."})
    events = db.list_events(action_id)

    def stream():
        for item in events:
            payload = json.dumps(item.data, separators=(",", ":"), default=str)
            yield f"id: {item.id}\nevent: {item.type}\ndata: {payload}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/lessons/{lesson_id}")
def get_lesson(lesson_id: str, db: Store = Depends(get_store)):
    artifact = db.get_artifact(lesson_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "lesson_not_found", "message": "Lesson artifact does not exist."})
    return artifact


class ExplanationRequest(BaseModel):
    blockId: str
    selectedText: str = Field(min_length=1, max_length=1200)
    mode: Literal["explain", "simpler", "example", "symbols", "why"] = "explain"


@app.post("/v1/lessons/{lesson_id}/explanations")
def explain_lesson(lesson_id: str, request: ExplanationRequest, db: Store = Depends(get_store)):
    artifact = get_lesson(lesson_id, db)
    block = next((item for item in artifact.blocks if item.id == request.blockId), None)
    selected = " ".join(request.selectedText.split())
    if block is None or not selected or selected not in " ".join(f"{block.heading or ''} {block.body}".split()):
        raise HTTPException(status_code=422, detail={"message": "Select a passage from this lesson."})
    if lesson_provider is None or not hasattr(lesson_provider, "explain"):
        raise HTTPException(status_code=503, detail={"message": "Connect an AI provider to explore this passage."})
    try:
        guidance = {"explain": "Explain the passage intuitively, then show and interpret its mathematics.", "simpler": "Use simpler language and small steps, defining unfamiliar words.", "example": "Give a concrete worked numerical example when appropriate and interpret the result.", "symbols": "Define each symbol and its role. Then explain how the terms interact. Do not invent meanings that the context does not establish.", "why": "Derive the result one step at a time, naming the rule behind every transformation."}[request.mode]
        blocks = lesson_provider.explain(selected_text=selected, lesson_context=f"Requested teaching approach: {guidance}\n{artifact.title}\n{block.heading}\n{block.body}")
        return {"blocks": [{"heading": item.heading, "body": item.body} for item in blocks]}
    except ModelProviderError as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc)}) from exc
