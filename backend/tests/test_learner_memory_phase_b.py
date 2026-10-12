"""Learner memory Phase B: schema, backfill, dual-write, erasure, read APIs."""
import json
import time

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.app.database import BACKEND_ROOT
from backend.app.learner_memory import store as facts
from backend.app.learner_memory.service import LearnerMemoryService
from backend.app.source_memory import SourceMemory
from backend.app.storage import Store


@pytest.fixture
def db(tmp_path):
    value = Store(tmp_path / "memory.db")
    yield value
    value.close()


def save_preference(db, owner, source_id, statement, *, scope=None, identifier=None):
    memory = SourceMemory(db)
    memory.revise(owner, source_id, statement, course_id=scope, expected_revision=0)
    return memory.derive(owner, "preference", {"statement": statement}, [{"sourceId": source_id, "revision": 1}],
                         scope=scope, explicit=True, identifier=identifier)["id"]


def all_facts(db, owner):
    with db.engine.connect() as conn:
        return facts.list_facts(conn, owner)


def insert_fact(db, owner, fact_id, *, statement="Has a midterm on 2026-11-03.", kind="deadline", status="active",
                subject="deadline:calc-midterm", course=None, superseded_by=None, sensitive=False):
    now = time.time()
    with db.transaction() as conn:
        conn.execute(text(f"""INSERT INTO memory_facts({facts.FACT_COLUMNS}) VALUES(:owner,:id,:kind,:statement,:subject,:course,'[]',
            NULL,'user_stated',:status,:sensitive,1.0,0.9,:now,:now,NULL,:superseded_by,'[]',NULL,0,NULL,90,:false,'test',1)"""),
            {"owner": owner, "id": fact_id, "kind": kind, "statement": statement, "subject": subject, "course": course,
             "status": status, "sensitive": sensitive, "now": now, "superseded_by": superseded_by, "false": False})


def migration_config(url):
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["openlearn_explicit_url"] = True
    return config


def test_migration_backfills_existing_preferences_and_downgrades(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}"
    config = migration_config(url)
    command.upgrade(config, "0085_object_cleanup_queue")
    engine = create_engine(url)

    def derived(owner, identifier, value, *, kind="preference", valid=True):
        conn.execute(text("INSERT INTO memory_derived(owner_id,id,kind,payload,valid) VALUES(:owner,:id,:kind,:payload,:valid)"),
                     {"owner": owner, "id": identifier, "kind": kind, "payload": json.dumps(value), "valid": valid})

    def source(owner, identifier, updated_at):
        conn.execute(text("INSERT INTO memory_sources(owner_id,id,kind,course_id,revision,deleted,updated_at) VALUES(:owner,:id,'note',NULL,1,false,:at)"),
                     {"owner": owner, "id": identifier, "at": updated_at})

    with engine.begin() as conn:
        for identifier, at in (("s1", 100.0), ("s2", 200.0), ("s3", 300.0), ("s4", 400.0), ("s5", 500.0)):
            source("alice", identifier, at)
        source("bob", "s1", 50.0)
        basis = lambda sid: [{"sourceId": sid, "revision": 1}]
        derived("alice", "d1", {"value": {"statement": "Prefers short answers."}, "basis": basis("s1"), "scope": None, "explicit": True})
        derived("alice", "d2", {"value": {"statement": "Use textbook notation."}, "basis": basis("s2"), "scope": "calc", "explicit": True})
        # The same statement saved twice in one scope becomes one fact.
        derived("alice", "d3", {"value": {"statement": "prefers  SHORT answers."}, "basis": basis("s3"), "scope": None, "explicit": True})
        derived("alice", "d4", {"value": {"tentative": True, "value": {"statement": "Maybe likes diagrams."}}, "basis": basis("s4"), "scope": None, "explicit": False})
        derived("alice", "d5", {"value": {"statement": "Dismissed."}, "basis": basis("s5"), "scope": None, "explicit": True}, valid=False)
        derived("alice", "d6", {"value": {"method": "extractive"}, "basis": basis("s1"), "scope": None, "explicit": False}, kind="summary")
        derived("bob", "d1", {"value": {"statement": "Bob's preference."}, "basis": basis("s1"), "scope": None, "explicit": True})

    command.upgrade(config, "0086_learner_memory")
    with engine.connect() as conn:
        rows = {row["statement"]: dict(row) for row in conn.execute(text("SELECT * FROM memory_facts WHERE owner_id='alice'")).mappings()}
        bob = conn.execute(text("SELECT statement FROM memory_facts WHERE owner_id='bob'")).scalars().all()
    assert set(rows) == {"Prefers short answers.", "Use textbook notation.", "Maybe likes diagrams."}
    short = rows["Prefers short answers."]
    assert (short["id"], short["origin"], short["status"], short["kind"]) == (facts.fact_id_for_derived("alice", "d1"), "user_stated", "active", "preference")
    assert [ref["derivedId"] for ref in json.loads(short["basis"])] == ["d1", "d3"]
    assert short["learned_at"] == 300.0 and short["confirmed_at"] == 300.0
    assert short["subject_key"] == facts.preference_subject_key("Prefers short answers.")
    assert rows["Use textbook notation."]["course_id"] == "calc"
    assert (rows["Maybe likes diagrams."]["origin"], rows["Maybe likes diagrams."]["status"]) == ("inferred", "tentative")
    assert rows["Maybe likes diagrams."]["confirmed_at"] is None
    assert bob == ["Bob's preference."]

    command.downgrade(config, "0085_object_cleanup_queue")
    with engine.connect() as conn:
        tables = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
    assert not {"memory_facts", "memory_episodes", "memory_embeddings", "memory_settings"} & tables
    assert "memory_derived" in tables
    engine.dispose()


