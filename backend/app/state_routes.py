"""FastAPI routes for the durable learner-state slice."""

from __future__ import annotations

import os
from .local_identity import local_identity_enabled
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Response, status

from .adaptive_observability import (
    ActivityCorrelationReport,
    AdaptiveObservabilityError,
    AdaptiveObservabilityService,
    ClosedLoopChain,
    ConceptSourceComparison,
    ImmediateAdaptationInput,
)
from .state_models import (
    BranchCreate,
    BranchContextResponse,
    BranchRecord,
    BranchUpdate,
    EvidenceAdmissionResponse,
    EvidenceCreate,
    EvidenceRecord,
    EvidenceChallenge,
    EvidenceChallengeCreate,
    ConceptStateExplanation,
    LearnerStateResponse,
    NoteCreate,
    NoteRecord,
    NoteRevision,
    NoteUpdate,
    ReviewSchedule,
    StateEvent,
    StateEventCreate,
    TimelinePage,
)
from .state_service import LearnerStateService, StateServiceError


def build_state_router(store_provider: Any) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["learner-state"])

    def learner_path() -> Any:
        return Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")

    def authorize(learner_id: str, claimed: str | None) -> None:
        """Prevent accidental cross-learner access in local development.

        This is intentionally not presented as authentication. A hosted service
        must disable development identity and replace this check with a trusted
        auth-derived learner ID.
        """

        if not local_identity_enabled():
            raise HTTPException(status_code=503, detail={"code": "authentication_required", "message": "Development identity is disabled; configure an authentication provider."})
        effective = claimed or "local"
        if effective != learner_id:
            raise HTTPException(status_code=403, detail={"code": "learner_scope_mismatch", "message": "X-Dev-Learner-Id must match the learner path."})

    def service() -> LearnerStateService:
        return LearnerStateService(store_provider())

    def adaptive_service() -> AdaptiveObservabilityService:
        return AdaptiveObservabilityService(store_provider())

    def translate(operation):  # type: ignore[no-untyped-def]
        try:
            return operation()
        except (StateServiceError, AdaptiveObservabilityError) as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    @router.get("/learners/{learner_id}/state", response_model=LearnerStateResponse)
    def get_state(learner_id: str = learner_path(), x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> LearnerStateResponse:
        authorize(learner_id, x_dev_learner_id)
        return service().get_state(learner_id)

    @router.get("/learners/{learner_id}/state/{concept_id}/explanation", response_model=ConceptStateExplanation)
    def explain_state(concept_id: str, learner_id: str = learner_path(), x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> ConceptStateExplanation:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().explain_state(learner_id, concept_id))

    @router.get("/learners/{learner_id}/timeline", response_model=TimelinePage)
    def timeline(learner_id: str = learner_path(), cursor: str | None = Query(default=None, max_length=400), limit: int = Query(default=30, ge=1, le=100), x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> TimelinePage:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().timeline(learner_id, cursor, limit))

    @router.get("/learners/{learner_id}/adaptive/policy-input", response_model=ImmediateAdaptationInput)
    def adaptive_policy_input(
        session_id: str = Query(alias="sessionId", min_length=1, max_length=160),
        concept_id: str | None = Query(default=None, alias="conceptId", max_length=160),
        learner_id: str = learner_path(),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> ImmediateAdaptationInput:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: adaptive_service().policy_input(learner_id, session_id, concept_id))

    @router.get("/learners/{learner_id}/adaptive/concepts/{concept_id}/sources", response_model=ConceptSourceComparison)
    def adaptive_concept_sources(
        concept_id: str,
        learner_id: str = learner_path(),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> ConceptSourceComparison:
        authorize(learner_id, x_dev_learner_id)
        return adaptive_service().compare_concept_sources(learner_id, concept_id)

    @router.get("/learners/{learner_id}/adaptive/activity-correlations", response_model=ActivityCorrelationReport)
    def adaptive_activity_correlations(
        learner_id: str = learner_path(),
        limit: int = Query(default=100, ge=1, le=200),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> ActivityCorrelationReport:
        authorize(learner_id, x_dev_learner_id)
        return adaptive_service().activity_correlations(learner_id, limit)

    @router.get("/learners/{learner_id}/adaptive/closed-loop", response_model=ClosedLoopChain)
    def adaptive_closed_loop(
        session_id: str = Query(alias="sessionId", min_length=1, max_length=160),
        concept_id: str | None = Query(default=None, alias="conceptId", max_length=160),
        learner_id: str = learner_path(),
        x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
    ) -> ClosedLoopChain:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: adaptive_service().closed_loop_chain(learner_id, session_id, concept_id))

    @router.post("/learners/{learner_id}/evidence/{evidence_id}/challenge", response_model=EvidenceChallenge, status_code=status.HTTP_201_CREATED)
    def challenge_evidence(request: EvidenceChallengeCreate, evidence_id: str, learner_id: str = learner_path(), x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> EvidenceChallenge:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().challenge_evidence(learner_id, evidence_id, request.reason))

    @router.post("/learners/{learner_id}/events", response_model=StateEvent, status_code=status.HTTP_201_CREATED)
    def append_event(request: StateEventCreate, learner_id: str = learner_path(),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> StateEvent:
        authorize(learner_id, x_dev_learner_id)
        if idempotency_key:
            request = request.model_copy(update={"idempotency_key": idempotency_key})
        event, _ = service().append_event(learner_id, request)
        return event

    @router.get("/learners/{learner_id}/events", response_model=list[StateEvent])
    def list_events(learner_id: str = learner_path(), limit: int = Query(default=100, ge=1, le=200),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[StateEvent]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_events(learner_id, limit)

    @router.post("/learners/{learner_id}/evidence", response_model=EvidenceAdmissionResponse, status_code=status.HTTP_201_CREATED)
    def admit_evidence(request: EvidenceCreate, learner_id: str = learner_path(),
                       x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id"),
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> EvidenceAdmissionResponse:
        authorize(learner_id, x_dev_learner_id)
        if idempotency_key:
            request = request.model_copy(update={"evidence_key": idempotency_key})
        return service().admit_evidence(learner_id, request)

    @router.get("/learners/{learner_id}/evidence", response_model=list[EvidenceRecord])
    def list_evidence(learner_id: str = learner_path(), limit: int = Query(default=100, ge=1, le=200),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[EvidenceRecord]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_evidence(learner_id, limit)

    @router.get("/learners/{learner_id}/review-queue", response_model=list[ReviewSchedule])
    def review_queue(learner_id: str = learner_path(), as_of: datetime | None = Query(default=None),
                     include_future: bool = Query(default=False),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[ReviewSchedule]:
        authorize(learner_id, x_dev_learner_id)
        return service().review_queue(learner_id, as_of, include_future)

    @router.post("/learners/{learner_id}/branches", response_model=BranchRecord, status_code=status.HTTP_201_CREATED)
    def create_branch(request: BranchCreate, learner_id: str = learner_path(),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().create_branch(learner_id, request))

    @router.get("/learners/{learner_id}/branches/{branch_id}", response_model=BranchRecord)
    def get_branch(branch_id: str, learner_id: str = learner_path(),
                   x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get_branch(learner_id, branch_id))

    @router.get("/learners/{learner_id}/branches", response_model=list[BranchRecord])
    def list_branches(learner_id: str = learner_path(), session_id: str | None = Query(default=None, max_length=160),
                      include_closed: bool = Query(default=False),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[BranchRecord]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_branches(learner_id, session_id, include_closed)

    @router.get("/learners/{learner_id}/branches/{branch_id}/context", response_model=BranchContextResponse)
    def get_branch_context(branch_id: str, learner_id: str = learner_path(),
                           x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchContextResponse:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get_branch_context(learner_id, branch_id))

    @router.patch("/learners/{learner_id}/branches/{branch_id}", response_model=BranchRecord)
    def update_branch(request: BranchUpdate, branch_id: str, learner_id: str = learner_path(),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().update_branch(learner_id, branch_id, request))

    @router.post("/learners/{learner_id}/branches/{branch_id}/close", response_model=BranchRecord)
    def close_branch(branch_id: str, learner_id: str = learner_path(),
                     x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().close_branch(learner_id, branch_id))

    @router.post("/learners/{learner_id}/branches/{branch_id}/cancel", response_model=BranchRecord)
    def cancel_branch(branch_id: str, learner_id: str = learner_path(),
                      x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> BranchRecord:
        """Cancel an in-flight sidecar using the same idempotent close transition."""
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().close_branch(learner_id, branch_id))

    @router.post("/learners/{learner_id}/notes", response_model=NoteRecord, status_code=status.HTTP_201_CREATED)
    def create_note(request: NoteCreate, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> NoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().create_note(learner_id, request))

    @router.get("/learners/{learner_id}/notes", response_model=list[NoteRecord])
    def list_notes(learner_id: str = learner_path(),
                   x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[NoteRecord]:
        authorize(learner_id, x_dev_learner_id)
        return service().list_notes(learner_id)

    @router.get("/learners/{learner_id}/notes/{note_id}", response_model=NoteRecord)
    def get_note(note_id: str, learner_id: str = learner_path(),
                 x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> NoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().get_note(learner_id, note_id))

    @router.patch("/learners/{learner_id}/notes/{note_id}", response_model=NoteRecord)
    def update_note(request: NoteUpdate, note_id: str, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> NoteRecord:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().update_note(learner_id, note_id, request))

    @router.get("/learners/{learner_id}/notes/{note_id}/revisions", response_model=list[NoteRevision])
    def note_revisions(note_id: str, learner_id: str = learner_path(),
                       x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> list[NoteRevision]:
        authorize(learner_id, x_dev_learner_id)
        return translate(lambda: service().note_revisions(learner_id, note_id))

    @router.delete("/learners/{learner_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_note(note_id: str, learner_id: str = learner_path(),
                    x_dev_learner_id: str | None = Header(default=None, alias="X-Dev-Learner-Id")) -> Response:
        authorize(learner_id, x_dev_learner_id)
        translate(lambda: service().delete_note(learner_id, note_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
