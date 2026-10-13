from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.material_routes import material_owner
from backend.app.storage import Store
from backend.app.usage.ledger import Ledger
from backend.app.usage_events_routes import build_usage_events_router


def _app(store, owner="alice"):
    app = FastAPI()
    app.include_router(build_usage_events_router(lambda: store))
    app.dependency_overrides[material_owner] = lambda: owner
    return TestClient(app)


def _append_revisions(ledger, owner, count, start=100.0):
    with ledger.transaction() as conn:
        ledger.account(conn, owner)
        for offset in range(count):
            ledger.update(conn, owner, start + offset)


def test_usage_event_feed_is_ordered_replayable_paginated_and_owner_scoped(tmp_path):
    store = Store(tmp_path / "usage-events.db")
    try:
        ledger = Ledger(store)
        _append_revisions(ledger, "alice", 3)
        _append_revisions(ledger, "bob", 2, start=200.0)
        client = _app(store)

        first = client.get("/v1/usage/events?afterRevision=0&limit=2")
        assert first.status_code == 200, first.text
        body = first.json()
        assert first.headers["cache-control"] == "private, no-store"
        assert [event["revision"] for event in body["events"]] == [1, 2]
        assert [event["kind"] for event in body["events"]] == ["usage.updated", "usage.updated"]
        assert body["nextRevision"] == 2
        assert body["latestRevision"] == 3
        assert body["hasMore"] is True
        assert body["resnapshotRequired"] is False
        assert set(body["events"][0]) == {"id", "revision", "kind", "createdAt"}

        # An interrupted consumer can repeat its cursor without duplicate
        # effects: events keep stable IDs and ordering across replay.
        replay = client.get("/v1/usage/events?afterRevision=0&limit=2").json()
        assert [event["id"] for event in replay["events"]] == [event["id"] for event in body["events"]]

        second = client.get(f"/v1/usage/events?afterRevision={body['nextRevision']}&limit=2").json()
        assert [event["revision"] for event in second["events"]] == [3]
        assert second["hasMore"] is False

        # Each principal sees its own revision namespace and event identities.
        bob_events = _app(store, "bob").get("/v1/usage/events").json()
        assert [event["revision"] for event in bob_events["events"]] == [1, 2]
        assert {event["id"] for event in bob_events["events"]}.isdisjoint(
            {event["id"] for event in body["events"]}
        )
        assert client.get("/v1/usage/events?afterRevision=3").json()["events"] == []
    finally:
        store.close()


def test_usage_event_feed_requires_resnapshot_if_history_has_a_gap(tmp_path):
    store = Store(tmp_path / "usage-event-gap.db")
    try:
        ledger = Ledger(store)
        _append_revisions(ledger, "alice", 3)
        with store.transaction() as conn:
            conn.execute(text("DELETE FROM usage_outbox WHERE owner_id='alice' AND revision=2"))

        # The gap is inside the first page, after revision 1. A cursor at zero
        # must not return revision 1 and then silently jump past the missing 2.
        response = _app(store).get("/v1/usage/events?afterRevision=0")
        assert response.status_code == 200
        assert response.json() == {
            "events": [],
            "nextRevision": 3,
            "latestRevision": 3,
            "hasMore": False,
            "resnapshotRequired": True,
        }
    finally:
        store.close()


def test_usage_event_feed_rejects_future_or_invalid_cursors(tmp_path):
    store = Store(tmp_path / "usage-event-cursor.db")
    try:
        ledger = Ledger(store)
        _append_revisions(ledger, "alice", 1)
        client = _app(store)
        assert client.get("/v1/usage/events?afterRevision=2").status_code == 422
        assert client.get("/v1/usage/events?afterRevision=-1").status_code == 422
        assert client.get("/v1/usage/events?limit=101").status_code == 422
    finally:
        store.close()
