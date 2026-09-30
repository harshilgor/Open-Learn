"""HTTP endpoints for Courses and roadmap management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from .course_models import (
    CourseCreate,
    CoursePublic,
    CourseRoadmapNode,
    CourseSummary,
    CourseUpdate,
    RoadmapGenerateRequest,
    RoadmapNodeCreate,
    RoadmapNodeUpdate,
    RoadmapProgressionResult,
    RoadmapReorderRequest,
)
from .course_service import CourseService
from .material_models import TextMaterial, UploadRequest
from .material_routes import material_owner
from .session_models import SessionSummary


def build_course_router(store_provider: Any, provider_getter: Any = None) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["courses"])

    def service(db=Depends(store_provider)) -> CourseService:
        provider = provider_getter() if provider_getter else None
        return CourseService(db, provider)

    @router.get("/courses", response_model=list[CourseSummary])
    def list_courses(
        include_archived: bool = Query(default=False),
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> list[CourseSummary]:
        return svc.list_courses(owner, include_archived=include_archived)

    @router.post("/courses", response_model=CoursePublic, status_code=status.HTTP_201_CREATED)
    def create_course(
        request: CourseCreate,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> CoursePublic:
        return svc.create_course(owner, request)

    @router.get("/courses/{course_id}", response_model=CoursePublic)
    def get_course(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> CoursePublic:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        return course

    @router.patch("/courses/{course_id}", response_model=CoursePublic)
    def update_course(
        course_id: str,
        request: CourseUpdate,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> CoursePublic:
        updated = svc.update_course(owner, course_id, request)
        if not updated:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        return updated

    @router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_course(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> None:
        if not svc.delete_course(owner, course_id):
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        return None

    @router.get("/courses/{course_id}/sessions")
    def list_course_sessions(
        course_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        sessions, total = svc.list_course_sessions(owner, course_id, limit, offset)
        return {
            "sessions": [
                SessionSummary(
                    id=item.id,
                    title=item.title or item.goal or "Untitled conversation",
                    goal=item.goal,
                    course_id=item.course_id,
                    updated_at=item.updated_at,
                    turn_count=svc.store.journey_turn_count(owner, item.id),
                ).to_summary_dict()
                for item in sessions
            ],
            "total": total,
        }

    @router.put("/courses/{course_id}/sessions/{session_id}")
    def add_course_session(
        course_id: str,
        session_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        if not svc.set_session_course(owner, course_id, session_id):
            raise HTTPException(status_code=404, detail={"code": "course_or_session_not_found", "message": "Course or chat does not exist."})
        return {"courseId": course_id, "sessionId": session_id}

    @router.delete("/courses/{course_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_course_session(
        course_id: str,
        session_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> None:
        if not svc.set_session_course(owner, course_id, session_id, remove=True):
            raise HTTPException(status_code=404, detail={"code": "course_or_session_not_found", "message": "Course or chat does not exist."})
        return None

    @router.get("/courses/{course_id}/notes")
    def list_course_notes(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        notes = svc.list_course_notes(owner, course_id)
        return {
            "notes": [note.model_dump(mode="json", by_alias=True) for note in notes],
            "total": len(notes),
        }

    @router.get("/courses/{course_id}/materials")
    def list_course_materials(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        materials = svc.list_course_materials(owner, course_id)
        return {"materials": materials, "total": len(materials)}

    @router.post("/courses/{course_id}/materials/text", status_code=status.HTTP_201_CREATED)
    def add_course_text_material(
        course_id: str,
        request: TextMaterial,
        tasks: BackgroundTasks,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        from .material_service import MaterialService
        mat_svc = MaterialService(svc.store)
        content = request.text.encode("utf-8")
        item = mat_svc.create(owner, UploadRequest(title=request.title, media_type="text/plain", byte_count=len(content), role=request.role, course_id=course_id))
        result = mat_svc.upload(owner, item["materialId"], item["versionId"], content)
        tasks.add_task(mat_svc.process_one)
        return result

    @router.post("/courses/{course_id}/materials/{material_id}/attach")
    def attach_course_material(
        course_id: str,
        material_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        if not svc.attach_material_to_course(owner, course_id, material_id):
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Course or material does not exist."})
        return {"status": "attached", "courseId": course_id, "materialId": material_id}

    @router.delete("/courses/{course_id}/materials/{material_id}")
    def detach_course_material(
        course_id: str,
        material_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> dict:
        if not svc.detach_material_from_course(owner, course_id, material_id):
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Course or material does not exist."})
        return {"status": "detached", "courseId": course_id, "materialId": material_id}

    @router.get("/courses/{course_id}/roadmap", response_model=list[CourseRoadmapNode])
    def get_roadmap(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> list[CourseRoadmapNode]:
        course = svc.get_course(owner, course_id)
        if not course:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not exist."})
        return course.roadmap

    @router.post("/courses/{course_id}/roadmap/generate", response_model=list[CourseRoadmapNode])
    def generate_roadmap(
        course_id: str,
        request: RoadmapGenerateRequest | None = None,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> list[CourseRoadmapNode]:
        prompt = request.prompt if request else None
        replace_existing = request.replace_existing if request else True
        try:
            return svc.generate_tailored_roadmap(owner, course_id, prompt=prompt, replace_existing=replace_existing)
        except ValueError as err:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": str(err)})

    @router.post("/courses/{course_id}/roadmap/nodes", response_model=CourseRoadmapNode, status_code=status.HTTP_201_CREATED)
    def add_roadmap_node(
        course_id: str,
        request: RoadmapNodeCreate,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> CourseRoadmapNode:
        try:
            return svc.add_roadmap_node(owner, course_id, request)
        except ValueError as err:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": str(err)})

    @router.patch("/courses/{course_id}/roadmap/{node_id}", response_model=CourseRoadmapNode)
    @router.patch("/courses/{course_id}/roadmap/nodes/{node_id}", response_model=CourseRoadmapNode)
    def update_roadmap_node(
        course_id: str,
        node_id: str,
        request: RoadmapNodeUpdate,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> CourseRoadmapNode:
        updated = svc.update_roadmap_node(owner, course_id, node_id, request)
        if not updated:
            raise HTTPException(status_code=404, detail={"code": "node_not_found", "message": "Roadmap node does not exist."})
        return updated

    @router.delete("/courses/{course_id}/roadmap/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
    @router.delete("/courses/{course_id}/roadmap/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_roadmap_node(
        course_id: str,
        node_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> None:
        if not svc.delete_roadmap_node(owner, course_id, node_id):
            raise HTTPException(status_code=404, detail={"code": "node_not_found", "message": "Roadmap node does not exist."})
        return None

    @router.post("/courses/{course_id}/roadmap/reorder", response_model=list[CourseRoadmapNode])
    def reorder_roadmap(
        course_id: str,
        request: RoadmapReorderRequest,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> list[CourseRoadmapNode]:
        try:
            return svc.reorder_roadmap_nodes(owner, course_id, request.node_ids)
        except ValueError as err:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": str(err)})

    @router.post("/courses/{course_id}/roadmap/evaluate", response_model=RoadmapProgressionResult)
    def evaluate_roadmap_progression(
        course_id: str,
        owner: str = Depends(material_owner),
        svc: CourseService = Depends(service),
    ) -> RoadmapProgressionResult:
        try:
            return svc.evaluate_roadmap_progression(owner, course_id)
        except ValueError as err:
            raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": str(err)})

    return router
