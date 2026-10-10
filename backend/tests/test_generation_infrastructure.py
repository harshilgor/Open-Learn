import asyncio
import socket
import threading

import pytest

from backend.app.generation_models import GenerationRequest
from backend.app.generation_service import EventBuffer
from backend.app.generation_store import GenerationStore
from backend.app.graph_generator import GraphGenerator
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.storage import Store


def request(message="Explain probability"):
    return GenerationRequest(mode="ask", message=message, gear="Guided", expectedRevision=1).model_dump(mode="json", by_alias=True)


def seed_session(store, session_id="session-1"):
    now = utc_now()
    scope = TopicScope(id=f"scope-{session_id}", topic="probability", resolved_meaning="probability",
                       objective="test generation lifecycle", depth="introductory", created_at=now)
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    store.save_session(LearningSession(id=session_id, learner_id="local", graph_id=graph.id,
                                       created_at=now, updated_at=now))


def test_generation_idempotency_and_lifecycle(tmp_path):
    store = Store(tmp_path / "generation.db")
    seed_session(store)
    records = GenerationStore(store)
    first = records.create("local", "session-1", request(), "same-key", "test", "test-model")
    duplicate = records.create("local", "session-1", request(), "same-key", "test", "test-model")
    assert duplicate["id"] == first["id"] and first["status"] == "queued"
    records.transition(first["id"], "preparing")
    records.update_metrics(first["id"], {"applicationTtftSeconds": 0.25})
    records.transition(first["id"], "streaming")
    records.transition(first["id"], "finalizing")
    records.transition(first["id"], "completed", result={"revision": 2})
    assert records.get("local", first["id"])["result"]["revision"] == 2
    assert GenerationStore.descriptor(records.get("local", first["id"])).metrics["applicationTtftSeconds"] == 0.25
    with pytest.raises(Exception):
        records.create("local", "session-1", request("Different request"), "same-key", "test", "test-model")
    store.close()


def test_event_buffer_replays_in_sequence_and_supports_duplicate_safe_consumers():
    socketpair_result = []

    def probe_socketpair():
        try:
            left, right = socket.socketpair()
            left.close()
            right.close()
            socketpair_result.append(True)
        except OSError:
            socketpair_result.append(False)

    probe = threading.Thread(target=probe_socketpair, daemon=True)
    probe.start()
    probe.join(timeout=0.5)
    if probe.is_alive() or not socketpair_result or not socketpair_result[0]:
        pytest.skip("The restricted Windows sandbox blocks asyncio's socketpair self-pipe.")

    async def scenario():
        buffer = EventBuffer()
        one = await buffer.publish("gen-1", "generation.started")
        two = await buffer.publish("gen-1", "text.delta", {"text": "Hello"})
        replay = []
        async for event in buffer.observe("gen-1", 0, True):
            replay.append(event)
        assert [event.sequence for event in replay] == [one.sequence, two.sequence]
        # A reconnect at sequence one sees only the new delta.
        reconnect = []
        async for event in buffer.observe("gen-1", one.sequence, True):
            reconnect.append(event)
        assert [event.sequence for event in reconnect] == [two.sequence]
    asyncio.run(scenario())


def test_cancel_request_becomes_a_terminal_cancelled_generation(tmp_path):
    store = Store(tmp_path / "cancel.db")
    seed_session(store)
    records = GenerationStore(store)
    created = records.create("local", "session-1", request(), "cancel-key", "test", "test-model")
    records.transition(created["id"], "preparing")
    requested = records.request_cancel("local", created["id"])
    assert requested["status"] == "cancel_requested" and requested["cancellationRequested"] is True
    records.transition(created["id"], "cancelled", error_code="CANCELLED")
    assert records.get("local", created["id"])["status"] == "cancelled"
    store.close()
