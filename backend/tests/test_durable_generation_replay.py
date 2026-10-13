import asyncio
import pytest

from backend.app.generation_service import DurableReplayEventStore
from backend.app.generation_store import GenerationStore
from backend.app.storage import Store
from backend.app.graph_generator import GraphGenerator
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession


def _record(records):
    now = utc_now()
    scope = TopicScope(id='scope-replay', topic='slope', resolved_meaning='slope',
        objective='Replay contract', depth='introductory', created_at=now)
    records.store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    records.store.save_graph(graph)
    records.store.save_session(LearningSession(id='session-1', learner_id='local', graph_id=graph.id,
        created_at=now, updated_at=now))
    return records.create("local", "session-1", {"mode": "ask", "message": "What is slope?"}, "key", "test", "test-model")


def test_replay_after_restart_and_two_independent_observers(tmp_path):
    database = tmp_path / "replay.db"
    store = Store(database)
    records = GenerationStore(store)
    generation_id = _record(records)["id"]

    async def first_process():
        replay = DurableReplayEventStore(records)
        first = await replay.append(generation_id, "generation.started", {"mode": "ask"})
        second = await replay.append(generation_id, "text.delta", {"text": "Slope"})
        assert (first.sequence, second.sequence) == (3, 4)

    asyncio.run(first_process())
    store.close()
    restarted = Store(database)
    reopened = GenerationStore(restarted)

    async def second_process():
        replay = DurableReplayEventStore(reopened)
        a, b = await asyncio.gather(
            _read(replay, generation_id, 0),
            _read(replay, generation_id, 3),
        )
        assert [event.sequence for event in a] == [1, 2, 3, 4]
        assert [event.type for event in a[:2]] == ['message.accepted', 'generation.queued']
        assert [event.sequence for event in b] == [4]
        terminal = await replay.append(generation_id, "generation.completed", {"result": {"revision": 2}})
        assert terminal.sequence == 5
        assert [event.sequence for event in await _read(replay, generation_id, 4)] == [5]

    asyncio.run(second_process())
    assert reopened.get("local", generation_id)["sequence"] == 5
    restarted.close()


async def _read(replay, generation_id, after):
    return [event async for event in replay.subscribe(generation_id, after, terminal=True)]


def test_interrupted_generation_has_replayable_terminal_event(tmp_path):
    store = Store(tmp_path / "interrupted.db")
    records = GenerationStore(store)
    generation_id = _record(records)["id"]
    records.interrupt_active()
    events = records.events_after(generation_id, 0)
    assert events[-1].type == "generation.error"
    assert events[-1].data["code"] == "STREAM_INTERRUPTED"
    assert records.get("local", generation_id)["status"] == "interrupted"
    store.close()


def test_process_restart_marks_active_stream_interrupted_and_replays_from_last_event_id(tmp_path):
    database = tmp_path / "restart-interrupt.db"
    store = Store(database)
    records = GenerationStore(store)
    generation_id = _record(records)["id"]
    records.transition(generation_id, "preparing")
    records.transition(generation_id, "streaming")
    records.append_event(generation_id, "generation.started", {"mode": "ask"})
    last_seen = records.append_event(generation_id, "text.delta", {"text": "Partial response"}).sequence
    store.close()

    restarted = Store(database)
    reopened = GenerationStore(restarted)
    reopened.interrupt_active()
    record = reopened.get("local", generation_id)
    assert record["status"] == "interrupted"
    assert record["errorCode"] == "STREAM_INTERRUPTED"

    async def recovery_event():
        replay = DurableReplayEventStore(reopened)
        return [event async for event in replay.subscribe(generation_id, last_seen, terminal=True)]

    events = asyncio.run(recovery_event())
    assert len(events) == 1
    assert events[0].sequence == last_seen + 1
    assert events[0].type == "generation.error"
    assert events[0].data["code"] == "STREAM_INTERRUPTED"
    restarted.close()


def test_preparing_transition_claims_generation_once(tmp_path):
    store = Store(tmp_path / "claim.db")
    records = GenerationStore(store)
    generation_id = _record(records)["id"]
    records.transition(generation_id, "preparing")
    with pytest.raises(RuntimeError, match="Illegal generation transition"):
        records.transition(generation_id, "preparing")
    store.close()


def test_terminal_status_and_event_commit_together_for_new_subscriber(tmp_path):
    store = Store(tmp_path / "terminal.db")
    records = GenerationStore(store)
    generation_id = _record(records)["id"]
    for status in ("preparing", "streaming", "finalizing"):
        records.transition(generation_id, status)
    with store.transaction() as connection:
        records.transition(generation_id, "completed", result={"revision": 2}, connection=connection)
        records.append_event(generation_id, "generation.completed", {"result": {"revision": 2}}, connection)
    assert records.get("local", generation_id)["status"] == "completed"
    assert [event.type for event in asyncio.run(_read(DurableReplayEventStore(records), generation_id, 0))] == ['message.accepted', 'generation.queued', "generation.completed"]
    store.close()


def test_two_live_observers_and_last_event_id_reconnect_receive_gapless_sequence(tmp_path):
    store = Store(tmp_path / "live-observers.db")
    records = GenerationStore(store)
    generation_id = _record(records)["id"]

    async def consume(replay, after):
        received = []
        async for event in replay.subscribe(generation_id, after, terminal=False):
            received.append(event)
            if event.type == "generation.completed":
                break
        return received

    async def scenario():
        replay = DurableReplayEventStore(records)
        first_tab = asyncio.create_task(consume(replay, 0))
        await asyncio.sleep(0.02)
        started = await replay.append(generation_id, "generation.started", {"mode": "ask"})
        delta = await replay.append(generation_id, "text.delta", {"text": "First block"})

        # A second tab reconnects using the last event ID acknowledged by the
        # first tab. It must receive only the missing tail, including terminal.
        second_tab = asyncio.create_task(consume(replay, delta.sequence))
        await asyncio.sleep(0.02)
        middle = await replay.append(generation_id, "text.delta", {"text": "Second block"})
        terminal = await replay.append(generation_id, "generation.completed", {"result": {"revision": 2}})
        first, second = await asyncio.gather(first_tab, second_tab)
        assert [event.sequence for event in first] == [1, 2, started.sequence, delta.sequence, middle.sequence, terminal.sequence]
        assert [event.sequence for event in second] == [middle.sequence, terminal.sequence]
        assert [event.type for event in second][-1] == "generation.completed"

    asyncio.run(scenario())
    store.close()
