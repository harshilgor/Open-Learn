"""Execute voice turns with the shared queue lease and transaction fencing."""
from ..workflow_store import WorkflowStore
from ..execution import LeaseHeartbeat, active_job
from ..identity import Principal, principal_context
from .coordinator import Coordinator
from .store import VoiceStore


from ..usage.context import usage_job

@usage_job
def run_voice_job(store, provider, job_id):
    records = WorkflowStore(store)
    job = records.claim(job_id)
    if not job:
        return
    heartbeat = LeaseHeartbeat(store, job)
    lease_token = active_job.set(job)
    identity_token = principal_context.set(Principal(job['owner_id'], 'voice_worker'))
    try:
        coordinator = Coordinator(store, provider)
        if job['kind'] == 'voice_action':
            session = coordinator.records.session(job['owner_id'], job['target_id'], active=True)
            action = next(a for a in coordinator.records.records(job['owner_id'], job['target_id'], 'actions') if a['id'] == job['payload']['action_id'])
            coordinator.execute(job['owner_id'], session, action)
            result = {'status': 'completed'}
        else:
            result = coordinator.run(job['owner_id'], job['target_id'], job['payload']['turn_id'])
        with store.transaction() as conn:
            records.finish(conn, job, result)
    except Exception:
        # Do not retry uncertain side effects automatically.
        try:
            with store.transaction() as conn:
                VoiceStore(store).emit(conn, job['owner_id'], job['target_id'], 'turn.failed', {'turnId': job['payload'].get('turn_id'), 'message': 'Buddy could not finish this turn. Check the action receipts before retrying.'})
                if job['payload'].get('turn_id'):
                    conn.execute(__import__('sqlalchemy').text("UPDATE voice_turns SET status='failed' WHERE id=:id AND owner_id=:owner"), {'id': job['payload']['turn_id'], 'owner': job['owner_id']})
            records.fail(job, 'voice_turn_failed', retryable=False)
        except Exception:
            pass  # A new lease or account deletion owns the outcome.
    finally:
        principal_context.reset(identity_token)
        active_job.reset(lease_token)
        heartbeat.close()
