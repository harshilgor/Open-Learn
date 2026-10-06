"""Same-application worker: python -m backend.app.worker [--once]."""
import argparse
import logging
import signal
import threading
import time

from sqlalchemy import text
from .database import database_url
from .storage import Store
from .execution import Outbox
from .workflow_store import WorkflowStore

log = logging.getLogger(__name__)
LEARNING_KINDS = {"journey", "note_synthesis", "note_draft", "next", "answer", "create", "hint", "retry", "resume", "pause", "challenge", "flag"}
USAGE_RECONCILE_INTERVAL_SECONDS = 15
_last_usage_reconcile = 0.0
_last_usage_monitor = 0.0


def monitor_usage_if_due(store, now=None):
    """Poll usage health at the same bounded cadence as reservation cleanup."""
    global _last_usage_monitor
    now = time.monotonic() if now is None else now
    if now - _last_usage_monitor < USAGE_RECONCILE_INTERVAL_SECONDS:
        return None
    _last_usage_monitor = now
    from .usage.ledger import Ledger
    try:
        return Ledger(store).monitor()
    except Exception as exc:
        log.warning("Usage health monitor iteration failed (%s)", type(exc).__name__)
        return None


def reconcile_usage_if_due(store, now=None):
    """Reconcile expired reservations from the hosted learning worker loop."""
    global _last_usage_reconcile
    now = time.monotonic() if now is None else now
    if now - _last_usage_reconcile < USAGE_RECONCILE_INTERVAL_SECONDS:
        return 0
    # Throttle even on DB failure so one outage does not flood worker logs.
    _last_usage_reconcile = now
    from .usage.ledger import Ledger
    from .usage.policy import Policy
    monitor_usage_if_due(store, now=now)
    return Ledger(store, Policy.load()).reconcile()


def dispatch_learning_completion(conn, event, payload):
    # Completion delivery is durable even with no expensive consumers yet.
    # Consumers register their own topics rather than mutating projections here.
    # The original command's result is already authoritative and queryable.
    log.info("learning.command.delivered event=%s kind=%s", event["id"], payload["kind"])


def dispatch_job(store):
    def deliver(conn, event, payload):
        WorkflowStore(store).enqueue(event["owner_id"], event["target_id"], payload["kind"],
                                    payload["input"], payload["key"], connection=conn)
    return deliver


def run_recording(store, provider, job_id):
    from .execution import job_scope, LeaseHeartbeat
    from .class_recording_service import ClassRecordingService
    jobs = WorkflowStore(store)
    job = jobs.claim(job_id)
    if job is None:
        return
    heartbeat = LeaseHeartbeat(store, job)
    try:
        with job_scope(job):
            with store.transaction() as conn:
                conn.execute(text("UPDATE class_recordings SET status='queued' WHERE id=:id AND learner_id=:owner AND status='processing'"), {"id": job["target_id"], "owner": job["owner_id"]})
            service = ClassRecordingService(store, provider)
            service.process(job["target_id"], job["owner_id"])
            with store.transaction() as conn:
                status = conn.execute(text("SELECT status FROM class_recordings WHERE id=:id AND learner_id=:owner"), {"id": job["target_id"], "owner": job["owner_id"]}).scalar_one_or_none()
                jobs.finish(conn, job, {"recordingId": job["target_id"]}, "completed" if status == "completed" else "failed")
    except Exception as exc:
        from .execution import failure_policy
        code, retryable = failure_policy(exc)
        jobs.fail(job, code, retryable=retryable)
    finally:
        heartbeat.close()


def reconcile_recordings(store):
    with store.transaction() as conn:
        rows = conn.execute(text("SELECT id,learner_id FROM class_recordings WHERE status IN ('queued','processing')")).all()
        for record_id, owner in rows:
            WorkflowStore(store).enqueue(owner, record_id, "class_recording", {}, "class-recording:" + record_id, connection=conn)


def run_hypothesis(store, provider, job_id):
    from .execution import job_scope, LeaseHeartbeat, failure_policy
    from .hypothesis_service import HypothesisService
    jobs = WorkflowStore(store)
    job = jobs.claim(job_id)
    if not job:
        return
    heartbeat = LeaseHeartbeat(store, job)
    try:
        with job_scope(job):
            result = HypothesisService(store, provider).analyze(job["owner_id"], job["payload"]["event_id"])
            with store.transaction() as conn:
                jobs.finish(conn, job, result)
    except Exception as exc:
        code, retry = failure_policy(exc)
        jobs.fail(job, code, retryable=retry)
    finally:
        heartbeat.close()


def tick(store, provider_getter):
    from .learning_routes import run_job
    from .lecture_pipeline import LectureWorker
    from .material_service import MaterialService
    from .identity_data import cleanup_objects
    try:
        reconciled_usage = reconcile_usage_if_due(store)
    except Exception as exc:
        log.warning("Usage reconciliation iteration failed (%s)", type(exc).__name__)
        reconciled_usage = 0
    cleanup_objects(store)
    reconcile_recordings(store)
    did_work = bool(reconciled_usage) or Outbox(store).deliver_one({"learning.command.completed": dispatch_learning_completion, "execution.job.requested": dispatch_job(store)})
    with store.engine.connect() as conn:
        pending = conn.execute(text("""SELECT id,kind FROM learning_jobs WHERE cancellation_requested=false
            AND next_retry_at<=:now AND (status='queued' OR (status='running' AND expires<:now)) ORDER BY priority DESC,created_at,id LIMIT 100"""), {"now": time.time()}).all()
    for job_id, kind in pending:
        if kind in LEARNING_KINDS:
            run_job(store, provider_getter(), job_id)
            did_work = True
            break
        if kind == "class_recording":
            run_recording(store, provider_getter(), job_id)
            did_work = True
            break
        if kind == "hypothesis_analyze":
            run_hypothesis(store, provider_getter(), job_id)
            did_work = True
            break
    if LectureWorker(store, provider_getter).drain(limit=4):
        did_work = True
    if MaterialService(store).process_one():
        did_work = True
    return did_work


def run(store, provider_getter, stop, once=False):
    from .lecture_pipeline import LectureWorker
    LectureWorker(store, provider_getter).reconcile()
    while not stop.is_set():
        try:
            busy = tick(store, provider_getter)
        except Exception as exc:
            log.warning("Worker iteration failed (%s)", type(exc).__name__)
            busy = False
        if once:
            return
        stop.wait(.1 if busy else 2)


def main():
    from .model_provider import configured_lesson_provider
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    store = Store(database_url())
    try:
        run(store, configured_lesson_provider, stop, args.once)
    finally:
        store.close()


if __name__ == "__main__":
    main()