def test_explicit_preference_writes_a_fact_in_the_same_transaction(db):
    first = save_preference(db, "alice", "p1", "Prefers one worked example.", identifier="preference_fixed")
    # A retried admission with the same identity is idempotent.
    SourceMemory(db).derive("alice", "preference", {"statement": "Prefers one worked example."}, [{"sourceId": "p1", "revision": 1}],
                            explicit=True, identifier="preference_fixed")
    second = save_preference(db, "alice", "p2", "prefers one worked  example.")
    save_preference(db, "alice", "p3", "Use textbook notation.", scope="calc")

    items = all_facts(db, "alice")
    assert len(items) == 2
    merged = next(fact for fact in items if fact["course_id"] is None)
    assert (merged["origin"], merged["status"], merged["confidence"], merged["stability_days"]) == ("user_stated", "active", 1.0, 365.0)
    assert [ref["derivedId"] for ref in merged["basis"]] == [first, second]
    assert merged["revision"] == 2
    assert next(fact for fact in items if fact["course_id"] == "calc")["statement"] == "Use textbook notation."
    assert all_facts(db, "bob") == []


def test_dismissing_and_removing_sources_forget_only_unsupported_facts(db):
    first = save_preference(db, "alice", "p1", "Prefers short answers.")
    second = save_preference(db, "alice", "p2", "Prefers short answers.")
    with db.transaction() as conn:
        facts.forget_derived(conn, "alice", first)
    [kept] = all_facts(db, "alice")
    assert [ref["derivedId"] for ref in kept["basis"]] == [second]
    with db.transaction() as conn:
        facts.forget_derived(conn, "alice", second)
    assert all_facts(db, "alice") == []

    save_preference(db, "alice", "p3", "Use textbook notation.")
    save_preference(db, "alice", "p4", "Explain with sports analogies.")
    SourceMemory(db).remove("alice", "p3", 1)
    SourceMemory(db).revise("alice", "p4", "Explain with music analogies.", expected_revision=1)
    [revised] = all_facts(db, "alice")
    assert revised["statement"] == "Explain with sports analogies."
    assert revised["status"] == "archived" and revised["invalid_at"] is not None


def test_one_active_fact_per_subject_and_scope(db):
    insert_fact(db, "alice", "fact_a")
    insert_fact(db, "alice", "fact_b", course="calc")
    insert_fact(db, "alice", "fact_c", status="superseded")
    insert_fact(db, "bob", "fact_a")
    with pytest.raises(IntegrityError):
        insert_fact(db, "alice", "fact_d")


def test_chat_block_reads_active_non_sensitive_fact_preferences(db):
    save_preference(db, "alice", "p1", "Prefers short answers.")
    insert_fact(db, "alice", "fact_sensitive", kind="preference", statement="Sensitive preference.", subject="preference:private", sensitive=True)
    insert_fact(db, "alice", "fact_tentative", kind="preference", statement="Tentative preference.", subject="preference:maybe", status="tentative")
    block = LearnerMemoryService(db).chat_block("alice", None, None, "x")
    assert block["preferences"] == [{"learnerSaid": "Prefers short answers.", "scope": "global"}]


