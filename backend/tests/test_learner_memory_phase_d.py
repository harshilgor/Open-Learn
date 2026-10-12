"""Learner memory Phase D: time intent, decay, ranking, retrieval, use tracking."""
import json
import math
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.app.learner_memory import policy, retrieval, store as facts
from backend.app.learner_memory.service import LearnerMemoryService
from backend.app.storage import Store

from test_learner_memory_phase_a import conversation  # noqa: F401  (fixture)

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc).timestamp()  # a Monday
DAY = 86400.0


def fact(identifier, statement, *, kind="goal", subject=None, course=None, origin="user_stated", status="active", event_date=None,
         learned_days_ago=1.0, importance=None, stability=None, sensitive=False, last_used_days_ago=None, concept_ids=()):
    importance = policy.DEFAULT_IMPORTANCE.get(kind, 0.5) if importance is None else importance
    return {"id": identifier, "kind": kind, "statement": statement, "subject_key": subject or f"{kind}:{identifier}", "course_id": course,
            "concept_ids": list(concept_ids), "event_date": event_date, "origin": origin, "status": status, "sensitive": sensitive,
            "confidence": 0.9, "importance": importance, "learned_at": NOW - learned_days_ago * DAY, "valid_from": NOW - learned_days_ago * DAY,
            "invalid_at": None, "superseded_by": None, "basis": [], "last_used_at": None if last_used_days_ago is None else NOW - last_used_days_ago * DAY,
            "use_count": 0, "confirmed_at": None, "stability_days": stability or 30 * (1 + 2 * importance), "needs_review": False,
            "policy_version": "test", "revision": 1}


def insert(db, owner, row):
    with db.transaction() as conn:
        conn.execute(text(f"INSERT INTO memory_facts({facts.FACT_COLUMNS}) VALUES(:owner_id,:id,:kind,:statement,:subject_key,:course_id,:concept_ids,"
                          ":event_date,:origin,:status,:sensitive,:confidence,:importance,:learned_at,:valid_from,:invalid_at,:superseded_by,:basis,"
                          ":last_used_at,:use_count,:confirmed_at,:stability_days,:needs_review,:policy_version,:revision)"),
                     {**row, "owner_id": owner, "concept_ids": json.dumps(row["concept_ids"]), "basis": json.dumps(row["basis"])})
        facts.bump_version(conn, owner)  # every writer bumps the owner's memory version


def episode(db, owner, identifier, summary, *, days_ago, course=None, topics=()):
    end = NOW - days_ago * DAY
    with db.transaction() as conn:
        conn.execute(text("""INSERT INTO memory_episodes(owner_id,id,session_id,course_id,period_start,period_end,turn_range,summary,topics,method,basis,status,created_at,revision)
            VALUES(:owner,:id,'session',:course,:start,:end,'{}',:summary,:topics,'extractive-v1','[]','active',:end,1)"""),
            {"owner": owner, "id": identifier, "course": course, "start": end - 3600, "end": end, "summary": summary, "topics": json.dumps(list(topics))})
        facts.bump_version(conn, owner)


@pytest.fixture
def db(tmp_path):
    value = Store(tmp_path / "retrieval.db")
    yield value
    value.close()


def window(intent):
    if intent is None:
        return None
    day = lambda value: datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    return day(intent.start), day(intent.end - 1), intent.prefers_future


@pytest.mark.parametrize("message,expected", [
    ("what did we cover last week", ("2026-10-05", "2026-10-11", False)),
    ("anything due this week?", ("2026-10-12", "2026-10-18", True)),
    ("plan for next week", ("2026-10-19", "2026-10-25", True)),
    ("what did I do last month", ("2026-09-01", "2026-09-30", False)),
    ("today's plan", ("2026-10-12", "2026-10-12", True)),
    ("tomorrow's quiz", ("2026-10-13", "2026-10-13", True)),
    ("yesterday we did limits", ("2026-10-11", "2026-10-11", False)),
    ("my exam is friday", ("2026-10-16", "2026-10-16", True)),
    ("next friday", ("2026-10-23", "2026-10-23", True)),
    ("last friday", ("2026-10-09", "2026-10-09", False)),
    ("what did we do in september", ("2026-09-01", "2026-09-30", False)),
    ("exam on Nov 3rd", ("2026-11-03", "2026-11-03", True)),
    ("is 2026-11-03 free", ("2026-11-03", "2026-11-03", True)),
    ("when is my midterm", ("2026-10-12", "2027-04-12", True)),
    ("the sun is hot", None),
    ("explain limits please", None),
])
def test_time_intent_windows(message, expected):
    assert window(retrieval.parse_time_intent(message, NOW, "UTC")) == expected


