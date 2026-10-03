"""Deterministic quality fixtures; provider judgement is covered by workflow tests."""
import pytest
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
from pydantic import ValidationError
from fastapi import HTTPException

from backend.app.assessment_generation import deterministic_quality_failures
from backend.app.assessment_models import Candidate, Criterion, Option, QuizCreate
from backend.app.quiz_service import QuizService
from backend.app.storage import Store
from backend.app.workflow_store import WorkflowStore
from backend.app.models import utc_now


def make_store():
    # Avoid pytest's Windows Temp ACL issue and SQLite's distinct in-memory migration connection.
    return Store(Path.cwd() / "backend" / "data" / f"assessment-quality-{uuid4().hex}.db")


def item(**changes):
    values = {"concept_id": "conditioning", "kind": "single", "stem": "Which population remains after conditioning on an event?", "reasoning_target": "Identify the restricted population.", "family": "conditional_population", "options": [Option(id="a", label="All observations"), Option(id="b", label="Only observations compatible with the event")], "correct_ids": ["b"], "solution": "Conditioning restricts the population to observations compatible with the event.", "criteria": [Criterion(id="population", description="Identifies the compatible population.", weight=1)], "hints": ["Which observations can still occur?"], "source_ids": ["span-1"]}
    values.update(changes)
    return Candidate(**values)


def sources():
    return [{"spanId": "span-1", "text": "Conditioning restricts possible observations."}]


def test_leakage_duplicate_ambiguous_and_unsupported_fixtures():
    assert "answer_leakage" in deterministic_quality_failures(item(options=[Option(id="a", label="Conditioning restricts the population to observations compatible with the event."), Option(id="b", label="All observations")], correct_ids=["a"]), sources(), [])
    assert "duplicate_template" in deterministic_quality_failures(item(stem="Which population remains after conditioning on 42 events?"), sources(), [{"stem": "Which population remains after conditioning on 12 events?"}])
    assert "ambiguous_options" in deterministic_quality_failures(item(options=[Option(id="a", label="Same"), Option(id="b", label=" same ")]), sources(), [])
    assert "unsupported_source" in deterministic_quality_failures(item(source_ids=["not-owned"]), sources(), [])


def test_exposure_and_alternate_valid_answer_contract():
    assert "exposure_limit" in deterministic_quality_failures(item(), sources(), [], exposure_count=3)
    # Written items deliberately have a rubric rather than a single answer string, allowing valid alternatives.
    written = item(kind="short", options=[], correct_ids=[])
    assert written.criteria[0].weight == 1


def test_modes_reject_unsupported_or_invalid_configuration():
    assert QuizCreate(session_id="s", mode="timed_short_quiz", mode_config={"duration_seconds": 300}).mode == "timed_short_quiz"
    with pytest.raises(ValidationError):
        QuizCreate(session_id="s", mode="timed_short_quiz", mode_config={"duration_seconds": 5})
    with pytest.raises(ValidationError):
        QuizCreate(session_id="s", mode="topic_drill", mode_config={"duration_seconds": 300})


def test_unapproved_or_withdrawn_item_cannot_be_presented_or_graded():
    store = make_store()
    try:
        records = WorkflowStore(store)
        with store.transaction() as conn:
            records.put(conn, "local", "item", {"id": "item-x", "qualityStatus": "withdrawn"})
            records.put(conn, "local", "presentation", {"id": "presentation-x", "itemId": "item-x", "quizId": "quiz-x"})
        with pytest.raises(HTTPException) as raised:
            QuizService(store, None).private_item("local", "presentation-x")
        assert raised.value.status_code == 409
    finally:
        store.close()


def test_timed_pause_resume_persists_remaining_duration():
    store = make_store()
    try:
        records, service = WorkflowStore(store), QuizService(store, None)
        quiz = {"id": "timed-x", "mode": "timed_short_quiz", "modeConfig": {"duration_seconds": 300}, "remainingSeconds": 300, "deadlineAt": None, "status": "paused", "current": "presentation-x"}
        with store.transaction() as conn:
            records.put(conn, "local", "quiz", quiz)
        with store.transaction() as conn:
            service.resume(conn, "local", "timed-x", 1)
        resumed = records.read("local", "timed-x", "quiz")
        assert resumed["deadlineAt"] and resumed["status"] == "in_progress"
        with store.transaction() as conn:
            service.pause(conn, "local", "timed-x", resumed["revision"])
        paused = records.read("local", "timed-x", "quiz")
        assert paused["deadlineAt"] is None and 0 < paused["remainingSeconds"] <= 300
        paused["deadlineAt"] = (utc_now() - timedelta(seconds=1)).isoformat()
        with store.transaction() as conn:
            records.put(conn, "local", "quiz", paused, expected=paused["revision"])
        with pytest.raises(HTTPException) as expired:
            service._ensure_active_time(records.read("local", "timed-x", "quiz"))
        assert expired.value.status_code == 409
    finally:
        store.close()


def test_evaluation_artifact_alone_cannot_create_evidence():
    store = make_store()
    try:
        with store.transaction() as conn:
            WorkflowStore(store).put(conn, "local", "assessment_evaluation", {"id": "evaluation-only", "role": "evaluator", "status": "evaluated", "score": 1})
        with store.engine.connect() as conn:
            assert conn.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM evidence WHERE learner_id='local'")).scalar_one() == 0
    finally:
        store.close()
