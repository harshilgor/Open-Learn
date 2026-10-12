"""Redis cache-aside layer: fail-open behavior, invalidation, and per-namespace freshness.

Uses fakeredis; no Redis server is required. See docs/REDIS_CACHE_ASIDE_IMPLEMENTATION.md.
"""
from __future__ import annotations

import json
import time
from contextlib import nullcontext
from types import SimpleNamespace

import fakeredis
import pytest
from sqlalchemy import text

from backend.app import cache
from backend.app.cache import (CircuitBreaker, NullCache, RedisCache, configure_cache, data_key, erase_owner,
                               generation_key, get_or_load, invalidate, json_codec, metrics, owner_child_scope,
                               owner_scope, reset_cache)
from backend.app.storage import Store

ALL = frozenset(cache.NAMESPACES)


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis()


@pytest.fixture
def use_cache(redis_client):
    """Install a fakeredis-backed cache serving every namespace (or a chosen set)."""
    def install(serving=ALL, shadow=frozenset(), client=None, breaker=None):
        instance = RedisCache(client or redis_client, serving=serving, shadow=shadow, breaker=breaker)
        configure_cache(instance)
        return instance
    metrics.reset()
    yield install
    reset_cache()
    metrics.reset()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    instance = Store(tmp_path / "cache.db")
    yield instance
    instance.close()


class Counter:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.values[min(self.calls, len(self.values)) - 1]


def read(namespace, scope, loader, parts=None, ttl=60, **kwargs):
    return get_or_load(namespace, scope, parts or {"k": 1}, loader, ttl_seconds=ttl, **json_codec(), **kwargs)


# --- Foundation -------------------------------------------------------------

def test_miss_then_hit_and_ttl_jitter(use_cache, redis_client):
    use_cache()
    loader = Counter({"value": 1})
    assert read("course", "s", loader) == {"value": 1}
    assert read("course", "s", loader) == {"value": 1}
    assert loader.calls == 1
    key = data_key("course", "s", 0, {"k": 1})
    assert 54 <= redis_client.ttl(key) <= 66
    assert metrics.snapshot()["course"] == {"hit": 1, "miss": 1}


def test_unlisted_namespace_bypasses_reads(use_cache):
    use_cache(serving=frozenset({"course"}))
    loader = Counter({"value": 1})
    read("calendar", "s", loader)
    read("calendar", "s", loader)
    assert loader.calls == 2


def test_null_cache_calls_loader_exactly_once_per_read():
    configure_cache(NullCache())
    try:
        loader = Counter("x")
        assert read("course", "s", loader) == "x"
        assert loader.calls == 1
        invalidate("course", "s")  # no-op, must not raise
    finally:
        reset_cache()


def test_decode_failure_deletes_entry_and_reloads(use_cache, redis_client):
    use_cache()
    redis_client.set(data_key("course", "s", 0, {"k": 1}), b"not json")
    loader = Counter({"fresh": True})
    assert read("course", "s", loader) == {"fresh": True}
    assert metrics.snapshot()["course"]["decode_error"] == 1
    assert read("course", "s", loader) == {"fresh": True}
    assert loader.calls == 1


def test_schema_bump_ignores_old_entries(use_cache, monkeypatch):
    use_cache()
    read("course", "s", Counter("old"))
    monkeypatch.setattr(cache, "CACHE_SCHEMA", cache.CACHE_SCHEMA + 1)
    assert read("course", "s", Counter("new")) == "new"


def test_owner_isolation(use_cache):
    use_cache()
    assert owner_scope("alice") != owner_scope("bob")
    assert "alice" not in owner_scope("alice")
    read("course", owner_scope("alice"), Counter("alice-data"))
    assert read("course", owner_scope("bob"), Counter("bob-data")) == "bob-data"


class BrokenRedis:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            self.calls += 1
            raise ConnectionError("redis down")
        return fail


def test_redis_outage_fails_open_and_breaker_stops_calls(use_cache):
    broken = BrokenRedis()
    now = [0.0]
    use_cache(client=broken, breaker=CircuitBreaker(threshold=5, cooldown=30, clock=lambda: now[0]))
    loader = Counter("db")
    for _ in range(10):
        assert read("course", "s", loader) == "db"
        invalidate("course", "s")
    assert loader.calls == 10
    calls_when_open = broken.calls
    assert calls_when_open <= 6  # threshold failures, then the breaker short-circuits
    read("course", "s", loader)
    assert broken.calls == calls_when_open
    assert cache.cache_status() == "degraded"
    now[0] = 31.0  # cooldown elapsed: one probe allowed, fails, breaker re-opens
    read("course", "s", loader)
    assert broken.calls == calls_when_open + 1
    assert metrics.snapshot()["other"]["breaker_open"] >= 2


