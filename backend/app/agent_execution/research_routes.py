"""Owner-scoped source inspection and erasure for saved research reports."""
from fastapi import APIRouter, Depends, HTTPException

from ..material_routes import material_owner
from .research_contracts import ResearchUnavailable
from .research_sources import ResearchSources


def build_research_router(store_provider):
    router = APIRouter(prefix="/v1/assistant", tags=["agent-research"])

    @router.get("/tasks/{task_id}/sources")
    def list_sources(task_id: str, owner=Depends(material_owner), store=Depends(store_provider)):
        return {"sources": ResearchSources(store).list(owner, task_id)}

    @router.get("/sources/{source_id}")
    def get_source(source_id: str, owner=Depends(material_owner), store=Depends(store_provider)):
        try:
            return ResearchSources(store).read(owner, source_id, include_excerpt=True)
        except ResearchUnavailable as exc:
            raise HTTPException(status_code=410, detail={"code": exc.code, "message": "Source content is no longer available."}) from None

    @router.delete("/sources/{source_id}", status_code=204)
    def delete_source(source_id: str, owner=Depends(material_owner), store=Depends(store_provider)):
        ResearchSources(store).delete(owner, source_id)

    return router
