from pathlib import Path
from uuid import uuid4
from backend.app.storage import Store
from backend.app.workflow_store import WorkflowStore
from backend.app.evidence_ledger import EvidenceLedger, event_id
from backend.app.assessment_adjudication import ChallengeService, Adjudication
from backend.app.quiz_service import QuizService


def test_invalidation_repairs_all_sessions_preserves_original_attempts():
    store = Store(Path.cwd() / "backend" / "data" / ("challenge-" + uuid4().hex + ".db"))
    records, ledger = WorkflowStore(store), EvidenceLedger(store)
    try:
        with store.transaction() as conn:
            for number in range(2):
                aid, pid = f"attempt-{number}", f"presentation-{number}"
                records.put(conn, "local", "presentation", {"id": pid, "itemId": "bad-item", "attemptId": aid})
                records.put(conn, "local", "attempt", {"id": aid, "presentationId": pid, "score": 1, "status": "evaluated"})
                ledger.emit(conn, "local", "attempt:" + aid, "QUIZ_RESPONSE", attempt_id=aid)
            records.put(conn, "local", "challenge", {"id": "challenge-1", "presentationId": "presentation-0", "status": "excluded_pending_review"})
        challenge = records.read("local", "challenge-1", "challenge")
        presentation = records.read("local", "presentation-0", "presentation")
        with store.transaction() as conn:
            ChallengeService(store, None).commit(conn, "local", (challenge, presentation, None,
                Adjudication(outcome="invalidate", explanation="The source contradicts the question.", source_ids=["s"]), None))
        with store.engine.connect() as conn:
            assert all(e["category"] == "excluded" for e in ledger.history(conn, "local")["entries"])
        assert records.read("local", "attempt-1", "attempt")["score"] == 1
        effective = QuizService(store, None)._effective_attempt("local", records.read("local", "attempt-1", "attempt"))
        assert effective["score"] is None
        assert effective["status"] == "invalidated"
    finally:
        store.close()


def test_latest_received_correction_wins_when_regrade_keeps_original_occurrence():
    store = Store(Path.cwd() / "backend" / "data" / ("correction-order-" + uuid4().hex + ".db"))
    try:
        ledger = EvidenceLedger(store)
        with store.transaction() as conn:
            original = event_id("local", "original")
            ledger.emit(conn, "local", "original", "QUIZ_RESPONSE", occurred_at="2026-09-01T00:00:00+00:00", attempt_id="a")
            ledger.emit(conn, "local", "withdraw", "EVIDENCE_RETRACTED", target_event_id=original,
                occurred_at="2026-10-01T00:00:00+00:00", admission="excluded", exclusion_reasons=("challenge",))
            ledger.emit(conn, "local", "regrade", "EVALUATION_CORRECTED", target_event_id=original,
                occurred_at="2026-09-01T00:00:00+00:00", admission="excluded", exclusion_reasons=("uncalibrated",))
            history = ledger.history(conn, "local")
            assert history["entries"][0]["correctionId"] == event_id("local", "regrade")
    finally:
        store.close()