def test_breaker_closes_after_successful_probe(redis_client):
    now = [0.0]
    breaker = CircuitBreaker(threshold=1, cooldown=5, clock=lambda: now[0])
    breaker.failure()
    assert not breaker.allow()
    now[0] = 6
    assert breaker.allow()
    breaker.success()
    assert breaker.allow() and not breaker.is_open


def test_stale_write_back_race_cannot_survive_invalidation(use_cache):
    """A slow reader that loaded old data before a write commits must not win."""
    use_cache()
    state = {"value": "old"}

    def slow_loader():
        snapshot = state["value"]
        state["value"] = "new"            # a writer commits while we were loading ...
        invalidate("course", "s")         # ... and bumps the generation after commit
        return snapshot
    assert read("course", "s", slow_loader) == "old"
    assert read("course", "s", lambda: state["value"]) == "new"


def test_single_flight_waits_for_holder(use_cache, redis_client):
    use_cache()
    key = data_key("web_evidence", "t", 0, {"k": 1})
    redis_client.set("ol:lock:" + key, b"1", px=5000)
    redis_client.set(key, json.dumps(["cached"]).encode())
    redis_client.delete(key)

    loader = Counter(["from-provider"])
    original_get = redis_client.get

    def get_then_appear(name):
        if name == key and loader.calls == 0 and not getattr(get_then_appear, "seen", False):
            get_then_appear.seen = True
            return None  # first read: miss while another request holds the lock
        if name == key:
            return json.dumps(["filled-by-holder"]).encode()
        return original_get(name)
    redis_client.get = get_then_appear
    assert read("web_evidence", "t", loader, single_flight=True) == ["filled-by-holder"]
    assert loader.calls == 0


def test_single_flight_does_not_wait_when_redis_is_unavailable(use_cache):
    use_cache(client=BrokenRedis(), breaker=CircuitBreaker(threshold=100))
    started = time.perf_counter()
    assert read("web_evidence", "t", Counter("x"), single_flight=True) == "x"
    assert time.perf_counter() - started < 0.1


def test_shadow_mode_returns_database_value_and_counts_mismatches(use_cache):
    use_cache(serving=frozenset(), shadow=frozenset({"course"}))
    assert read("course", "s", Counter({"v": 1})) == {"v": 1}         # populates
    assert read("course", "s", Counter({"v": 1})) == {"v": 1}         # match
    assert read("course", "s", Counter({"v": 2})) == {"v": 2}         # stale cache never served
    counts = metrics.snapshot()["course"]
    assert counts["shadow_match"] == 1 and counts["shadow_mismatch"] == 1


def test_erase_owner_removes_only_that_owner(use_cache, redis_client):
    use_cache()
    alice, bob = owner_scope("alice"), owner_scope("bob")
    read("course", alice, Counter("a"))
    read("material_blocks", owner_child_scope("alice", "v1"), Counter("a-blocks"))
    invalidate("course", alice)
    read("course", bob, Counter("b"))
    erase_owner("alice")
    remaining = [key.decode() for key in redis_client.scan_iter("ol:*")]
    assert remaining and all(alice not in key for key in remaining)
    assert any(bob in key for key in remaining)


def test_unknown_namespace_is_rejected(use_cache):
    use_cache()
    with pytest.raises(ValueError):
        read("everything", "s", Counter(1))
    with pytest.raises(ValueError):
        invalidate("everything", "s")


