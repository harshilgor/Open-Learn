"""Authenticated change-feed API for unified usage snapshots."""

from fastapi import APIRouter, Depends, Query, Response

from .material_routes import material_owner
from .usage.outbox import UsageOutbox


def build_usage_events_router(store_provider):
    router = APIRouter(prefix="/v1")

    @router.get("/usage/events")
    def events(
        response: Response,
        after_revision: int = Query(default=0, alias="afterRevision", ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        owner: str = Depends(material_owner),
    ):
        response.headers["Cache-Control"] = "private, no-store"
        return UsageOutbox(store_provider()).after(owner, after_revision, limit)

    return router