def test_account_erasure_removes_every_memory_row_for_the_owner_only(db):
    from backend.app.identity_data import erase_owner
    for owner in ("alice", "bob"):
        save_preference(db, owner, "p1", "Prefers short answers.")
        now = time.time()
        with db.transaction() as conn:
            conn.execute(text("""INSERT INTO memory_episodes(owner_id,id,session_id,course_id,period_start,period_end,turn_range,summary,topics,method,basis,status,created_at,revision)
                VALUES(:owner,'episode_1','session_1',NULL,:now,:now,'{}','Covered limits.','[]','extractive-v1','[]','active',:now,1)"""), {"owner": owner, "now": now})
            conn.execute(text("INSERT INTO memory_embeddings(owner_id,item_type,item_id,model,dims,vector,content_hash,created_at) VALUES(:owner,'fact','f','m',2,'[0,1]','h',:now)"),
                         {"owner": owner, "now": now})
            facts.put_settings(conn, owner, learning_enabled=False, expected_revision=0)
    erase_owner(db, "alice")
    with db.engine.connect() as conn:
        for table in ("memory_facts", "memory_episodes", "memory_embeddings", "memory_settings"):
            owners = conn.execute(text(f"SELECT owner_id FROM {table}")).scalars().all()
            assert owners == ["bob"], table


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.app.identity import Principal, principal_context
    from backend.app.identity_middleware import IdentityMiddleware
    from backend.app.learner_memory.routes import build_learner_memory_router
    from backend.app.memory_routes import build_memory_router
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    store = Store(tmp_path / "api.db")
    token = principal_context.set(Principal("local", "local"))
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    app.include_router(build_memory_router(lambda: store))
    app.include_router(build_learner_memory_router(lambda: store))
    with TestClient(app) as client:
        yield client, store
    store.close()
    principal_context.reset(token)


def test_fact_and_episode_read_apis_are_owner_scoped_and_private(api):
    client, store = api
    saved = client.post("/v1/memory/preferences", json={"statement": "Prefers short answers.", "confirmed": True})
    assert saved.status_code == 200, saved.text
    insert_fact(store, "local", "fact_old", status="superseded", superseded_by="fact_new", statement="Midterm on 2026-11-01.")
    insert_fact(store, "local", "fact_new", statement="Midterm on 2026-11-03.")
    insert_fact(store, "local", "fact_shadow", status="shadow", subject="deadline:shadow")
    insert_fact(store, "bob", "fact_bob", statement="Bob's midterm.")

    listed = client.get("/v1/memory/facts")
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    statements = {item["statement"] for item in listed.json()["items"]}
    assert statements == {"Prefers short answers.", "Midterm on 2026-11-01.", "Midterm on 2026-11-03."}
    preference = next(item for item in listed.json()["items"] if item["kind"] == "preference")
    assert preference["origin"] == "user_stated" and preference["basis"][0]["type"] == "memory_source"
    assert [item["id"] for item in client.get("/v1/memory/facts", params={"kind": "deadline", "status": "active"}).json()["items"]] == ["fact_new"]
    assert client.get("/v1/memory/facts", params={"kind": "misconception"}).status_code == 422
    assert client.get("/v1/memory/facts", params={"status": "shadow"}).status_code == 422

    history = client.get("/v1/memory/facts/fact_new/history").json()["items"]
    assert [item["id"] for item in history] == ["fact_old", "fact_new"]
    assert client.get("/v1/memory/facts/fact_bob/history").status_code == 404
    assert client.get("/v1/memory/facts/fact_shadow/history").status_code == 404

    # Dismissing the saved preference through the existing route forgets the fact.
    derived_id = saved.json()["id"]
    assert client.delete(f"/v1/memory/derived/{derived_id}").status_code == 200
    assert "Prefers short answers." not in {item["statement"] for item in client.get("/v1/memory/facts").json()["items"]}

    assert client.get("/v1/memory/episodes").json() == {"items": []}
    assert client.delete("/v1/memory/episodes/missing").status_code == 404


def test_memory_settings_use_optimistic_revisions(api):
    client, _ = api
    assert client.get("/v1/memory/settings").json() == {"learningEnabled": True, "revision": 0, "updatedAt": None, "extraction": "off"}
    paused = client.put("/v1/memory/settings", json={"learningEnabled": False, "expectedRevision": 0})
    assert paused.status_code == 200 and paused.json()["learningEnabled"] is False and paused.json()["revision"] == 1
    assert client.put("/v1/memory/settings", json={"learningEnabled": True, "expectedRevision": 0}).status_code == 409
    resumed = client.put("/v1/memory/settings", json={"learningEnabled": True, "expectedRevision": 1})
    assert resumed.json()["revision"] == 2 and resumed.json()["learningEnabled"] is True
    assert client.put("/v1/memory/settings", json={"learningEnabled": True, "expectedRevision": 1, "ownerId": "bob"}).status_code == 422
