"""Authenticated personal concept review. No shared curriculum mutation API."""
from fastapi import APIRouter, Depends, Query
from pydantic import Field
from typing import Literal
from .material_routes import material_owner
from .shared_contracts import Contract, Revision
from .stable_concept_models import (ConceptCreate, CourseMappingCreate, RelationshipCreate, ReviewCommand, LegacyMappingCreate, ConceptChange, MappingReport, RubricMappingCreate)
from .stable_concept_service import StableConceptService


class AttributionRequest(Contract):
    question_revision: Revision
    outcomes: dict[str, Literal["correct", "incorrect", "partial", "unknown"]] = Field(max_length=50)


def build_stable_concept_router(store_provider, provider_getter=None):
    router = APIRouter(prefix="/v1/concepts", tags=["stable-concepts"])

    def service(db=Depends(store_provider)):
        return StableConceptService(db, provider_getter() if provider_getter else None)

    @router.get("")
    def graph(revision: int | None = Query(default=None, ge=1), owner=Depends(material_owner), svc=Depends(service)):
        return svc.graph(owner, revision)

    @router.post("")
    def create(command: ConceptCreate, owner=Depends(material_owner), svc=Depends(service)):
        return svc.create(owner, command)

    @router.get("/resolve")
    def resolve(query: str = Query(default="", max_length=1000), course_id: str | None = None, explicit_id: str | None = None, owner=Depends(material_owner), svc=Depends(service)):
        return svc.resolve(owner, query, course_id, explicit_id)

    @router.post("/course-mappings")
    def course_mapping(command: CourseMappingCreate, owner=Depends(material_owner), svc=Depends(service)):
        return svc.map_course(owner, command)

    @router.post("/relationships")
    def propose(command: RelationshipCreate, owner=Depends(material_owner), svc=Depends(service)):
        return svc.propose_relationship(owner, command)

    @router.post("/relationships/{relationship_id}/review")
    def review(relationship_id: str, command: ReviewCommand, owner=Depends(material_owner), svc=Depends(service)):
        return svc.review_relationship(owner, relationship_id, command)

    @router.post("/identity-changes")
    def identity_change(command: ConceptChange, owner=Depends(material_owner), svc=Depends(service)):
        return svc.change_identity(owner, command)

    @router.post("/legacy-mappings")
    def legacy(command: LegacyMappingCreate, owner=Depends(material_owner), svc=Depends(service)):
        return svc.map_legacy(owner, command)

    @router.post("/reports")
    def report(command: MappingReport, owner=Depends(material_owner), svc=Depends(service)):
        return svc.report(owner, command)

    @router.post("/rubric-mappings")
    def rubric(command: RubricMappingCreate, owner=Depends(material_owner), svc=Depends(service)):
        return svc.map_rubric(owner, command)

    @router.post("/rubric-mappings/{question_id}/attribution")
    def attribute(question_id: str, command: AttributionRequest, owner=Depends(material_owner), svc=Depends(service)):
        return svc.attribution(owner, question_id, command.question_revision, command.outcomes)

    @router.get("/{concept_id}/prerequisites")
    def prerequisites(concept_id: str, depth: int = Query(default=3, ge=0, le=8), limit: int = Query(default=20, ge=1, le=100), owner=Depends(material_owner), svc=Depends(service)):
        return svc.prerequisites(owner, concept_id, depth, limit)

    return router
