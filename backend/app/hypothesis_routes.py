"""Student-visible possible explanations and short diagnostic checks."""
from fastapi import APIRouter, Depends
from .material_routes import material_owner
from .hypothesis_service import HypothesisService, SelfReport


def build_hypothesis_router(store_provider, provider_getter):
    router = APIRouter(prefix="/v1/hypotheses", tags=["hypotheses"])
    def service(db=Depends(store_provider)):
        return HypothesisService(db, provider_getter())

    @router.get("")
    def listing(concept_id: str | None = None, owner=Depends(material_owner), svc=Depends(service)):
        return {"hypotheses": svc.listing(owner, concept_id)}

    @router.get("/recommendation/{concept_id}")
    def recommendation(concept_id: str, owner=Depends(material_owner), svc=Depends(service)):
        return svc.recommendation(owner, concept_id)

    @router.get("/{hypothesis_id}/history")
    def history(hypothesis_id: str, owner=Depends(material_owner), svc=Depends(service)):
        return {"revisions": svc.history(owner, hypothesis_id)}

    @router.post("/{hypothesis_id}/self-report")
    def report(hypothesis_id: str, command: SelfReport, owner=Depends(material_owner), svc=Depends(service)):
        return svc.self_report(owner, hypothesis_id, command)

    @router.post("/{hypothesis_id}/check")
    def check(hypothesis_id: str, owner=Depends(material_owner), svc=Depends(service)):
        return svc.start_check(owner, hypothesis_id)

    return router
