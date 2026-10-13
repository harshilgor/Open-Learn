"""Learner memory Phase F1: learner write APIs, sensitive opt-in, forget-all, preference precedence (spec §10)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.learner_memory import consolidation, policy, profile, store as facts
from backend.app.learner_memory.service import LearnerMemoryService
from backend.app.storage import Store

from test_learner_memory_phase_a import ask, conversation, remember  # noqa: F401 (fixture)
from test_learner_memory_phase_d import fact, insert


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.app.identity import Principal, principal_context
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.learner_memory.routes import build_learner_memory_router
    from backend.app.memory_routes import build_memory_router
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    monkeypatch.setenv("OPENLEARN_MEMORY_CONSOLIDATION", "on")
    value = Store(tmp_path / "api.db")
    token = principal_context.set(Principal("local", "local"))
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: value)
    app.include_router(build_memory_router(lambda: value))
    app.include_router(build_learner_memory_router(lambda: value))
    with TestClient(app) as client:
        yield client, value
    value.close()
    principal_context.reset(token)


def row(db, owner, fact_id):
    with db.engine.connect() as conn:
        return facts.get_fact(conn, owner, fact_id)


def course(db, owner, identifier, name):
    with db.transaction() as conn:
        conn.execute(text("INSERT INTO courses(id,owner_id,name,goal,created_at,updated_at,archived_at) VALUES(:id,:owner,:name,'',0,0,NULL)"),
                     {"id": identifier, "owner": owner, "name": name})


def memory_text(db, owner, message="hello", course_id=None):
    context = LearnerMemoryService(db).context(owner, course_id, message)
    return context.text if context else ""


# --- PATCH /facts/{id}: edit supersedes, never rewrites (§2 rule 3) --------------

def test_edit_creates_a_confirmed_fact_that_supersedes_the_old_one(api):
    client, db = api
    insert(db, "local", fact("exam", "Calc midterm on 2026-11-03.", kind="deadline", subject="deadline:calc-midterm",
                             event_date="2026-11-03", origin="inferred",
                             ) | {"basis": [{"type": "turn", "sessionId": "s1", "turnIndex": 4, "quote": "midterm is nov 3"}]})
    edited = client.patch("/v1/memory/facts/exam", json={"statement": "Calc midterm on 2026-11-05.", "kind": "deadline",
                                                         "eventDate": "2026-11-05", "expectedRevision": 1})
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert edited.headers["cache-control"] == "private, no-store"
    assert body["superseded"] == ["exam"] and body["origin"] == "user_confirmed" and body["status"] == "active"
    assert body["eventDate"] == "2026-11-05"
    # The learner's original words still link back to the turn.
    assert {"type": "turn", "sessionId": "s1", "turnIndex": 4, "quote": "midterm is nov 3"} in body["basis"]
    old, new = row(db, "local", "exam"), row(db, "local", body["id"])
    assert old["statement"] == "Calc midterm on 2026-11-03."  # immutable
    assert old["status"] == "superseded" and old["superseded_by"] == body["id"]
    assert new["subject_key"] == "deadline:calc-midterm" and new["stability_days"] == policy.CORRECTED_STABILITY_DAYS
    history = client.get(f"/v1/memory/facts/{body['id']}/history").json()["items"]
    assert [item["id"] for item in history] == ["exam", body["id"]]


def test_edit_checks_revision_state_course_and_input(api):
    client, db = api
    insert(db, "local", fact("goal", "Wants to pass calc."))
    stale = client.patch("/v1/memory/facts/goal", json={"statement": "Wants an A.", "kind": "goal", "expectedRevision": 7})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "revision_conflict"
    bad = client.patch("/v1/memory/facts/goal", json={"statement": "See https://example.com", "kind": "goal", "expectedRevision": 1})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_memory"
    unknown_course = client.patch("/v1/memory/facts/goal", json={"statement": "Wants an A.", "kind": "goal", "courseId": "nope",
                                                                 "expectedRevision": 1})
    assert unknown_course.status_code == 404
    first = client.patch("/v1/memory/facts/goal", json={"statement": "Wants an A.", "kind": "goal", "expectedRevision": 1})
    assert first.status_code == 200
    # The old fact is now superseded: it can't be edited again (a retried request doesn't fork the timeline).
    again = client.patch("/v1/memory/facts/goal", json={"statement": "Wants an A.", "kind": "goal", "expectedRevision": 2})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "memory_not_editable"


def test_undoing_an_edit_restores_the_original(api):
    client, db = api
    insert(db, "local", fact("pref", "Prefers short answers.", kind="preference", subject="preference:length"))
    new_id = client.patch("/v1/memory/facts/pref", json={"statement": "Prefers detailed answers.", "kind": "preference",
                                                         "expectedRevision": 1}).json()["id"]
    undone = client.delete(f"/v1/memory/facts/{new_id}?undo=true").json()
    assert undone["restored"] == ["pref"] and row(db, "local", "pref")["status"] == "active"
    assert row(db, "local", new_id) is None


def test_edit_can_move_a_fact_to_a_course_and_change_kind(api):
    client, db = api
    course(db, "local", "calc", "Calculus")
    insert(db, "local", fact("note", "Struggles with limits.", kind="note_to_self", subject="note_to_self:limits"))
    body = client.patch("/v1/memory/facts/note", json={"statement": "Struggles with epsilon-delta limits.", "kind": "background",
                                                       "courseId": "calc", "expectedRevision": 1}).json()
    assert body["kind"] == "background" and body["courseId"] == "calc"
    assert row(db, "local", body["id"])["subject_key"] == "background:limits"


# --- POST /facts/{id}/confirm ---------------------------------------------------------

def test_confirm_promotes_an_inference_and_takes_its_slot(api):
    client, db = api
    insert(db, "local", fact("held", "Prefers diagrams.", kind="preference", subject="preference:format", origin="inferred",
                             status="tentative"))
    insert(db, "local", fact("current", "Prefers text.", kind="preference", subject="preference:format", origin="inferred"))
    body = client.post("/v1/memory/facts/held/confirm", json={"expectedRevision": 1}).json()
    assert body["status"] == "active" and body["origin"] == "user_confirmed" and body["superseded"] == ["current"]
    assert row(db, "local", "held")["stability_days"] == policy.CONFIRMED_STABILITY_DAYS
    assert row(db, "local", "current")["superseded_by"] == "held"


def test_confirm_keeps_a_learner_statement_origin(api):
    client, db = api
    insert(db, "local", fact("goal", "Wants to pass calc."))
    body = client.post("/v1/memory/facts/goal/confirm", json={"expectedRevision": 1}).json()
    assert body["origin"] == "user_stated" and body["confirmedAt"] is not None and body["superseded"] == []


def test_confirming_one_side_resolves_a_review_conflict(api):
    client, db = api
    insert(db, "local", fact("a", "Exam on 2026-11-03.", kind="deadline", subject="deadline:exam", event_date="2026-11-03"))
    insert(db, "local", fact("b", "Exam on 2026-11-04.", kind="deadline", subject="deadline:exam", event_date="2026-11-04",
                             status="tentative"))
    with db.transaction() as conn:
        facts.set_needs_review(conn, "local", ["a", "b"], True)
    review = client.get("/v1/memory/facts").json()["items"]
    assert {item["id"] for item in review if item["needsReview"]} == {"a", "b"}
    revision = row(db, "local", "b")["revision"]
    body = client.post("/v1/memory/facts/b/confirm", json={"expectedRevision": revision}).json()
    assert body["status"] == "active" and body["needsReview"] is False and body["superseded"] == ["a"]
    assert row(db, "local", "a")["status"] == "superseded" and row(db, "local", "a")["needs_review"] is False


# --- POST /facts: manual facts ------------------------------------------------------

def test_learner_can_add_a_fact_and_adding_it_twice_is_harmless(api):
    client, db = api
    created = client.post("/v1/memory/facts", json={"statement": "Works night shifts on weekends.", "kind": "constraint"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["origin"] == "user_stated" and body["status"] == "active" and body["basis"] == [{"type": "learner"}]
    again = client.post("/v1/memory/facts", json={"statement": "works night shifts  on weekends.", "kind": "constraint"})
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert "Works night shifts on weekends." in memory_text(db, "local")


@pytest.mark.parametrize("payload,code", [
    ({"statement": "", "kind": "goal"}, 422),
    ({"statement": "x" * 301, "kind": "goal"}, 422),
    ({"statement": "My password is hunter2", "kind": "background"}, 422),
    ({"statement": "Email me at a@b.co", "kind": "background"}, 422),
    ({"statement": "Final exam", "kind": "deadline"}, 422),
    ({"statement": "Final exam", "kind": "deadline", "eventDate": "2031-01-01"}, 422),
    ({"statement": "Pass", "kind": "wish"}, 422),
    ({"statement": "Pass", "kind": "goal", "courseId": "someone-elses"}, 404),
])
def test_manual_facts_are_validated(api, payload, code):
    client, db = api
    course(db, "bob", "someone-elses", "Bob's course")
    assert client.post("/v1/memory/facts", json=payload).status_code == code


# --- Sensitive facts: stored on request, out of prompts until enabled (§2 rule 6) -----

def test_sensitive_fact_enters_context_only_when_the_learner_enables_it(api):
    client, db = api
    body = client.post("/v1/memory/facts", json={"statement": "Has ADHD; prefers short study blocks.", "kind": "constraint"}).json()
    assert body["sensitive"] is True and body["sensitiveEnabled"] is False
    assert "ADHD" not in memory_text(db, "local")
    with db.engine.connect() as conn:
        assert body["id"] not in profile.build(facts.facts_with_status(conn, "local", {"active"}), 1.9e9)["factIds"]

    enabled = client.put(f"/v1/memory/facts/{body['id']}/sensitive", json={"enabled": True, "expectedRevision": body["revision"]})
    assert enabled.status_code == 200 and enabled.json()["sensitiveEnabled"] is True
    assert "ADHD" in memory_text(db, "local")
    assert "ADHD" in client.get("/v1/memory/profile").json()["text"]

    disabled = client.put(f"/v1/memory/facts/{body['id']}/sensitive", json={"enabled": False, "expectedRevision": enabled.json()["revision"]})
    assert disabled.json()["sensitiveEnabled"] is False
    assert "ADHD" not in memory_text(db, "local")


def test_sensitive_switch_only_applies_to_sensitive_facts(api):
    client, db = api
    insert(db, "local", fact("goal", "Wants to pass calc."))
    response = client.put("/v1/memory/facts/goal/sensitive", json={"enabled": True, "expectedRevision": 1})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "memory_not_editable"


def test_editing_keeps_the_sensitive_opt_in(api):
    client, db = api
    body = client.post("/v1/memory/facts", json={"statement": "Takes medication at noon.", "kind": "constraint"}).json()
    enabled = client.put(f"/v1/memory/facts/{body['id']}/sensitive", json={"enabled": True, "expectedRevision": body["revision"]}).json()
    edited = client.patch(f"/v1/memory/facts/{body['id']}", json={"statement": "Takes medication at 1pm.", "kind": "constraint",
                                                                  "expectedRevision": enabled["revision"]}).json()
    assert edited["sensitive"] is True and edited["sensitiveEnabled"] is True


# --- Forget everything ------------------------------------------------------------------

def test_forget_all_needs_a_current_token_and_spares_other_owners(api):
    client, db = api
    remember(db, "local", "pref-source", "Prefers short answers.")
    insert(db, "local", fact("goal", "Wants to pass calc."))
    insert(db, "local", fact("shadow", "Shadow goal.", status="shadow"))
    insert(db, "bob", fact("bob_goal", "Bob wants to pass."))
    preview = client.get("/v1/memory/forget-all").json()
    assert preview["facts"] == 2 and preview["episodes"] == 0  # shadow rows are never shown or counted
    assert client.post("/v1/memory/forget-all", json={"confirmation": "yes"}).status_code == 409
    insert(db, "local", fact("late", "Learned after the preview."))
    stale = client.post("/v1/memory/forget-all", json={"confirmation": preview["confirmation"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "confirmation_stale"

    token = client.get("/v1/memory/forget-all").json()["confirmation"]
    done = client.post("/v1/memory/forget-all", json={"confirmation": token})
    assert done.status_code == 200 and done.json() == {"status": "deleted", "facts": 3, "episodes": 0}
    with db.engine.connect() as conn:
        owners = {item[0] for item in conn.execute(text("SELECT owner_id FROM memory_facts"))}
        valid_prefs = conn.execute(text("SELECT COUNT(*) FROM memory_derived WHERE owner_id='local' AND kind='preference' AND valid=true")).scalar_one()
        assert profile.stored(conn, "local") is None
    assert owners == {"bob"} and valid_prefs == 0
    assert memory_text(db, "local") == ""
    changes = client.get("/v1/memory/changes").json()["items"]
    assert changes[0]["source"] == "learner" and changes[0]["summary"] == "3 memories forgotten"


# --- Owner isolation (§2 rule 7) ---------------------------------------------------------

def test_write_apis_never_touch_another_owners_facts(api):
    client, db = api
    insert(db, "bob", fact("bob_goal", "Bob wants to pass.", status="tentative", origin="inferred"))
    assert client.patch("/v1/memory/facts/bob_goal", json={"statement": "Mine now.", "kind": "goal", "expectedRevision": 1}).status_code == 404
    assert client.post("/v1/memory/facts/bob_goal/confirm", json={"expectedRevision": 1}).status_code == 404
    assert client.put("/v1/memory/facts/bob_goal/sensitive", json={"enabled": True, "expectedRevision": 1}).status_code == 404
    assert client.delete("/v1/memory/facts/bob_goal").status_code == 404
    unchanged = row(db, "bob", "bob_goal")
    assert unchanged["status"] == "tentative" and unchanged["revision"] == 1


# --- Change log from learner actions -------------------------------------------------------

def test_learner_actions_are_logged_without_content(api):
    client, db = api
    added = client.post("/v1/memory/facts", json={"statement": "Studies in the library.", "kind": "background"}).json()
    edited = client.patch(f"/v1/memory/facts/{added['id']}", json={"statement": "Studies at home.", "kind": "background",
                                                                   "expectedRevision": added["revision"]}).json()
    client.post(f"/v1/memory/facts/{edited['id']}/confirm", json={"expectedRevision": edited["revision"]})
    client.delete(f"/v1/memory/facts/{edited['id']}")
    items = client.get("/v1/memory/changes").json()["items"]
    assert [item["summary"] for item in items] == ["1 memory forgotten", "1 memory confirmed by you", "1 memory edited by you",
                                                   "1 memory added by you"]
    assert all(item["source"] == "learner" for item in items)
    assert "library" not in json.dumps(items) and "home" not in json.dumps(items)


def test_change_summary_wording_for_learner_actions():
    from backend.app.learner_memory.routes import change_summary
    assert change_summary({"forgotten": 4, "episodesForgotten": 2}) == "4 memories forgotten, 2 session summaries forgotten"
    assert change_summary({"added": 1, "edited": 2}) == "1 memory added by you, 2 edited by you"


# --- Preference precedence (§10) ------------------------------------------------------------

def test_precedence_order_is_request_course_global_buddy_account():
    ranked = sorted(["account", "buddy_profile", "global_fact", "course_fact", "current_request"], key=policy.preference_source_rank)
    assert ranked == list(policy.PREFERENCE_PRECEDENCE)
    assert policy.preference_source_rank("something_else") == len(policy.PREFERENCE_PRECEDENCE)


def test_course_preference_is_listed_before_global_in_the_chat_block(tmp_path):
    db = Store(tmp_path / "precedence.db")
    try:
        course(db, "ana", "calc", "Calculus")
        remember(db, "ana", "global-pref", "Prefers short answers.")
        remember(db, "ana", "calc-pref", "Prefers full derivations.", scope="calc")
        block = LearnerMemoryService(db).chat_block("ana", "session", "calc", "hi")
        assert [item["scope"] for item in block["preferences"]] == ["course", "global"]
    finally:
        db.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_precedence_note_reaches_the_prompt_with_memory(conversation, monkeypatch, enabled):  # noqa: F811
    client, db, provider, session = conversation
    monkeypatch.setenv("OPENLEARN_MEMORY_CHAT_CONTEXT", "on" if enabled else "off")
    remember(db, "local", "pref-source", "Prefers one worked example before practice.")
    ask(client, session, "What does conditioning change?", f"precedence-{enabled}")
    prompt = provider.streamed[-1]
    prompt = prompt if isinstance(prompt, str) else prompt.legacy_prompt()
    assert ("Preference precedence:" in prompt) is enabled
