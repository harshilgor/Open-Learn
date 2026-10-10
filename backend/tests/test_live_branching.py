"""Durable inbox, branch and owner-fencing contracts for live chat."""
import json
import socket
import threading
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.app.conversation_branching import ConversationBranchStore, classify_relation, visible_context_turns
from backend.app.generation_store import GenerationStore
from backend.app.generation_observability import live_branching_metrics
from backend.app.generation_observability import record_client_outbox_snapshot
from backend.app.generation_models import OutboxMetricsRequest
from backend.app.graph_generator import GraphGenerator
from backend.app.identity import Principal, principal_context
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.storage import Store


@pytest.fixture
def live_branching_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    store = Store(tmp_path / "live-branching.db")
    principal_token = principal_context.set(Principal("local", "local"))
    scope = TopicScope(id="scope-live-branching", topic="biology", resolved_meaning="ecology",
                       objective="understand ecosystems", depth="introductory", created_at=utc_now())
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    session = LearningSession(id="session-live-branching", learner_id="local", graph_id=graph.id,
                              goal="understand ecosystems", created_at=utc_now(), updated_at=utc_now())
    store.save_session(session)
    try:
        yield store, session, GenerationStore(store), ConversationBranchStore(store)
    finally:
        store.close()
        principal_context.reset(principal_token)


def _request(client_id: str, message: str) -> dict:
    return {"mode": "ask", "message": message, "clientMessageId": client_id}


@pytest.mark.parametrize(("message", "relation"), [
    ("Please stop generating.", "cancel"),
    ("Also explain the next step.", "add"),
    ("Actually, I meant the other population.", "clarify"),
    ("Rewrite that with a simpler example.", "revise"),
    ("New topic: explain linear equations.", "new_topic"),
    ("Tell me more.", "uncertain"),
])
def test_relation_classifier_routes_all_supported_followup_types(message, relation):
    assert classify_relation(message) == relation


def test_branch_context_includes_ancestors_and_legacy_turns_but_not_siblings():
    turns = [
        {"question": "Legacy history"},
        {"question": "Root answer", "branchId": "root"},
        {"question": "Sibling answer", "branchId": "sibling"},
        {"question": "Child answer", "branchId": "child"},
    ]
    parents = {"root": None, "sibling": "root", "child": "root", "fresh-topic": None}
    assert [turn["question"] for turn in visible_context_turns(turns, "child", parents)] == [
        "Legacy history", "Root answer",
    ]
    assert [turn["question"] for turn in visible_context_turns(turns, "fresh-topic", parents)] == [
        "Legacy history",
    ]


