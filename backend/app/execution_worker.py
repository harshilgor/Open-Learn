"""Bounded polling of existing workflow executors, usable locally or externally.

python -m backend.app.execution_worker --queue interactive
python -m backend.app.execution_worker --queue batch

No separate application or provider implementation lives in this worker.
"""
import argparse
import logging
import threading
from .execution_outbox import ExecutionOutbox
from .workflow_store import WorkflowStore

INTERACTIVE_KINDS = frozenset({"create", "journey", "note_synthesis", "note_draft", "next", "answer", "hint", "retry", "resume", "pause", "challenge", "flag"})
REVIEW_KINDS = frozenset({"review_create", "review_answer", "concept_sync", "review_backfill"})
LECTURE_KINDS = frozenset({"lecture_transcribe", "lecture_segment", "lecture_section", "lecture_verify", "lecture_generate", "lecture_audio_retention"})


class ExecutionWorker:
    def __init__(self, store, provider_getter, queue="interactive"):
        if queue not in {"interactive", "batch"}:
            raise ValueError("Invalid queue")
        self.store, self.provider_getter, self.queue = store, provider_getter, queue
        self.records = WorkflowStore(store)

    def tick(self, limit=20):
        from .usage.ledger import Ledger
        from .worker import monitor_usage_if_due
        monitor_usage_if_due(self.store)
        Ledger(self.store).reconcile()
        if self.queue == 'interactive':
            from .voice.maintenance import tick as voice_maintenance
            voice_maintenance(self.store)
        def enqueue(conn, owner, message_id, payload):
            self.records.enqueue(owner, payload["target"], payload["kind"], payload["input"], message_id,
                                 connection=conn, input_revision=payload.get("inputRevision"), queue=payload.get("queue"))
        ExecutionOutbox(self.store).drain({"execution.enqueue": enqueue}, limit)
        if self.queue == "batch":
            from .lecture_pipeline import LectureWorker
            # Reserve a bounded transcription batch per poll so workers on
            # other class/session queues can make progress between batches.
            return LectureWorker(self.store, self.provider_getter).drain(min(limit, 4))
        from .learning_routes import run_job
        from .review_routes import run_review_job
        ids = self.records.ready_ids(self.queue, INTERACTIVE_KINDS | REVIEW_KINDS | {'voice_turn', 'voice_action', 'voice_teach'}, limit)
        for job_id in ids:
            from sqlalchemy import text
            with self.store.engine.connect() as conn:
                kind = conn.execute(text("SELECT kind FROM learning_jobs WHERE id=:id"), {"id": job_id}).scalar_one()
            executor = run_review_job if kind in REVIEW_KINDS else run_job
            executor(self.store, self.provider_getter(), job_id)
        return len(ids)

    def run(self, stopped: threading.Event, interval=1):
        while not stopped.is_set():
            try:
                self.tick()
            except Exception as exc:
                # Do not include payloads, URLs, tokens, or raw provider errors.
                logging.getLogger(__name__).warning("Worker tick failed (%s)", type(exc).__name__)
            stopped.wait(interval)


def main():
    import signal
    from .database import database_url
    from .storage import Store
    from .model_provider import configured_lesson_provider
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", choices=["interactive", "batch"], default="interactive")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    store = Store(database_url())
    try:
        worker = ExecutionWorker(store, configured_lesson_provider, args.queue)
        if args.queue == "batch":
            from .lecture_pipeline import LectureWorker
            LectureWorker(store, configured_lesson_provider).reconcile()
        if args.once:
            worker.tick()
        else:
            stopped = threading.Event()
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            worker.run(stopped)
    finally:
        store.close()


if __name__ == "__main__":
    main()