def test_time_intent_uses_the_learner_timezone():
    late_sunday_in_la = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc).timestamp()  # Sunday 22:00 in Los Angeles
    assert retrieval.parse_time_intent("today", late_sunday_in_la, "America/Los_Angeles").start == datetime(2026, 10, 11, 7, tzinfo=timezone.utc).timestamp()


def test_retention_and_stability_golden_values():
    assert math.isclose(policy.retention(fact("a", "x", kind="interest", importance=0.0, learned_days_ago=30), NOW), math.exp(-1))
    assert policy.retention(fact("d", "x", kind="deadline", event_date="2026-10-05"), NOW) == 1.0  # within the 7-day grace
    assert policy.retention(fact("d", "x", kind="deadline", event_date="2026-09-01"), NOW) < 1.0
    old_constraint = fact("c", "x", kind="constraint", learned_days_ago=900)
    assert policy.retention(old_constraint, NOW) == policy.CONSTRAINT_RETENTION_FLOOR
    assert policy.retention({**old_constraint, "origin": "inferred"}, NOW) < policy.CONSTRAINT_RETENTION_FLOOR
    assert policy.retention(fact("u", "x", learned_days_ago=300, last_used_days_ago=0), NOW) == 1.0
    assert policy.stability_after_use(40) == 50 and policy.stability_after_use(300) == 365


def test_bm25_normalizes_and_ignores_stopwords():
    scores = retrieval.bm25(retrieval.tokens("when is my calculus midterm"),
                            [retrieval.tokens("Has a calculus midterm on 2026-11-03."), retrieval.tokens("Loves basketball."), []])
    assert scores[0] == 1.0 and scores[1] == 0.0 and scores[2] == 0.0


def test_ranking_orders_by_relevance_strength_importance_and_scope():
    candidates = [
        fact("midterm", "Has a calculus midterm on 2026-11-03.", kind="deadline", event_date="2026-11-03"),
        fact("calc-goal", "Wants an A in calculus.", course="calc"),
        fact("calc-goal-global", "Wants an A in calculus overall."),
        fact("basketball", "Loves basketball.", kind="interest"),
        fact("lab", "Lab report due 2026-10-20.", kind="deadline", event_date="2026-10-20"),
        fact("stale", "Wants to learn calculus proofs.", learned_days_ago=400, importance=0.2, stability=30),
    ]
    ranked = retrieval.rank(candidates, [], message="how should I prepare for the calculus midterm", now=NOW, course_id="calc")
    order = [entry.item["id"] for entry in ranked]
    assert order[0] == "midterm"
    assert order.index("calc-goal") < order.index("calc-goal-global") < order.index("stale")
    assert "basketball" not in order          # below MIN_RELEVANCE
    assert "lab" in order                     # deadline within 14 days survives without lexical match
    ranked_future = retrieval.rank(candidates, [], message="when is my next deadline", now=NOW, intent=retrieval.parse_time_intent("when is my next deadline", NOW))
    assert [entry.item["id"] for entry in ranked_future][:2] == ["lab", "midterm"]


def test_selection_caps_kinds_episodes_and_budget(monkeypatch):
    ranked = [retrieval.Scored(fact(f"g{index}", f"Goal {index}"), "fact", 0.9, 1, 1 - index / 100) for index in range(4)]
    ranked += [retrieval.Scored({"id": f"e{index}", "summary": "Covered limits."}, "episode", 0.9, 1, 0.5 - index / 100) for index in range(5)]
    chosen, episodes, omitted = retrieval.select(ranked, exclude_ids={"g0"})
    assert [entry.item["id"] for entry in chosen] == ["g1", "g2"] and len(episodes) == 3
    assert {"id": "g3", "reason": "kind_diversity"} in omitted and {"id": "e3", "reason": "episode_limit"} in omitted
    monkeypatch.setattr(policy, "RETRIEVED_MAX_TOKENS", 15)
    chosen, _, omitted = retrieval.select(ranked)
    assert [entry.item["id"] for entry in chosen] == ["g0"] and {"id": "g1", "reason": "memory_budget"} in omitted


