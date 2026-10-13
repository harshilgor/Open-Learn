"""Learner-facing memory APIs (spec §10). Read APIs and settings land in Phase B; profile and changes in Phase E;
learner edits, confirmation, manual facts, the sensitive opt-in and forget-all in Phase F."""
from __future__ import annotations

import time

from fastapi import APIRouter, Response

from ..identity import assert_owner_active, current_principal, fail
from . import consolidation, policy, profile, store, validator
from .models import (FactConfirm, FactCreate, FactEdit, ForgetAll, MemorySettingsUpdate, SensitiveUpdate, public_episode, public_fact,
                     public_settings)


# Fact changes, then session summaries, which name their own noun.
CHANGE_LABELS = (("learned", "learned"), ("added", "added by you"), ("edited", "edited by you"), ("confirmed", "confirmed by you"),
                 ("updated", "updated"), ("merged", "merged"), ("promoted", "confirmed by use"), ("archived", "archived"),
                 ("expired", "expired"), ("forgotten", "forgotten"), ("needsReview", "need your review"))
EPISODE_LABELS = (("episodesArchived", "archived"), ("episodesForgotten", "forgotten"))


def change_summary(counts: dict) -> str:
    """"3 memories archived, 1 updated": learner-facing, content-free."""
    parts = [(counts[key], label) for key, label in CHANGE_LABELS if counts.get(key)]
    text = ""
    if parts:
        (first, label), rest = parts[0], parts[1:]
        text = ", ".join([f"{first} {'memory' if first == 1 else 'memories'} {label}"] + [f"{count} {label}" for count, label in rest])
    for key, label in EPISODE_LABELS:
        episodes = counts.get(key)
        if episodes:
            text += (", " if text else "") + f"{episodes} session {'summary' if episodes == 1 else 'summaries'} {label}"
    return text


def _private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


MEMORY_INPUT_MESSAGES = {
    "kind_not_allowed": "Unknown memory kind.",
    "statement_length": f"A memory needs 1 to {policy.STATEMENT_MAX_CHARS} characters.",
    "identifier_or_credential": "Memories can't hold links, contact details or passwords.",
    "event_date_invalid": "Use a date within two years, as YYYY-MM-DD.",
    "deadline_date_required": "A deadline needs a date.",
}


def _learner_input(conn, owner, body):
    """Validate a learner-typed fact; fails with a content-free reason code."""
    if not store.course_owned(conn, owner, body.course_id):
        fail("course_not_found", "The selected course is unavailable.", 404)
    try:
        return validator.learner_statement(body.kind, body.statement, body.event_date)
    except validator.LearnerInputError as error:
        fail("invalid_memory", MEMORY_INPUT_MESSAGES.get(str(error), "This memory can't be saved."), 422)


def _guarded(action):
    """Map store conflicts to HTTP errors; None means the memory is unavailable."""
    try:
        result = action()
    except store.RevisionConflict:
        fail("revision_conflict", "This memory changed. Refresh and try again.", 409)
    except store.NotEditable:
        fail("memory_not_editable", "This memory can't be changed this way.", 409)
    if result is None:
        fail("memory_not_found", "This memory is unavailable.", 404)
    return result


def _after_learner_change(conn, owner, counts, fact_ids):
    profile.rebuild_if_enabled(conn, owner)
    consolidation.record_change(conn, owner, "learner", counts, fact_ids=fact_ids)


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
            current = store.get_fact(conn, owner, fact_id)
            if current and current["status"] != "shadow":
                store.retire_preference_sources(conn, owner, current)
            restored = store.undo_fact(conn, owner, fact_id, window_seconds=86400 if undo else -1)
            if restored is None:
                fail("memory_not_found", "This memory is unavailable.", 404)
            _after_learner_change(conn, owner, {"forgotten": 1}, [fact_id] + restored)
        return {"status": "deleted", "restored": restored}

    @router.post("/facts")
    def add(body: FactCreate, response: Response):
        """The learner adds a memory by hand (user_stated, active)."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            statement, event_date, sensitive = _learner_input(conn, owner, body)
            fact_id, created = store.add_fact(conn, owner, kind=body.kind, statement=statement, course_id=body.course_id,
                                              event_date=event_date, sensitive=sensitive)
            if created:
                _after_learner_change(conn, owner, {"added": 1}, [fact_id])
            fact = store.get_fact(conn, owner, fact_id)
        response.status_code = 201 if created else 200
        return public_fact(fact)

    @router.patch("/facts/{fact_id}")
    def edit(fact_id: str, body: FactEdit, response: Response):
        """Edit = a new learner-confirmed fact that supersedes this one (§2 rule 3)."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            statement, event_date, sensitive = _learner_input(conn, owner, body)
            new_id, superseded = _guarded(lambda: store.edit_fact(
                conn, owner, fact_id, statement=statement, kind=body.kind, course_id=body.course_id, event_date=event_date,
                sensitive=sensitive, expected_revision=body.expected_revision))
            _after_learner_change(conn, owner, {"edited": 1}, [new_id] + superseded)
            fact = store.get_fact(conn, owner, new_id)
        return {**public_fact(fact), "superseded": superseded}

    @router.post("/facts/{fact_id}/confirm")
    def confirm(fact_id: str, body: FactConfirm, response: Response):
        """Confirm a memory. For a needs_review pair, this keeps this side and replaces the other."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            superseded = _guarded(lambda: store.confirm_fact(conn, owner, fact_id, expected_revision=body.expected_revision))
            _after_learner_change(conn, owner, {"confirmed": 1}, [fact_id] + superseded)
            fact = store.get_fact(conn, owner, fact_id)
        return {**public_fact(fact), "superseded": superseded}

    @router.put("/facts/{fact_id}/sensitive")
    def sensitive(fact_id: str, body: SensitiveUpdate, response: Response):
        """Let one sensitive memory into the tutor's context, or take it back out (§2 rule 6)."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            fact = _guarded(lambda: store.set_sensitive_enabled(conn, owner, fact_id, body.enabled,
                                                                expected_revision=body.expected_revision))
            profile.rebuild_if_enabled(conn, owner)
        return public_fact(fact)

    @router.get("/forget-all")
    def forget_all_preview(response: Response):
        """What "forget everything" would delete, and the token that confirms it."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().engine.connect() as conn:
            assert_owner_active(conn, owner)
            return {**store.memory_counts(conn, owner), "confirmation": store.forget_all_token(conn, owner)}

    @router.post("/forget-all")
    def forget_all(body: ForgetAll, response: Response):
        """Hard-delete every memory and session summary. The token must match current memory."""
        _private(response)
        owner = current_principal().owner_id
        with store_provider().transaction() as conn:
            assert_owner_active(conn, owner)
            if body.confirmation != store.forget_all_token(conn, owner):
                fail("confirmation_stale", "Your memories changed. Review them and confirm again.", 409)
            counts = store.forget_all(conn, owner)
            profile.clear(conn, owner)
            consolidation.record_change(conn, owner, "learner", {"forgotten": counts["facts"], "episodesForgotten": counts["episodes"]})
        return {"status": "deleted", **counts}

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
