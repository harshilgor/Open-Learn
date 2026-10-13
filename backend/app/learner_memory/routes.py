"""Learner-facing memory APIs (spec §10). Read APIs and settings land in Phase B; profile and changes in Phase E."""
from __future__ import annotations

import time

from fastapi import APIRouter, Response

from ..identity import assert_owner_active, current_principal, fail
from . import consolidation, policy, profile, store
from .models import MemorySettingsUpdate, public_episode, public_fact, public_settings


# Fact changes, then session summaries, which name their own noun.
CHANGE_LABELS = (("learned", "learned"), ("updated", "updated"), ("merged", "merged"), ("promoted", "confirmed by use"),
                 ("archived", "archived"), ("expired", "expired"), ("needsReview", "need your review"))


def change_summary(counts: dict) -> str:
    """"3 memories archived, 1 updated": learner-facing, content-free."""
    parts = [(counts[key], label) for key, label in CHANGE_LABELS if counts.get(key)]
    text = ""
    if parts:
        (first, label), rest = parts[0], parts[1:]
        text = ", ".join([f"{first} {'memory' if first == 1 else 'memories'} {label}"] + [f"{count} {label}" for count, label in rest])
    episodes = counts.get("episodesArchived")
    if episodes:
        text += (", " if text else "") + f"{episodes} session {'summary' if episodes == 1 else 'summaries'} archived"
    return text


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
            profile.rebuild_if_enabled(conn, owner)
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

    @router.get("/profile")
    def core_profile(response: Response):
        """The core profile (§9.3 step 6): stored when consolidation runs, else a live preview."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            active = {fact["id"]: fact for fact in store.facts_with_status(conn, owner, {"active"})}
            saved = profile.stored(conn, owner) if policy.consolidation_enabled() else None
        payload = saved or profile.build(list(active.values()), time.time())
        items = [active[identifier] for identifier in payload["factIds"] if identifier in active]
        return {"source": "stored" if saved else "preview", "policyVersion": payload["policyVersion"],
                "text": "\n".join(profile.line(fact) for fact in items), "items": [public_fact(fact) for fact in items]}

    @router.get("/changes")
    def recent_changes(response: Response):
        """Recent consolidation and learning changes; counts and IDs only."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            entries = consolidation.changes(conn, owner)
        return {"items": [{**entry, "summary": change_summary(entry["counts"])} for entry in entries]}

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