def seed(db, owner="alice"):
    insert(db, owner, fact("pref", "Prefers short answers with one example.", kind="preference", learned_days_ago=10))
    insert(db, owner, fact("calc-pref", "Prefers formal notation in Calculus I.", kind="preference", course="calc", learned_days_ago=5))
    insert(db, owner, fact("midterm", "Has a calculus midterm on 2026-11-03.", kind="deadline", event_date="2026-11-03", course="calc", learned_days_ago=3))
    insert(db, owner, fact("goal", "Wants an A in calculus.", course="calc", learned_days_ago=20))
    insert(db, owner, fact("bball", "Loves basketball; sports analogies help.", kind="interest", learned_days_ago=40))
    insert(db, owner, fact("secret", "Has dyslexia.", kind="constraint", sensitive=True))
    insert(db, owner, fact("tentative", "Maybe likes diagrams.", kind="preference", status="tentative"))
    with db.transaction() as conn:
        conn.execute(text("INSERT INTO courses(id,owner_id,name,goal,created_at,updated_at,archived_at) VALUES('calc',:owner,'Calculus I','',:now,:now,NULL)"),
                     {"owner": owner, "now": datetime.fromtimestamp(NOW, timezone.utc)})


def test_context_renders_profile_and_relevant_memories_deterministically(db):
    seed(db)
    service = LearnerMemoryService(db)
    result = service.context("alice", "calc", "how do I prepare for the calculus midterm", now=NOW, timezone_name="UTC")
    lines = result.text.splitlines()
    assert lines[0] == policy.MEMORY_BLOCK_HEADER + ":"
    assert lines[1:4] == ["Profile:", "- [preference · Calculus I] Prefers formal notation in Calculus I. (learner said, 2026-10-07)",
                          "- [preference] Prefers short answers with one example. (learner said, 2026-10-02)"]
    assert "Relevant memories:" in lines and "- [deadline · Calculus I] Has a calculus midterm on 2026-11-03. (learner said, 2026-10-09)" in lines
    assert "dyslexia" not in result.text and "diagrams" not in result.text and "basketball" not in result.text
    assert result.fact_ids[:2] == ("calc-pref", "pref") and "midterm" in result.fact_ids
    assert result.trace["profile"] == ["calc-pref", "pref"] and all("statement" not in item for item in result.trace["included"])
    again = service.context("alice", "calc", "how do I prepare for the calculus midterm", now=NOW, timezone_name="UTC")
    assert again.text == result.text  # byte-stable for provider prompt caching
    assert service.context("bob", "calc", "how do I prepare for the calculus midterm", now=NOW) is None


def test_assessment_context_only_carries_preferences_and_constraints(db):
    seed(db)
    episode(db, "alice", "ep1", "Practiced calculus midterm problems.", days_ago=2, course="calc")
    result = LearnerMemoryService(db).context("alice", "calc", "calculus midterm practice quiz", purpose="assessment", now=NOW)
    assert set(result.fact_ids) == {"calc-pref", "pref"} and result.episode_ids == ()
    assert "Relevant memories" not in result.text and "Earlier sessions" not in result.text


def test_short_impersonal_messages_skip_retrieval_but_keep_the_profile(db):
    seed(db)
    result = LearnerMemoryService(db).context("alice", "calc", "ok thanks", now=NOW)
    assert result.fact_ids == ("calc-pref", "pref") and result.trace["included"] == []


def test_episodes_answer_what_did_we_cover_last_week(db):
    seed(db)
    episode(db, "alice", "ep-last-week", "Chain rule and implicit differentiation; struggled with nested functions.", days_ago=5, course="calc")
    episode(db, "alice", "ep-old", "Limits and continuity.", days_ago=40, course="calc")
    result = LearnerMemoryService(db).context("alice", "calc", "what did we cover last week?", now=NOW, timezone_name="UTC")
    assert result.episode_ids == ("ep-last-week",)
    assert "Earlier sessions:" in result.text and "2026-10-07 · Chain rule" in result.text


def test_record_use_reinforces_once_a_day(db):
    insert(db, "alice", fact("goal", "Wants an A in calculus.", stability=40))
    with db.transaction() as conn:
        facts.record_use(conn, "alice", ["goal", "missing"], now=NOW)
        facts.record_use(conn, "alice", ["goal"], now=NOW + 60)
    with db.engine.connect() as conn:
        row = facts.get_fact(conn, "alice", "goal")
    assert (row["use_count"], row["last_used_at"], row["stability_days"], row["revision"]) == (2, NOW + 60, 50.0, 1)


