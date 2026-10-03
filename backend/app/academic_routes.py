"""Typed owner-scoped academic, readiness and planning API."""
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .material_routes import material_owner
from .academic_planning import AcademicPlanningService, AcademicError

class ObservationCommand(BaseModel):
    kind: Literal['assignment', 'assessment', 'term', 'coverage']
    fields: dict[str, Any]
    source: dict[str, Any]
    origin: Literal['manual', 'canvas', 'lecture', 'syllabus', 'announcement'] = 'manual'
    externalId: str | None = None
    entityId: str | None = None
    idempotencyKey: str | None = None
    observedAt: str | None = None
    confirmation: Literal['confirmed', 'tentative', 'inferred'] = 'confirmed'
    override: bool = False
    reason: str | None = None
    negated: bool = False

class TaskCommand(BaseModel):
    id: str | None = None
    action: Literal['diagnostic', 'retrieval', 'repair', 'transfer', 'assignment']
    conceptIds: list[str] = Field(default_factory=list, max_length=30)
    capability: str = 'recall'
    entityId: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    duration: list[int] = Field(default_factory=lambda: [8, 15], min_length=2, max_length=2)
    prerequisites: list[str] = Field(default_factory=list, max_length=30)
    sourceBasis: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    due: dict[str, Any] | None = None

class TaskAction(BaseModel):
    status: Literal['accepted', 'scheduled', 'active', 'completed', 'skipped', 'cancelled'] | None = None
    pinned: bool | None = None
    workflowId: str | None = None
    evidenceIds: list[str] = Field(default_factory=list, max_length=50)
    revision: int

class Window(BaseModel):
    start: str
    end: str

class PlanCommand(BaseModel):
    timezone: str
    windows: list[Window] = Field(max_length=100)
    protected: list[Window] = Field(default_factory=list, max_length=100)
    autoAdjust: bool = False
    reason: str = 'Availability changed.'

class RevisionCommand(BaseModel):
    revision: int

def build_academic_router(store_provider):
    router = APIRouter(prefix='/v1/courses/{course_id}/academic', tags=['academic-planning'])
    def service(db=Depends(store_provider)): return AcademicPlanningService(db)
    def call(fn):
        try: return fn()
        except AcademicError as exc: raise HTTPException(exc.status, detail={'code': exc.code, 'message': str(exc)}) from exc
        except (ValueError, KeyError) as exc: raise HTTPException(422, detail={'code': 'invalid_academic_input', 'message': str(exc)}) from exc
    @router.get('')
    def view(course_id: str, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.view(owner, course_id))
    @router.post('/observations')
    def observation(course_id: str, command: ObservationCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.ingest(owner, course_id, command.model_dump(exclude_none=True)))
    @router.post('/assessments/{assessment_id}/readiness')
    def readiness(course_id: str, assessment_id: str, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.readiness(owner, course_id, assessment_id))
    @router.post('/assessments/{assessment_id}/tasks')
    def generate(course_id: str, assessment_id: str, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.generate(owner, course_id, assessment_id))
    @router.post('/tasks')
    def task(course_id: str, command: TaskCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.create_task(owner, course_id, command.model_dump(exclude_none=True)))
    @router.patch('/tasks/{task_id}')
    def action(course_id: str, task_id: str, command: TaskAction, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.task_action(owner, course_id, task_id, command.model_dump(exclude_none=True)))
    @router.get('/advice')
    def advice(course_id: str, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.advice(owner, course_id))
    @router.post('/plans')
    def plan(course_id: str, command: PlanCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.plan(owner, course_id, command.model_dump()))
    @router.post('/plans/{plan_id}/accept')
    def accept(course_id: str, plan_id: str, command: RevisionCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.accept_plan(owner, course_id, plan_id, command.revision))
    return router
