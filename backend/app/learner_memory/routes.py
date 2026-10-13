"""Learner-facing memory APIs (spec §10). Read APIs and settings land in Phase B."""
from __future__ import annotations

from fastapi import APIRouter, Response

from ..identity import assert_owner_active, current_principal, fail
from . import policy, store
from .models import MemorySettingsUpdate, public_episode, public_fact, public_settings


def _private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


def build_learner_memory_router(store_provider):
    router = APIRouter(prefix="/v1/memory", tags=["memory"])

    @router.get("/facts")
    def facts(response: Response, status: str | None = None, kind: str | None = None, course_id: str | None = None,
              generation_id: str | None = None):
        _private(response)
        if generation_id is not None:
            # What one chat turn saved, for the "Saved to memory" chip.
            owner = current_principal().owner_id
            with store_provider().engine.connect() as conn:
                assert_owner_active(conn, owner)
                items = store.facts_for_generation(conn, owner, generation_id)
            return {"items": [public_fact(fact) for fact in items]}
        if status is not None and (status not in policy.FACT_STATUSES or status == "shadow"):
            fail("invalid_memory_status", "Unknown memory status.", 422)
        if kind is not None and kind not in policy.FACT_KINDS:
            fail("invalid_memory_kind", "Unknown memory kind.", 422)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            items = store.list_facts(conn, owner, status=status, kind=kind, course_id=course_id)
        return {"items": [public_fact(fact) for fact in items]}

    @router.get("/facts/{fact_id}/history")
    def history(fact_id: str, response: Response):
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            chain = store.fact_history(conn, owner, fact_id)
        if chain is None:
            fail("memory_not_found", "This memory is unavailable.", 404)
        return {"items": [public_fact(fact) for fact in chain]}

    @router.delete("/facts/{fact_id}")
    def forget(fact_id: str, response: Response, undo: bool = False):
        """Hard delete (§9.1). Undo also restores what this fact replaced, within 24 h."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            restored = store.undo_fact(conn, owner, fact_id, window_seconds=86400 if undo else -1)
            if restored is None:
                fail("memory_not_found", "This memory is unavailable.", 404)
        return {"status": "deleted", "restored": restored}

    @router.get("/episodes")
    def episodes(response: Response, course_id: str | None = None):
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            items = store.list_episodes(conn, owner, course_id=course_id)
        return {"items": [public_episode(item) for item in items]}

    @router.delete("/episodes/{episode_id}")
    def delete_episode(episode_id: str, response: Response):
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            if not store.delete_episode(conn, owner, episode_id):
                fail("memory_not_found", "This memory is unavailable.", 404)
        return {"status": "deleted"}

    @router.get("/settings")
    def settings(response: Response):
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            settings = store.get_settings(conn, owner)
        # Shadow extraction is invisible to learners, so it reads as "off".
        return {**public_settings(settings), "extraction": "on" if policy.extraction_mode() == "on" and policy.extraction_enabled() else "off"}

    @router.put("/settings")
    def update_settings(body: MemorySettingsUpdate, response: Response):
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            updated = store.put_settings(conn, owner, learning_enabled=body.learning_enabled,
                                         expected_revision=body.expected_revision)
        if updated is None:
            fail("revision_conflict", "Memory settings changed. Refresh and try again.", 409)
        return public_settings(updated)

    return router
