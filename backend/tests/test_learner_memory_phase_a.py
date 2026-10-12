"""Learner memory Phase A: chat memory block, compiler ranking, wasted compile."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.context_compiler import ContextCompiler
from backend.app.context_engine import estimate_tokens
from backend.app.learner_memory import policy
from backend.app.learner_memory.service import LearnerMemoryService
from backend.app.source_memory import SourceMemory
from backend.app.storage import Store

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "memory.db")
    yield value
    value.close()


def remember(store, owner, source_id, statement, *, scope=None, explicit=True):
    memory = SourceMemory(store)
    memory.revise(owner, source_id, statement, course_id=scope, expected_revision=0)
    return memory.derive(owner, "preference", {"statement": statement}, [{"sourceId": source_id, "revision": 1}],
                         scope=scope, explicit=explicit)["id"]


def academic(store, owner, course, identifier, kind, field, value, title, **facts):
    payload = {"id": identifier, "courseId": course, "kind": kind,
               "facts": {"title": {"value": title}, field: {"value": value},
                         **{key: {"value": item} for key, item in facts.items()}}}
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO academic_entities(owner_id,id,course_id,revision,payload,created_at) VALUES(:owner,:id,:course,1,:payload,:now)"),
                     {"owner": owner, "id": identifier, "course": course, "payload": json.dumps(payload), "now": time.time()})


def test_chat_block_ranks_explicit_preferences_and_isolates_owners(store):
    remember(store, "alice", "p-global", "Prefers short answers with one example.")
    time.sleep(0.01)
    remember(store, "alice", "p-course", "Use calculus notation from my textbook.", scope="calc")
    remember(store, "alice", "p-other", "Explain chemistry with kitchen analogies.", scope="chem")
    remember(store, "alice", "p-tentative", "Maybe likes diagrams.", explicit=False)

    block = LearnerMemoryService(store).chat_block("alice", None, "calc", "help", now=NOW)

    assert block["note"] == policy.MEMORY_BLOCK_HEADER
    assert block["preferences"] == [
        {"learnerSaid": "Use calculus notation from my textbook.", "scope": "course"},
        {"learnerSaid": "Prefers short answers with one example.", "scope": "global"},
    ]
    assert LearnerMemoryService(store).chat_block("bob", None, "calc", "help", now=NOW) is None


def test_chat_block_lists_only_upcoming_course_dates(store):
    soon = (NOW + timedelta(days=5)).isoformat()
    academic(store, "alice", "calc", "e1", "assessment", "date", {"kind": "date_only", "value": (NOW + timedelta(days=9)).date().isoformat()}, "Midterm")
    academic(store, "alice", "calc", "e2", "assignment", "due", {"kind": "instant", "value": soon}, "Problem set 4")
    academic(store, "alice", "calc", "e3", "assignment", "due", {"kind": "instant", "value": (NOW - timedelta(hours=2)).isoformat()}, "Overdue set")
    academic(store, "alice", "calc", "e4", "assignment", "due", {"kind": "instant", "value": (NOW + timedelta(days=45)).isoformat()}, "Final project")
    academic(store, "alice", "calc", "e5", "assignment", "due", {"kind": "instant", "value": soon}, "Done set", completed=True)
    academic(store, "alice", "chem", "e6", "assignment", "due", {"kind": "instant", "value": soon}, "Lab report")
    academic(store, "alice", "calc", "e7", "assessment", "date", {"kind": "date_only", "value": NOW.date().isoformat()}, "Quiz today")

    block = LearnerMemoryService(store).chat_block("alice", None, "calc", "when is my midterm", now=NOW)

    assert [item["title"] for item in block["upcoming"]] == ["Quiz today", "Problem set 4", "Midterm"]
    assert block["upcoming"][1] == {"title": "Problem set 4", "type": "assignment", "date": (NOW + timedelta(days=5)).date().isoformat()}
    # Without a course there is no course calendar to show.
    assert LearnerMemoryService(store).chat_block("alice", None, None, "x", now=NOW) is None


def test_chat_block_trims_to_its_budget_and_fails_soft(store, monkeypatch):
    for index in range(policy.MAX_PREFERENCES):
        remember(store, "alice", f"p{index}", f"Preference {index} " + "detail " * 60)
    monkeypatch.setattr(policy, "MEMORY_BLOCK_MAX_TOKENS", 300)
    block = LearnerMemoryService(store).chat_block("alice", None, None, "x", now=NOW)
    assert 0 < len(block["preferences"]) < policy.MAX_PREFERENCES
    assert estimate_tokens(block) <= 300
    assert all(len(item["learnerSaid"]) <= policy.PREFERENCE_MAX_CHARS for item in block["preferences"])

    class Broken:
        @property
        def engine(self):
            raise RuntimeError("database unavailable")
    assert LearnerMemoryService(Broken()).chat_block("alice", None, None, "x") is None


def test_compiler_ranks_and_caps_remembered_items(store):
    for index in range(policy.COMPILER_MAX_REMEMBERED + 3):
        remember(store, "alice", f"g{index}", f"Global preference {index}")
    packet = ContextCompiler(store).compile("alice", None, "teaching", "algebra", token_budget=20000)
    remembered = json.loads(packet["text"].split("\n\n")[0])["remembered"]
    assert len(remembered) == policy.COMPILER_MAX_REMEMBERED
    # Newest first, so the most recent preference is always admitted.
    assert remembered[0]["value"]["statement"] == f"Global preference {policy.COMPILER_MAX_REMEMBERED + 2}"


def test_compiler_token_estimate_matches_context_engine():
    value = "Conditional probability ✓ " * 40
    assert ContextCompiler.tokens(value) == estimate_tokens(value)
    assert ContextCompiler.tokens(value) < len(value.encode("utf-8"))


class StreamingProvider:
    provider_name = "test-only"

    def __init__(self):
        self.streamed = []

    def complete_json(self, prompt, max_tokens=4000):
        return {"blocks": [{"kind": "explanation", "heading": "Answer", "body": "A focused answer."}]}

    async def stream_text(self, prompt, max_tokens=4000, **options):
        self.streamed.append(prompt)
        yield "A focused answer."


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    from backend.app.generation_routes import build_generation_router
    from backend.app.graph_generator import GraphGenerator
    from backend.app.identity import Principal, principal_context
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.learning_routes import build_learning_router
    from backend.app.models import TopicScope, utc_now
    from backend.app.session_models import LearningSession

    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    # Generations run in-process here. CI sets OPENLEARN_WORKER_MODE=external,
    # where no worker would ever produce the event stream these tests read.
    monkeypatch.setenv("OPENLEARN_WORKER_MODE", "embedded")
    store = Store(tmp_path / "conversation.db")
    token = principal_context.set(Principal("local", "local"))
    scope = TopicScope(id="scope-memory", topic="probability", resolved_meaning="probability",
                       objective="conditional probability", depth="introductory", created_at=utc_now())
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    session = LearningSession(id="session-memory", learner_id="local", graph_id=graph.id, goal="conditional probability",
                              created_at=utc_now(), updated_at=utc_now())
    store.save_session(session)
    with store.transaction() as conn:
        conn.execute(text("UPDATE buddy_chats SET presentation='conversation' WHERE id=:id AND owner_id='local'"), {"id": session.id})
    provider = StreamingProvider()
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    app.include_router(build_learning_router(lambda: store, lambda: provider))
    app.include_router(build_generation_router(lambda: store, lambda: provider))
    with TestClient(app) as client:
        yield client, store, provider, session
    store.close()
    principal_context.reset(token)


def ask(client, session, message, key):
    created = client.post(f"/v1/sessions/{session.id}/generations",
                          json={"mode": "ask", "message": message, "gear": "Guided", "expectedRevision": 1},
                          headers={"Idempotency-Key": key})
    assert created.status_code == 202, created.text
    events = client.get(f"/v1/generations/{created.json()['id']}/events")
    assert "event: generation.completed" in events.text, events.text


@pytest.mark.parametrize("enabled", [True, False])
def test_saved_preference_reaches_conversation_prompt_only_when_enabled(conversation, monkeypatch, enabled):
    client, store, provider, session = conversation
    monkeypatch.setenv("OPENLEARN_MEMORY_CHAT_CONTEXT", "on" if enabled else "off")
    remember(store, "local", "pref-source", "Prefers one worked example before practice.")

    ask(client, session, "What does conditioning change?", f"memory-{enabled}")

    prompt = provider.streamed[-1]
    prompt = prompt if isinstance(prompt, str) else prompt.legacy_prompt()
    assert ("Prefers one worked example before practice." in prompt) is enabled
    assert ("learnerMemory" in prompt) is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_conversation_skips_unused_control_plane_compile(conversation, monkeypatch, enabled):
    from backend.app.learning_control_plane import LearningControlPlane
    client, _, _, session = conversation
    monkeypatch.setenv("OPENLEARN_MEMORY_SKIP_UNUSED_COMPILE", "on" if enabled else "off")
    calls = []
    original = LearningControlPlane.prepare

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(LearningControlPlane, "prepare", counted)

    ask(client, session, "What does conditioning change?", f"skip-{enabled}")

    assert len(calls) == (0 if enabled else 1)
    saved = client.get(f"/v1/sessions/{session.id}/journey").json()
    assert saved["turns"][-1]["status"] == "completed"


def test_assessment_context_excludes_summaries_but_keeps_preferences(store):
    remember(store, "alice", "pref", "Prefers short answers.")
    memory = SourceMemory(store)
    memory.revise("alice", "chat", "We solved x = 4 together. Next: unresolved algebra.", kind="conversation", expected_revision=0)
    memory.summarize("alice", "chat", 1)

    teaching = json.loads(ContextCompiler(store).compile("alice", None, "teaching", "algebra")["text"].split("\n\n")[0])
    assessment = json.loads(ContextCompiler(store).compile("alice", None, "assessment", "algebra")["text"].split("\n\n")[0])

    assert {item["kind"] for item in teaching["remembered"]} == {"preference", "summary"}
    assert [item["kind"] for item in assessment["remembered"]] == ["preference"]