def test_retrieval_v2_reaches_the_prompt_and_records_use_at_commit(conversation, monkeypatch):
    client, db, provider, session = conversation
    monkeypatch.setenv("OPENLEARN_MEMORY_CHAT_CONTEXT", "on")
    monkeypatch.setenv("OPENLEARN_MEMORY_RETRIEVAL_V2", "on")
    monkeypatch.setenv("AI_TUTOR_DEV_CONTEXT_INSPECTOR", "1")
    insert(db, "local", fact("exam", "Has a probability exam on 2026-11-20.", kind="deadline", event_date="2026-11-20", learned_days_ago=1))
    insert(db, "local", fact("hobby", "Loves basketball.", kind="interest"))
    created = client.post(f"/v1/sessions/{session.id}/generations", json={"mode": "ask", "message": "Help me get ready for my probability exam",
                          "gear": "Guided", "expectedRevision": 1}, headers={"Idempotency-Key": "v2"})
    assert created.status_code == 202, created.text
    assert "event: generation.completed" in client.get(f"/v1/generations/{created.json()['id']}/events").text
    prompt = provider.streamed[-1]
    prompt = prompt if isinstance(prompt, str) else prompt.legacy_prompt()
    assert "Relevant memories:" in prompt and "Has a probability exam on 2026-11-20." in prompt and "basketball" not in prompt
    with db.engine.connect() as conn:
        used = facts.get_fact(conn, "local", "exam")
        unused = facts.get_fact(conn, "local", "hobby")
    assert used["use_count"] == 1 and used["last_used_at"] is not None and unused["use_count"] == 0
    inspected = client.get(f"/v1/generations/{created.json()['id']}/context")
    assert inspected.status_code == 200, inspected.text
    trace = inspected.json()["memoryTrace"]
    assert trace["blockIncluded"] and [item["id"] for item in trace["included"]] == ["exam"]
    assert "probability" not in json.dumps(trace)


@pytest.mark.parametrize("message,expected", [
    ("what is due in november", ("2026-11-01", "2026-11-30", True)),
    ("anything in march", ("2027-03-01", "2027-03-31", True)),
    ("what did we study in november", ("2025-11-01", "2025-11-30", False)),
    ("what did we cover in october", ("2026-10-01", "2026-10-31", False)),
])
def test_month_questions_look_forward_unless_past_tense(message, expected):
    assert window(retrieval.parse_time_intent(message, NOW, "UTC")) == expected


def test_cached_ranking_rows_never_serve_stale_facts(db):
    from backend.app.learner_memory import service as memory_service
    service = LearnerMemoryService(db)
    insert(db, "alice", fact("old-exam", "Has a calculus midterm on 2026-11-03.", kind="deadline", event_date="2026-11-03", subject="deadline:calc-midterm"))
    query = "when is my calculus midterm"
    assert service.context("alice", None, query, now=NOW).fact_ids == ("old-exam",)
    assert any(key[1] == "alice" for key in memory_service._FACTS)
    # Supersede, then add a replacement with the same count, revision sum and
    # learned_at: only the version counter tells these sets apart.
    with db.transaction() as conn:
        conn.execute(text("UPDATE memory_facts SET status='superseded',revision=revision+1 WHERE id='old-exam'"))
        facts.bump_version(conn, "alice")
    insert(db, "alice", fact("new-exam", "Has a calculus midterm on 2026-11-10.", kind="deadline", event_date="2026-11-10", subject="deadline:calc-midterm"))
    assert service.context("alice", None, query, now=NOW).fact_ids == ("new-exam",)
    with db.transaction() as conn:
        facts.delete_fact(conn, "alice", "new-exam")
    assert service.context("alice", None, query, now=NOW) is None
    # Per-use fields are read fresh even when the static rows are cached.
    insert(db, "alice", fact("goal", "Wants to learn calculus proofs.", learned_days_ago=300, stability=30))
    weak = service.context("alice", None, "calculus proofs help", now=NOW).trace["included"][0]["strength"]
    with db.transaction() as conn:
        facts.record_use(conn, "alice", ["goal"], now=NOW)
    strong = service.context("alice", None, "calculus proofs help", now=NOW).trace["included"][0]["strength"]
    assert weak < 0.01 and strong == 1.0


def test_indexed_and_plain_lexical_scores_agree():
    docs = {"a": retrieval._tokens("Has a calculus midterm"), "b": retrieval._tokens("Loves basketball"), "c": retrieval._tokens("calculus calculus proofs")}
    plain = retrieval.bm25(retrieval.tokens("calculus midterm"), list(docs.values()))
    indexed = retrieval.bm25_indexed(retrieval.tokens("calculus midterm"), retrieval.build_index(docs))
    assert [round(value, 9) for value in plain] == [round(indexed.get(key, 0.0), 9) for key in docs]
