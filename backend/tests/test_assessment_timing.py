import json
import pytest

from backend.app import assessment_timing as timing


def test_scope_correlates_and_restores_without_content(monkeypatch):
    records = []
    monkeypatch.setattr(timing.logger, "info", lambda message: records.append(json.loads(message)))

    @timing.execution_scope
    def run(secret):
        with timing.span("author", attempt=2):
            pass
        timing.emit("queue_age", 17, command="next")
        return secret

    assert run("PRIVATE ANSWER") == "PRIVATE ANSWER"
    assert records[0]["executionId"] == records[1]["executionId"]
    assert records[0]["executionId"]
    assert records[0]["attempt"] == 2
    assert "PRIVATE" not in json.dumps(records)
    assert timing._execution.get() is None


def test_failed_span_preserves_exception_and_resets_scope(monkeypatch):
    records = []
    monkeypatch.setattr(timing.logger, "info", lambda message: records.append(json.loads(message)))

    @timing.execution_scope
    @timing.timed("prepare")
    def fail():
        raise RuntimeError("PRIVATE PROVIDER PAYLOAD")

    with pytest.raises(RuntimeError):
        fail()
    assert records[0]["status"] == "failed"
    assert "PRIVATE" not in json.dumps(records)
    assert timing._execution.get() is None


def test_unknown_stage_rejected():
    with pytest.raises(ValueError):
        timing.emit("learner_content", 1)


def test_summary_deduplicates_event_ids_but_not_equal_durations():
    from backend.scripts.assessment_timing_report import summarize
    event = {"event": "assessment_timing", "eventId": "one", "stage": "author",
        "status": "completed", "durationMs": 10}
    result = summarize([event, event, {**event, "eventId": "two"},
        {**event, "eventId": "bad", "durationMs": float("nan")}])
    assert result["stages"][0]["samples"] == 2
    assert result["stages"][0]["p50Ms"] == 10