def test_cache_disabled_without_url(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CACHE_ENABLED", "true")
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(cache.build_cache_from_env(), NullCache)
    monkeypatch.setenv("OPENLEARN_CACHE_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert isinstance(cache.build_cache_from_env(), NullCache)


def test_env_namespaces_and_shadow_are_disjoint(monkeypatch):
    monkeypatch.setenv("OPENLEARN_CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("OPENLEARN_CACHE_NAMESPACES", "course, calendar,bogus")
    monkeypatch.setenv("OPENLEARN_CACHE_SHADOW", "calendar")
    built = cache.build_cache_from_env()
    assert built.serving == {"course"} and built.shadow == {"calendar"}


# --- After-commit invalidation ---------------------------------------------

def generation(client, namespace, scope):
    raw = client.get(generation_key(namespace, scope))
    return int(raw) if raw else 0


def test_invalidation_flushes_after_commit_deduplicated(use_cache, redis_client, store):
    use_cache()
    with store.transaction():
        invalidate("course", "s")
        invalidate("course", "s")
        assert generation(redis_client, "course", "s") == 0  # not before commit
    assert generation(redis_client, "course", "s") == 1


def test_rollback_discards_invalidation(use_cache, redis_client, store):
    use_cache()
    with pytest.raises(RuntimeError):
        with store.transaction():
            invalidate("course", "s")
            raise RuntimeError("rollback")
    assert generation(redis_client, "course", "s") == 0


def test_borrowed_connection_flushes_with_owning_transaction(use_cache, redis_client, store):
    use_cache()

    def service_write(connection=None):
        with (nullcontext(connection) if connection is not None else store.transaction()):
            invalidate("course", "s")
    with store.transaction() as conn:
        service_write(conn)
        assert generation(redis_client, "course", "s") == 0
    assert generation(redis_client, "course", "s") == 1


def test_nested_transaction_flushes_on_its_own_commit(use_cache, redis_client, store):
    use_cache()
    with store.transaction():
        with store.transaction():
            invalidate("course", "inner")
        assert generation(redis_client, "course", "inner") == 1
        invalidate("course", "outer")
        assert generation(redis_client, "course", "outer") == 0
    assert generation(redis_client, "course", "outer") == 1


def test_invalidation_outside_transaction_is_immediate(use_cache, redis_client):
    use_cache()
    invalidate("course", "s")
    assert generation(redis_client, "course", "s") == 1


# --- Namespaces: read-after-write and parity --------------------------------

def _session(store, owner="local", course_id=None, suffix="1"):
    from backend.app.graph_generator import GraphGenerator
    from backend.app.models import TopicScope, utc_now
    from backend.app.session_models import LearningSession
    scope = TopicScope(id="scope-cache-" + suffix, topic="biology", resolved_meaning="ecology",
                       objective="understand ecosystems", depth="introductory", created_at=utc_now())
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    session = LearningSession(id="session-cache-" + suffix, learner_id=owner, graph_id=graph.id, course_id=course_id,
                              goal="understand ecosystems", created_at=utc_now(), updated_at=utc_now())
    store.save_session(session)
    return session


def test_course_reads_follow_course_material_and_session_writes(use_cache, store):
    from backend.app.course_models import CourseCreate, CourseUpdate
    from backend.app.course_service import CourseService
    from backend.app.material_service import MaterialService
    use_cache(serving=frozenset({"course"}))
    svc = CourseService(store)
    course = svc.create_course("local", CourseCreate(name="Ecology", goal="Food webs"))
    first = svc.list_courses("local")
    assert [c.name for c in first] == ["Ecology"]
    assert svc.list_courses("local") == first
    assert metrics.snapshot()["course"]["hit"] >= 1

    svc.update_course("local", course.id, CourseUpdate(name="Ecology II"))
    assert svc.get_course("local", course.id).name == "Ecology II"
    assert [c.name for c in svc.list_courses("local")] == ["Ecology II"]

    MaterialService(store).create("local", SimpleNamespace(title="Notes", role="reference", media_type="text/plain",
                                                           byte_count=4, course_id=course.id))
    assert svc.list_courses("local")[0].material_count == 1

    _session(store, course_id=course.id)
    assert svc.get_course("local", course.id).summary.session_count == 1

    # Parity: a cached hit equals an uncached load.
    cached = svc.get_course("local", course.id)
    assert cached == svc._load_course("local", course.id)

    svc.delete_course("local", course.id)
    assert svc.get_course("local", course.id) is None
    assert svc.list_courses("local") == []


def test_ordinary_session_saves_do_not_invalidate_courses(use_cache, redis_client, store):
    from backend.app.course_models import CourseCreate
    from backend.app.course_service import CourseService
    use_cache(serving=frozenset({"course"}))
    course = CourseService(store).create_course("local", CourseCreate(name="Ecology", goal="Food webs"))
    session = _session(store, course_id=course.id)
    before = generation(redis_client, "course", owner_scope("local"))
    store.save_session(session.model_copy(update={"title": "Renamed"}))
    assert generation(redis_client, "course", owner_scope("local")) == before


def test_concept_graph_tracks_revisions_and_reports(use_cache, store):
    from backend.app.stable_concept_models import ConceptCreate, MappingReport
    from backend.app.stable_concept_service import StableConceptService
    use_cache(serving=frozenset({"concept_graph"}))
    svc = StableConceptService(store)
    empty = svc.graph("local")
    assert svc.graph("local") == empty
    concept = svc.create("local", ConceptCreate(title="Food web", definition="Feeding relations in an ecosystem.",
                                                discipline="biology", expected_grain="One idea."))["concept"]
    graph = svc.graph("local")
    assert [c["id"] for c in graph["stable_concepts"]] == [concept["id"]]
    revision = graph["revision"]
    svc.report("local", MappingReport(concept_id=concept["id"], description="Mapping looks wrong."))
    reported = svc.graph("local")
    assert reported["revision"] == revision  # reports don't bump the revision ...
    assert len(reported["concept_mapping_reports"]) == 1  # ... but still invalidate


def test_material_blocks_cache_follows_reprocessing_and_delete(use_cache, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.material_routes import build_material_router
    monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    use_cache(serving=frozenset({"material_blocks"}))
    store = Store(tmp_path / "materials.db")
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    app.include_router(build_material_router(lambda: store))
    try:
        with TestClient(app) as client:
            item = client.post("/v1/materials/text", json={"title": "Algebra", "text": "Linear equations.\n\nVariables."}).json()
            url = f"/v1/material-versions/{item['versionId']}/blocks"
            from backend.app.material_service import MaterialService
            # Processing may be deferred to the worker depending on process state; drain it so the
            # version is "ready" (only ready versions are cached).
            while MaterialService(store).process_one():
                pass
            first = client.get(url).json()
            assert client.get(url).json() == first
            assert metrics.snapshot()["material_blocks"]["hit"] == 1
            with store.transaction() as conn:  # simulate a reprocessing rewrite through the service hook
                # The dev identity's owner id depends on prior local-identity setup; read the real owner.
                owner = conn.execute(text("SELECT m.owner_id FROM materials m JOIN material_versions v ON v.material_id=m.id "
                                          "WHERE v.id=:v"), {"v": item["versionId"]}).scalar_one()
                conn.execute(text("UPDATE material_blocks SET text='Rewritten.' WHERE version_id=:v"), {"v": item["versionId"]})
                from backend.app.material_service import MaterialService
                MaterialService.invalidate_blocks(owner, item["versionId"])
            assert {b["text"] for b in client.get(url).json()["blocks"]} == {"Rewritten."}
            assert client.get(url, headers={"X-Dev-Learner-Id": "other"}).status_code == 404
            assert client.delete(f"/v1/materials/{item['id']}").status_code == 200
            assert client.get(url).status_code == 404  # ownership check is never cached
    finally:
        store.close()


def _event(calendar, title="Physics revision"):
    from backend.app.calendar.contracts import EventInput
    return EventInput(calendarId=calendar, title=title, temporal={"mode": "timed", "timezone": "America/Los_Angeles",
                      "start": "2026-11-01T10:00:00-08:00", "end": "2026-11-01T10:30:00-08:00"})


def test_calendar_occurrences_follow_event_writes_and_undo(use_cache, store):
    from backend.app.calendar.service import CalendarService
    use_cache(serving=frozenset({"calendar"}))
    svc = CalendarService(store)
    calendar = svc.calendars("alice")["items"][0]["id"]
    assert svc.calendars("alice") == svc.calendars("alice")
    window = ("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")
    assert svc.occurrences("alice", *window)["items"] == []
    operation = svc.create("alice", _event(calendar), "first")
    feed = svc.occurrences("alice", *window)
    assert [item["title"] for item in feed["items"]] == ["Physics revision"]
    assert svc.occurrences("alice", *window) == feed  # hit
    uncached = svc._occurrences("alice", *window)
    assert {k: v for k, v in feed.items() if k != "generatedAt"} == {k: v for k, v in uncached.items() if k != "generatedAt"}
    svc.undo("alice", operation["id"], "undo")
    assert svc.occurrences("alice", *window)["items"] == []
    assert svc.occurrences("bob", *window)["items"] == []


def test_usage_display_invalidates_when_generation_completes(use_cache, redis_client, store):
    from backend.app.generation_store import GenerationStore
    from backend.app.identity import Principal, principal_context
    use_cache(serving=frozenset({"usage_display"}))
    token = principal_context.set(Principal("local", "local"))
    try:
        session = _session(store)
        records = GenerationStore(store)
        created = records.create("local", session.id, {"mode": "ask", "message": "Explain.", "clientMessageId": "m1"},
                                 "m1", "test", "test-model")
        for status in ("preparing", "streaming", "finalizing"):
            records.transition(created["id"], status)
        before = generation(redis_client, "usage_display", owner_scope("local"))
        records.transition(created["id"], "completed")
        assert generation(redis_client, "usage_display", owner_scope("local")) == before + 1
    finally:
        principal_context.reset(token)


def test_web_evidence_uses_redis_instead_of_sql_when_enabled(use_cache, store):
    from backend.app.web_evidence.store import WebEvidenceStore
    evidence = WebEvidenceStore(store)
    loader = Counter([{"url": "https://example.org", "excerpt": "x"}])
    args = dict(owner_id="local", tenant_id="default", fingerprint="fp", ttl_seconds=600, loader=loader)

    use_cache(serving=frozenset({"web_evidence"}))
    assert evidence.cached_search("webcache_a", **args) == loader.values[0]
    assert evidence.cached_search("webcache_a", **args) == loader.values[0]
    assert loader.calls == 1
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM context_records WHERE kind='web_evidence_cache'")).scalar_one() == 0

    configure_cache(NullCache())  # local/desktop: original SQL cache path
    assert evidence.cached_search("webcache_b", **args) == loader.values[0]
    assert evidence.cached_search("webcache_b", **args) == loader.values[0]
    assert loader.calls == 2
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM context_records WHERE kind='web_evidence_cache'")).scalar_one() == 1


def test_web_evidence_zero_ttl_never_caches(use_cache, store):
    from backend.app.web_evidence.store import WebEvidenceStore
    use_cache(serving=frozenset({"web_evidence"}))
    loader = Counter([])
    for _ in range(2):
        WebEvidenceStore(store).cached_search("webcache_z", owner_id="local", tenant_id="default", fingerprint="fp",
                                              ttl_seconds=0, loader=loader)
    assert loader.calls == 2


# --- Operations ------------------------------------------------------------

def test_connection_budget_includes_redis_and_rejects_overflow():
    from backend.scripts.check_connection_budget import validate
    budget = json.loads(open("deploy/connection-budget.json", encoding="utf-8").read())
    result = validate(budget)
    assert result["peakRedisIncludingReserves"] <= budget["redis"]["connectionLimit"]
    budget["redis"]["roles"][0]["poolSize"] = 100
    with pytest.raises(ValueError):
        validate(budget)
    budget = json.loads(open("deploy/connection-budget.json", encoding="utf-8").read())
    budget["redis"]["roles"] = budget["redis"]["roles"][1:]
    with pytest.raises(ValueError):
        validate(budget)


def test_redis_pool_size_follows_role(monkeypatch):
    from backend.app.capacity import REDIS_ROLE_POOLS, redis_pool_size
    monkeypatch.setenv("OPENLEARN_PROCESS_ROLE", "generation")
    monkeypatch.delenv("OPENLEARN_REDIS_POOL_SIZE", raising=False)
    assert redis_pool_size() == REDIS_ROLE_POOLS["generation"]
    monkeypatch.setenv("OPENLEARN_REDIS_POOL_SIZE", "3")
    assert redis_pool_size() == 3


def test_performance_snapshot_reports_cache_counters(use_cache):
    from backend.app.performance import registry
    use_cache()
    read("course", "s", Counter(1))
    snapshot = registry.snapshot()
    assert snapshot["cache"]["status"] == "ok"
    assert snapshot["cache"]["namespaces"]["course"]["miss"] == 1


@pytest.mark.skipif(not __import__("os").getenv("OPENLEARN_TEST_REDIS_URL"),
                    reason="Set OPENLEARN_TEST_REDIS_URL to run against a real Redis/Valkey server")
def test_real_redis_round_trip_invalidation_and_erasure(monkeypatch, store):
    import redis
    client = redis.Redis.from_url(__import__("os").environ["OPENLEARN_TEST_REDIS_URL"], socket_timeout=1)
    client.flushdb()
    configure_cache(RedisCache(client, serving=ALL))
    try:
        loader = Counter({"v": 1}, {"v": 2})
        assert read("course", owner_scope("alice"), loader) == {"v": 1}
        assert read("course", owner_scope("alice"), loader) == {"v": 1}
        with store.transaction():
            invalidate("course", owner_scope("alice"))
        assert read("course", owner_scope("alice"), loader) == {"v": 2}
        assert read("web_evidence", "tenant", Counter(["hit"]), single_flight=True) == ["hit"]
        erase_owner("alice")
        assert not list(client.scan_iter(f"ol:*{owner_scope('alice')}*"))
    finally:
        client.flushdb()
        reset_cache()


def test_readiness_reports_degraded_cache_without_failing(use_cache):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    breaker = CircuitBreaker(threshold=1, cooldown=60)
    use_cache(client=BrokenRedis(), breaker=breaker)
    read("course", "s", Counter(1))
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "cache": "degraded"}