def test_acceptance_is_idempotent_and_allocates_ordered_conversation_events(live_branching_store):
    store, session, records, _ = live_branching_store
    first = records.create("local", session.id, _request("message-one", "Explain a food web."),
                           "message-one", "test", "test-model")
    retry = records.create("local", session.id, _request("message-one", "Explain a food web."),
                           "message-one", "test", "test-model")
    second = records.create("local", session.id, _request("message-two", "Also explain producers."),
                            "message-two", "test", "test-model", reject_if_active=False)
    assert retry["id"] == first["id"]
    assert first["conversationSeq"] < second["conversationSeq"]
    with store.engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT sequence,event_type FROM conversation_events
            WHERE owner_id='local' AND session_id=:session ORDER BY sequence
        """), {"session": session.id}).all()
        user_count = connection.execute(text("""
            SELECT COUNT(*) FROM conversation_events
            WHERE owner_id='local' AND session_id=:session AND event_type='user_message'
        """), {"session": session.id}).scalar_one()
    assert [row[0] for row in rows] == sorted(row[0] for row in rows)
    assert user_count == 2


def test_reply_to_generation_is_validated_and_kept_in_event_and_generation(live_branching_store):
    store, session, records, _ = live_branching_store
    first = records.create("local", session.id, _request("parent-message", "Explain ecosystems."),
                           "parent-message", "test", "test-model")
    child_request = _request("child-message", "Can you expand on that?")
    child_request["replyToGenerationId"] = first["id"]
    child = records.create("local", session.id, child_request, "child-message", "test", "test-model",
                           reject_if_active=False)
    with store.engine.connect() as connection:
        parent_id = connection.execute(text("SELECT parent_generation_id FROM generation_records WHERE id=:id"),
                                       {"id": child["id"]}).scalar_one()
        event = connection.execute(text("SELECT payload_json FROM conversation_events WHERE id=:id"),
                                   {"id": child["messageEventId"]}).scalar_one()
    assert parent_id == first["id"]
    assert json.loads(event)["replyToGenerationId"] == first["id"]
    invalid = _request("invalid-reply", "Reply to a response in another conversation.")
    invalid["replyToGenerationId"] = "missing-generation"
    with pytest.raises(HTTPException) as error:
        records.create("local", session.id, invalid, "invalid-reply", "test", "test-model",
                       reject_if_active=False)
    assert error.value.status_code == 404


def test_new_topic_starts_a_fresh_branch_and_add_keeps_selected_parent(live_branching_store):
    store, session, records, _ = live_branching_store
    root = records.create("local", session.id, _request("root-topic", "Explain ecosystems."),
                          "root-topic", "test", "test-model")
    followup = records.create("local", session.id, _request("add-topic", "Also explain food chains."),
                             "add-topic", "test", "test-model", reject_if_active=False)
    fresh_request = _request("new-topic", "New topic: explain linear equations.")
    fresh = records.create("local", session.id, fresh_request, "new-topic", "test", "test-model",
                           reject_if_active=False)
    with store.engine.connect() as connection:
        parent_rows = connection.execute(text("""
            SELECT id,parent_branch_id FROM response_branches WHERE owner_id='local' AND session_id=:session
        """), {"session": session.id}).all()
    parents = {branch_id: parent_id for branch_id, parent_id in parent_rows}
    assert parents[root["branchId"]] is None
    assert parents[followup["branchId"]] == root["branchId"]
    assert parents[fresh["branchId"]] is None


def test_branch_selection_uses_compare_and_set_and_is_not_changed_by_late_completion(live_branching_store):
    _, session, records, branches = live_branching_store
    first = records.create("local", session.id, _request("branch-one", "Explain ecosystems."),
                           "branch-one", "test", "test-model")
    second = records.create("local", session.id, _request("branch-two", "Also explain food chains."),
                            "branch-two", "test", "test-model", reject_if_active=False)
    initial = branches.list_branches("local", session.id)
    assert initial["selectedBranchId"] == second["branchId"]
    selected = branches.select_branch("local", session.id, first["branchId"], initial["revision"])
    assert selected["selectedBranchId"] == first["branchId"]
    records.claim_capacity(second["id"], conversation_limit=2, global_limit=4)
    assert branches.list_branches("local", session.id)["selectedBranchId"] == first["branchId"]
    with pytest.raises(HTTPException) as error:
        branches.select_branch("local", session.id, second["branchId"], initial["revision"])
    assert error.value.status_code == 409


def test_expired_owner_preserves_checkpoint_and_rejects_late_deltas(live_branching_store):
    _, session, records, _ = live_branching_store
    created = records.create("local", session.id, _request("checkpoint-message", "What is an ecosystem?"),
                            "checkpoint-message", "test", "test-model")
    owner = records.claim_capacity(created["id"], conversation_limit=1, global_limit=4, lease_seconds=30)
    assert owner is not None
    records.transition(created["id"], "streaming", owner_token=owner["ownerToken"])
    records.append_event(created["id"], "text.delta", {"text": "An ecosystem "}, owner_token=owner["ownerToken"])
    interrupted = records.interrupt_expired_leases(owner["leaseExpiresAt"] + 1)
    assert interrupted == [created["id"]]
    saved = records.get("local", created["id"])
    assert saved["status"] == "interrupted"
    assert saved["partialOutput"] == "An ecosystem "
    with pytest.raises(RuntimeError, match="no longer owns"):
        records.append_event(created["id"], "text.delta", {"text": "late content"}, owner_token=owner["ownerToken"])


def test_stop_message_is_persisted_without_moving_selected_branch(live_branching_store):
    _, session, records, branches = live_branching_store
    active = records.create("local", session.id, _request("active-message", "Explain gravity."),
                           "active-message", "test", "test-model")
    owner = records.claim_capacity(active["id"], conversation_limit=2, global_limit=4)
    assert owner is not None
    records.transition(active["id"], "streaming", owner_token=owner["ownerToken"])
    before = branches.list_branches("local", session.id)
    with records.store.transaction() as connection:
        receipt = branches.accept_cancel_message(connection, "local", session.id, "stop-message",
                                                 "Please stop generating.", "ask")
    after = branches.list_branches("local", session.id)
    assert receipt["targetGenerationId"] == active["id"]
    assert receipt["targetStatus"] == "cancel_requested"
    assert after["selectedBranchId"] == before["selectedBranchId"]
    assert any(branch["relation"] == "cancel" and branch["message"] == "Please stop generating."
               for branch in after["branches"])
    with pytest.raises(RuntimeError, match="no longer owns"):
        records.append_event(active["id"], "text.delta", {"text": "late content"}, owner_token=owner["ownerToken"])


def test_remote_cancel_remains_requested_until_lease_owner_or_recovery_confirms(live_branching_store, monkeypatch):
    from backend.app.generation_service import GenerationManager

    store, session, records, _ = live_branching_store
    monkeypatch.setenv("LIVE_BRANCHING_ENABLED", "true")

    class Provider:
        provider_name = "test"
        model = "test-model"

    manager = GenerationManager(store, Provider())
    created = records.create("local", session.id, _request("remote-cancel", "Explain gravity."),
                             "remote-cancel", "test", "test-model")
    owner = records.claim_capacity(created["id"], conversation_limit=2, global_limit=4, lease_seconds=30)
    assert owner
    records.transition(created["id"], "streaming", owner_token=owner["ownerToken"])
    result = manager.cancel("local", created["id"])
    assert result["status"] == "cancel_requested"
    still_owned = records.get("local", created["id"])
    assert still_owned["status"] == "cancel_requested" and still_owned["capacityReserved"]
    with store.engine.connect() as connection:
        global_count = connection.execute(text("""
            SELECT active_count FROM generation_capacity WHERE scope_type='global' AND scope_id='deployment'
        """)).scalar_one()
    assert global_count == 1
    assert records.interrupt_expired_leases(owner["leaseExpiresAt"] + 1) == [created["id"]]


def test_cancel_wins_race_against_failure_and_sse_observers_attach_cleanly(live_branching_store):
    from backend.app.generation_service import GenerationManager

    store, session, records, _ = live_branching_store
    created = records.create("local", session.id, _request("cancel-failure-race", "Explain gravity."),
        "cancel-failure-race", "test", "test-model")
    owner = records.claim_capacity(created["id"], conversation_limit=1, global_limit=4)
    assert owner is not None
    records.transition(created["id"], "streaming", owner_token=owner["ownerToken"])
    records.request_cancel("local", created["id"])

    with pytest.raises(RuntimeError):
        records.transition(created["id"], "failed", error_code="PROVIDER_ERROR",
                           owner_token=owner["ownerToken"])
    assert records.get("local", created["id"])["status"] == "cancel_requested"
    records.transition(created["id"], "cancelled", error_code="CANCELLED",
                       owner_token=owner["ownerToken"])

    manager = GenerationManager(store, None)
    manager._attach(created["id"])
    assert manager.observers[created["id"]] == 1
    manager._detach("local", created["id"])
    assert manager.observers[created["id"]] == 0


def test_failed_generation_retry_reuses_message_and_links_new_execution(live_branching_store):
    store, session, records, _ = live_branching_store

    def save_context(_connection, generation_id, _submission):
        return {"journeyRevision": 1, "contextSnapshot": {
            "revision": 1,
            "turns": [{"generationId": generation_id, "question": "Explain ecosystems.", "status": "pending"}],
        }}

    original = records.create("local", session.id, _request("retry-message", "Explain ecosystems."),
        "retry-message", "test", "test-model", on_create=save_context)
    records.transition(original["id"], "preparing")
    records.transition(original["id"], "interrupted", error_code="STREAM_INTERRUPTED")

    retry = records.retry("local", original["id"], "retry-execution", on_create=save_context)
    duplicate = records.retry("local", original["id"], "retry-execution", on_create=save_context)
    assert retry["id"] != original["id"]
    assert retry["parentGenerationId"] == original["id"]
    assert retry["messageId"] == original["messageId"]
    assert retry["conversationSeq"] == original["conversationSeq"]
    assert duplicate["id"] == retry["id"] and duplicate["createdNow"] is False
    with store.engine.connect() as connection:
        user_events = connection.execute(text("""
            SELECT COUNT(*) FROM conversation_events
            WHERE owner_id='local' AND session_id=:session AND event_type='user_message'
        """), {"session": session.id}).scalar_one()
        retry_snapshot = connection.execute(text("""
            SELECT 1 FROM generation_context_snapshots WHERE generation_id=:id
        """), {"id": retry["id"]}).first()
    assert user_events == 1
    assert retry_snapshot is not None


def test_manager_retry_adds_new_pending_execution_without_duplicate_user_event(live_branching_store, monkeypatch):
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.app.journey_service import JourneyService

    store, session, records, _ = live_branching_store
    monkeypatch.setenv("GENERATION_GLOBAL_ACTIVE_LIMIT", "1")

    class Provider:
        provider_name = "test"
        model = "test-model"

    service = JourneyService(store, None)
    source_command = GenerationRequest(mode="ask", message="Explain ecosystems.", action="message",
        expectedRevision=1, clientMessageId="retry-e2e-message")
    source = records.create("local", session.id, source_command.model_dump(mode="json", by_alias=True),
        "retry-e2e-message", "test", "test-model",
        on_create=lambda connection, generation_id, submission: service.submit_stream_turn(
            connection, "local", session.id, source_command, generation_id, submission))
    records.transition(source["id"], "preparing")
    records.transition(source["id"], "interrupted", error_code="STREAM_INTERRUPTED")

    blocker_command = GenerationRequest(mode="ask", message="Also explain food chains.", action="message",
        expectedRevision=1, clientMessageId="retry-e2e-blocker")
    blocker = records.create("local", session.id, blocker_command.model_dump(mode="json", by_alias=True),
        "retry-e2e-blocker", "test", "test-model",
        on_create=lambda connection, generation_id, submission: service.submit_stream_turn(
            connection, "local", session.id, blocker_command, generation_id, submission),
        reject_if_active=False)
    assert records.claim_capacity(blocker["id"], conversation_limit=2, global_limit=1)

    retried = GenerationManager(store, Provider()).retry("local", source["id"], "retry-e2e-execution")
    journey = service.get("local", session.id)
    with store.engine.connect() as connection:
        user_events = connection.execute(text("""
            SELECT COUNT(*) FROM conversation_events WHERE owner_id='local' AND session_id=:session
                AND event_type='user_message'
        """), {"session": session.id}).scalar_one()
    assert retried["status"] == "queued"
    assert retried["parentGenerationId"] == source["id"]
    assert retried["messageId"] == source["messageId"]
    assert sum(turn.get("generationId") == retried["id"] for turn in journey["turns"]) == 1
    assert sum(turn.get("clientMessageId") == source["messageId"] for turn in journey["turns"]) == 2
    assert user_events == 2


def test_manager_durably_accepts_and_retries_when_provider_is_temporarily_unavailable(live_branching_store):
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager

    store, session, records, _ = live_branching_store
    manager = GenerationManager(store, None, provider_getter=lambda: None)
    command = GenerationRequest(mode="ask", message="Explain ecosystems.", gear="Guided",
        expectedRevision=1, clientMessageId="provider-down-message")

    accepted = manager.create("local", session.id, command, "provider-down-message")
    assert accepted["status"] == "queued"
    assert accepted["messageId"] == "provider-down-message"

    with store.engine.connect() as connection:
        events = connection.execute(text("""
            SELECT event_type FROM generation_events WHERE generation_id=:id ORDER BY sequence
        """), {"id": accepted["id"]}).scalars().all()
    assert "message.accepted" in events
    assert records.get("local", accepted["id"])["status"] == "queued"

    lease = records.claim_capacity(accepted["id"], conversation_limit=1, global_limit=1)
    assert lease is not None
    records.transition(accepted["id"], "interrupted", error_code="STREAM_INTERRUPTED",
                       owner_token=lease["ownerToken"])

    retried = manager.retry("local", accepted["id"], "provider-down-retry")
    assert retried["status"] == "queued"
    assert retried["messageId"] == accepted["messageId"]
    assert retried["id"] != accepted["id"]


def test_generation_runner_binds_verified_owner_and_conversation_usage_scope(live_branching_store, monkeypatch):
    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.app.usage.context import current_root, current_store

    store, session, records, _ = live_branching_store
    manager = GenerationManager(store, None, provider_getter=lambda: None)
    command = GenerationRequest(mode="ask", message="Explain ecosystems.", gear="Guided",
        expectedRevision=1, clientMessageId="usage-scope-message")
    record = records.create("local", session.id, command.model_dump(mode="json", by_alias=True),
        "usage-scope-message", "pending", "pending")
    lease = records.claim_capacity(record["id"], conversation_limit=1, global_limit=1)
    assert lease is not None

    async def inspect_scope(*_args, **_kwargs):
        assert principal_context.get().owner_id == "local"
        assert current_store.get() is store
        assert current_root.get() == session.id

    monkeypatch.setattr(manager, "_run_generation", inspect_scope)
    coroutine = manager._run(record["id"], "local", command, None, lease["ownerToken"])
    try:
        coroutine.send(None)
    except StopIteration:
        pass
    else:
        pytest.fail("The test runner should complete without suspending")
    assert principal_context.get().owner_id == "local"
    assert current_store.get() is None
    assert current_root.get() is None


def test_stale_write_counter_is_persisted(live_branching_store):
    store, session, records, _ = live_branching_store
    record = records.create("local", session.id, _request("stale-counter", "Explain ecosystems."),
        "stale-counter", "test", "test-model")
    with pytest.raises(RuntimeError, match="no longer owns"):
        records.update_metrics(record["id"], {"ignored": True}, owner_token="stale-owner")
    with store.engine.connect() as connection:
        count = connection.execute(text("""
            SELECT value FROM live_branching_metric_counters WHERE name='stale_write_rejections'
        """)).scalar_one()
    assert count == 1


def test_operations_metrics_are_aggregate_and_report_acceptance_percentiles(live_branching_store):
    store, session, records, _ = live_branching_store
    record = records.create("local", session.id, _request("metrics-message", "Repeatable test prompt."),
        "metrics-message", "test", "test-model")
    records.record_acceptance_latency(record["id"], 42.0)
    record_client_outbox_snapshot(store, "local", session.id, OutboxMetricsRequest(
        clientId="tab-client-123", queuedCount=2, sendingCount=1, acceptedCount=0,
        failedCount=1, choiceCount=0, oldestPendingAgeSeconds=17.5))
    result = live_branching_metrics(store, 24)
    assert result["acceptanceLatencyMs"] == {"count": 1, "p50": 42.0, "p95": 42.0}
    assert result["activeGenerations"]["deployment"] == 1
    assert result["clientOutbox"]["available"] is True
    assert result["clientOutbox"]["queued"] == 2
    assert result["clientOutbox"]["sending"] == 1
    assert result["clientOutbox"]["failed"] == 1
    assert result["clientOutbox"]["oldestPendingAgeSeconds"] == 17.5
    assert "Repeatable test prompt." not in json.dumps(result)


def test_two_full_responses_can_stream_under_bounded_concurrency(live_branching_store, monkeypatch):
    import asyncio

    from types import SimpleNamespace

    from backend.app.generation_models import GenerationRequest
    from backend.app.generation_service import GenerationManager
    from backend.app.journey_service import JourneyService

    store, session, records, branches = live_branching_store
    # Python's Windows event-loop self-pipe uses socketpair(). In this
    # restricted desktop sandbox, its TCP fallback blocks inside accept();
    # let the integration test run in CI/normal environments and skip here.
    probe_result = []

    def probe_socketpair():
        try:
            left, right = socket.socketpair()
            left.close()
            right.close()
            probe_result.append(True)
        except OSError:
            probe_result.append(False)

    probe = threading.Thread(target=probe_socketpair, daemon=True)
    probe.start()
    probe.join(timeout=0.5)
    if probe.is_alive() or not probe_result or not probe_result[0]:
        pytest.skip("The restricted Windows sandbox blocks asyncio's socketpair self-pipe.")

    monkeypatch.setenv("LIVE_BRANCHING_ENABLED", "true")
    monkeypatch.setenv("GENERATION_PER_CONVERSATION_ACTIVE_LIMIT", "2")
    monkeypatch.setenv("GENERATION_GLOBAL_ACTIVE_LIMIT", "2")
    both_preparing = threading.Barrier(2)
    prepared_messages = []

    def prepare(self, owner, session_id, command, cancel_check=None, on_event=None,
                generation_id=None, journey_snapshot=None):
        both_preparing.wait(timeout=5)
        prepared_messages.append(command.message)
        return {
            "journey": journey_snapshot,
            "generationId": generation_id,
            "conceptId": "ecology",
            "title": "Ecology",
            "directReply": f"Reply to {command.message}",
            "responseKind": "social",
            "sources": [],
            "noteReceipt": {"label": "test", "notes": [], "totalCharacters": 0},
            "contextId": None,
            "actionId": f"action-{generation_id}",
            "question": command.message,
        }

    def commit(self, connection, owner, prepared, command, body, visualizations=None):
        return SimpleNamespace(id=f"lesson-{prepared['generationId']}"), {
            "revision": prepared["journey"]["revision"], "sessionId": session.id,
        }

    monkeypatch.setattr(JourneyService, "prepare_stream", prepare)
    monkeypatch.setattr(JourneyService, "commit_stream", commit)

    class Provider:
        provider_name = "test"
        model = "test-model"

    manager = GenerationManager(store, Provider())

    async def run():
        first = manager.create("local", session.id,
            GenerationRequest(mode="ask", message="First question", gear="Guided", expectedRevision=1),
            "parallel-first")
        second = manager.create("local", session.id,
            GenerationRequest(mode="ask", message="Second question", gear="Guided", expectedRevision=1),
            "parallel-second")
        assert first["status"] == second["status"] == "preparing"
        await asyncio.wait_for(asyncio.gather(*list(manager.tasks.values())), timeout=10)
        return first, second

    first, second = asyncio.run(run())
    assert sorted(prepared_messages) == ["First question", "Second question"]
    assert records.get("local", first["id"])["status"] == "completed"
    assert records.get("local", second["id"])["status"] == "completed"
    assert records.get("local", first["id"])["partialOutput"] == "Reply to First question"
    assert records.get("local", second["id"])["partialOutput"] == "Reply to Second question"
    assert branches.list_branches("local", session.id)["selectedBranchId"] == second["branchId"]
