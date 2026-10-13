from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .database import database_url
from .graph_generator import GraphGenerator
from .learner_graph import LearnerGraphRepository, build_learner_graph_router
from .learning_kernel import build_lesson, classify_intent, resolve_concept
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
    SessionGearUpdate,
    TeachingActionInput,
)
from .state_models import StateEventCreate
from .state_routes import build_state_router
from .agent_routes import build_agent_router
from .state_service import LearnerStateService
from .storage import Store

app = FastAPI(title="AI Tutor Harness API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
store = Store(database_url())
generator = GraphGenerator()


def get_store() -> Store:
    return store


# The learner graph is a separate cross-topic projection.  Its routes use the
# same persistence connection, while its schema and projection logic remain
# isolated from the topic graph API above.
app.include_router(build_learner_graph_router(get_store))
app.include_router(build_state_router(get_store))
app.include_router(build_agent_router(get_store))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "learning-harness", "graph_provider": generator.provider_name}


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
def create_learning_session(request: SessionCreate, db: Store = Depends(get_store)) -> LearningSession:
    """Pin a learning session to a graph revision for resumable actions."""
    graph_id = request.graph_id
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
    session = LearningSession(
        id=f"session_{uuid4().hex}",
        learner_id=request.learner_id,
        graph_id=graph.id,
        graph_revision=request.graph_revision or graph.version,
        goal=request.goal,
        gear=request.gear,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    # Keep the learner's single cross-topic map current as soon as a session
    # starts. Repeated imports are deduplicated by LearnerGraphRepository.
    LearnerGraphRepository(db).import_topic_graph(session.learner_id, graph)
    db.save_session(session)
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


@app.get("/v1/sessions/{session_id}", response_model=LearningSession)
def get_learning_session(session_id: str, db: Store = Depends(get_store)) -> LearningSession:
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    return session


@app.patch("/v1/sessions/{session_id}/gear", response_model=LearningSession)
def update_session_gear(session_id: str, request: SessionGearUpdate, db: Store = Depends(get_store)) -> LearningSession:
    """Persist a preference for future actions without rewriting existing lessons."""
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": "Learning session does not exist."})
    if request.expected_state_version is not None and request.expected_state_version != session.state_version:
        raise HTTPException(status_code=409, detail={"code": "stale_session", "message": "The session changed; reload it before changing Teaching Gear."})
    updated = session.model_copy(update={"gear": request.gear, "state_version": session.state_version + 1, "updated_at": utc_now()})
    db.save_session(updated)
    return updated


@app.post("/v1/sessions/{session_id}/actions", response_model=RunStatus, status_code=status.HTTP_202_ACCEPTED)
def create_teaching_action(
    session_id: str,
    request: TeachingActionInput,
    db: Store = Depends(get_store),
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
    if request.expected_state_version is not None and request.expected_state_version != session.state_version:
        raise HTTPException(status_code=409, detail={"code": "stale_session", "message": "The session changed; reload it before sending this action."})
    if idempotency_key:
        existing = db.get_action_by_idempotency(session_id, idempotency_key)
        if existing is not None:
            return existing
    if request.supersedes_action_id:
        superseded = db.get_action(request.supersedes_action_id)
        if superseded and superseded.session_id == session.id and superseded.status not in {ActionStatus.qualified_response, ActionStatus.delivered, ActionStatus.failed, ActionStatus.cancelled}:
            cancelled = superseded.model_copy(update={"status": ActionStatus.cancelled, "message": "Replaced by a newer action for this anchor.", "updated_at": utc_now()})
            db.save_action(cancelled)
            _event(db, cancelled.run_id, 98, "action.cancelled", {"superseded_by": "pending"})
    graph = db.get_graph(session.graph_id)
    if graph is None:
        raise HTTPException(status_code=409, detail={"code": "graph_unavailable", "message": "The session's graph is no longer available."})

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
        concept = resolve_concept(graph, request.concept_id)
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
            has_block_anchor=bool(request.parent_block_id or request.anchor and request.anchor.block_id),
            has_selection_anchor=bool(request.anchor and request.anchor.selected_text),
            is_branch=bool(request.parent_lesson_id),
        )
        action = action.model_copy(update={"status": ActionStatus.context_ready, "progress": 30, "action_context": action_context, "message": "Graph, position, gear, evidence, and intent context assembled.", "updated_at": utc_now()})
        db.save_action(action, idempotency_key)
        _event(db, action_id, 2, "context.ready", {
            "graph_id": graph.id,
            "concept_id": concept.id,
            "graph_revision": graph.version,
            "learner_state_version": action_context.learner_evidence.state_version,
            "profile": action_context.teaching_profile.model_dump(mode="json", by_alias=True),
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
            graph, concept, request, session.id, intent, session.graph_revision, action_id, action_context, plan
        )
        db.save_artifact(artifact)
        _event(db, action_id, 5, "artifact.created", {"lesson_id": artifact.id, "plan_id": plan.id, "block_count": len(artifact.blocks)})
        action = action.model_copy(update={"status": ActionStatus.generated, "progress": 70, "lesson": artifact, "message": "Structured lesson created.", "updated_at": utc_now()})
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
        updated_session = session.model_copy(update={"current_concept_id": concept.id, "current_lesson_id": artifact.id, "state_version": session.state_version + 1, "updated_at": utc_now()})
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
        return action
    except HTTPException:
        raise
    except Exception as exc:
        failed = action.model_copy(update={"status": ActionStatus.failed, "progress": 0, "message": "Teaching action failed; retry is safe.", "updated_at": utc_now()})
        db.save_action(failed, idempotency_key)
        _event(db, action_id, 99, "action.failed", {"code": "teaching_action_failed", "detail": str(exc)})
        raise HTTPException(status_code=500, detail={"code": "teaching_action_failed", "message": "Teaching action failed; retry is safe."}) from exc


@app.get("/v1/runs/{run_id}", response_model=RunStatus)
def get_teaching_action(run_id: str, db: Store = Depends(get_store)) -> RunStatus:
    action = db.get_action(run_id)
    if action is None:
        raise HTTPException(status_code=404, detail={"code": "action_not_found", "message": "Teaching action does not exist."})
    return action


@app.post("/v1/runs/{run_id}/cancel", response_model=RunStatus)
def cancel_teaching_action(run_id: str, db: Store = Depends(get_store)) -> RunStatus:
    """Cancel a pending action. Completed artifacts are immutable history."""
    action = db.get_action(run_id)
    if action is None:
        raise HTTPException(status_code=404, detail={"code": "action_not_found", "message": "Teaching action does not exist."})
    if action.status in {ActionStatus.qualified_response, ActionStatus.delivered, ActionStatus.failed, ActionStatus.cancelled}:
        return action
    cancelled = action.model_copy(update={"status": ActionStatus.cancelled, "message": "Action cancelled.", "updated_at": utc_now()})
    db.save_action(cancelled)
    _event(db, run_id, 98, "action.cancelled", {"reason": "learner_cancelled"})
    return cancelled


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
