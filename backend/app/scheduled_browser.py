"""Scheduled browser boundaries; existing stores remain the execution owners."""
import hashlib
import json
import time
from sqlalchemy import text
from .identity import fail
from .workflow_store import WorkflowStore, encoded

CHECKPOINT_MAX_ASSIGNMENTS = 2000
CHECKPOINT_RETENTION_SECONDS = 90 * 86400


def retained_assignments(previous, current, now):
    """Bound each checkpoint, retaining the most recently observed identities first."""
    observations = previous.get('observedAt', {})
    retained = {key: value for key, value in previous.get('assignments', {}).items()
                if now - observations.get(key, previous.get('checkedAt', 0)) < CHECKPOINT_RETENTION_SECONDS}
    retained.update(current)
    seen = {key: now if key in current else observations.get(key, previous.get('checkedAt', 0))
            for key in retained}
    newest = sorted(retained, key=lambda key: seen[key], reverse=True)[:CHECKPOINT_MAX_ASSIGNMENTS]
    return {key: retained[key] for key in newest}, {key: seen[key] for key in newest}


def browser_actions(actions):
    return [a for a in actions if (a.get('skillId') if isinstance(a, dict) else a.skillId) == 'assistant.website_task']


def validate_actions(conn, owner, actions, session_id):
    for action in browser_actions(actions):
        args = action.args if hasattr(action, 'args') else action['args']
        connection = conn.execute(text('SELECT status,payload FROM site_connections WHERE id=:id AND owner_id=:owner'),
                                  {'id':args.get('connectionId'), 'owner':owner}).mappings().first()
        if not connection or connection['status'] == 'revoked':
            fail('connection_unavailable', 'Choose a connected cloud website for this routine.', 422)
        if json.loads(connection['payload']).get('executor') != 'cloud':
            fail('cloud_connection_required', 'Scheduled website tasks require a cloud connection.', 422)
        if not session_id or args.get('sessionId') != session_id:
            fail('session_required', 'Bind the scheduled website task to this conversation.', 422)


def cancel_tasks(conn, store, owner, fire_ids):
    from .browser_assistant.store import AssistantStore
    repo = AssistantStore(store)
    for fire_id in fire_ids:
        ids = conn.execute(text("SELECT job_id FROM reminder_action_runs WHERE owner_id=:owner AND fire_id=:fire AND skill_id='assistant.website_task' AND status='waiting'"),
                           {'owner':owner,'fire':fire_id}).scalars().all()
        for identifier in ids:
            task = repo.run(conn,owner,identifier)
            if task['status'] not in {'completed','completed_partial','failed','cancelled'}:
                task = repo.update_run(conn,task,status='cancelled',pendingCommand=None)
                repo.event(conn,task,'task.cancelled','Scheduled website check stopped.')
                conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,cancel_requested=true,lease=NULL,expires=NULL WHERE owner_id=:owner AND target_id=:task AND status IN ('queued','retry_wait','running')"),
                             {'owner':owner,'task':identifier})


def project_result(conn, store, ledger, task, status):
    """Serialize checkpoint updates before the ledger CAS in the same transaction."""
    conn.execute(text('UPDATE reminders SET payload=payload WHERE id=:id AND owner_id=:owner'),
                 {'id':ledger['fire_id'], 'owner':ledger['owner_id']})
    fire = conn.execute(text('SELECT policy_id,payload FROM reminders WHERE id=:id AND owner_id=:owner'),
                        {'id':ledger['fire_id'], 'owner':ledger['owner_id']}).mappings().one()
    # Cancellation may have won while a completion reconciler was waiting.
    if conn.execute(text('SELECT status FROM reminders WHERE id=:id'), {'id':ledger['fire_id']}).scalar_one() != 'delivering':
        fail('routine_cancelled', 'This scheduled activity was cancelled.', 409)
    scope = encoded([ledger['owner_id'], fire['policy_id'] or ledger['fire_id'], task.get('connectionId'), task.get('courseId')])
    checkpoint_id = 'portal_checkpoint_' + hashlib.sha256(scope.encode()).hexdigest()[:32]
    prior_row = conn.execute(text('SELECT payload,revision FROM practice_records WHERE id=:id AND owner_id=:owner AND kind=:kind'),
                             {'id':checkpoint_id, 'owner':ledger['owner_id'], 'kind':'scheduled_portal_checkpoint'}).mappings().first()
    previous = json.loads(prior_row['payload']) if prior_row else {}
    fingerprints = {}
    for fact in task.get('facts', []):
        if fact.get('kind') != 'assignment':
            continue
        source = fact.get('source') or {}
        source_url=source.get('url') if isinstance(source,dict) else None
        identity = fact.get('entityId') or (encoded([source_url,fact.get('title')]) if source_url and fact.get('title') else None)
        if not identity:
            continue  # Unidentified facts cannot support a reliable novelty claim.
        digest = hashlib.sha256(encoded({k:fact.get(k) for k in ('title','date','conflict')}).encode()).hexdigest()
        fingerprints[identity] = digest
    now = time.time()
    baseline, _ = retained_assignments(previous, {}, now)
    additions = [key for key in fingerprints if key not in baseline]
    changes = [key for key in fingerprints if key in baseline and fingerprints[key] != baseline[key]]
    summary = task.get('summary') or 'The website check finished. Open the task to review its results.'
    if status == 'completed_partial':
        summary = 'Partial website check: some requested areas were not verified. ' + summary
    elif fingerprints:
        summary = f'{len(additions)} newly observed assignments; {len(changes)} changed assignments. ' + summary
    if status == 'completed' and previous.get('checkedAt') and fingerprints and not additions and not changes:
        summary='No newly observed or changed assignments in the covered results. '+summary
    if status == 'completed':
        retained, observed = retained_assignments(previous, fingerprints, now)
        WorkflowStore(store).put(conn, ledger['owner_id'], 'scheduled_portal_checkpoint',
            {'id':checkpoint_id, 'version':1, 'assignments':retained, 'observedAt':observed, 'checkedAt':now, 'taskId':ledger['job_id']}, expected=prior_row['revision'] if prior_row else None)
    return {'summary':summary[:2000], 'body':summary[:2000], 'coverage':task.get('coverage', []),
            'browserTaskId':ledger['job_id'], 'deepLink':'/s/'+task['sessionId'] if task.get('sessionId') else '/chat?view=reminders'}


def reconcile_attention(store):
    """Attention has a separate identity so it cannot consume final inbox delivery."""
    with store.transaction() as conn:
        rows = conn.execute(text("SELECT a.*,r.payload AS task_payload,r.status AS task_status FROM reminder_action_runs a JOIN reminders f ON f.id=a.fire_id AND f.owner_id=a.owner_id JOIN assistant_runs r ON r.id=a.job_id AND r.owner_id=a.owner_id WHERE a.status='waiting' AND f.status='delivering' AND r.status IN ('waiting_for_login','waiting_for_user','waiting_for_device','paused') AND NOT EXISTS (SELECT 1 FROM practice_records p WHERE p.owner_id=a.owner_id AND p.kind='scheduled_attention_receipt' AND p.parent_id=a.fire_id) ORDER BY r.updated_at,a.fire_id LIMIT 100")).mappings().all()
        for row in rows:
            conn.execute(text('UPDATE reminders SET payload=payload WHERE id=:id AND owner_id=:owner'),{'id':row['fire_id'],'owner':row['owner_id']})
            if conn.execute(text('SELECT status FROM reminders WHERE id=:id'),{'id':row['fire_id']}).scalar_one()!='delivering':
                continue
            if conn.execute(text("SELECT 1 FROM practice_records WHERE owner_id=:owner AND kind='scheduled_attention_receipt' AND parent_id=:fire"),{'owner':row['owner_id'],'fire':row['fire_id']}).first():
                continue
            task = json.loads(row['task_payload'])
            identifier = 'scheduled_attention_' + hashlib.sha256((row['fire_id']+':'+str(row['step_id'])).encode()).hexdigest()[:32]
            session = task.get('sessionId')
            payload = {'id':identifier, 'title':'Scheduled website check needs your attention',
                       'body':'Open this task to sign in or answer its question. It will continue after you respond.',
                       'url':'/s/'+session if session else '/chat?view=reminders', 'taskId':row['job_id']}
            conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES(:id,:owner,:ref,'inbox','available',:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING"),
                         {'id':identifier, 'owner':row['owner_id'], 'ref':identifier, 'payload':encoded(payload), 'now':time.time()})
            WorkflowStore(store).put(conn,row['owner_id'],'scheduled_attention_receipt',{'id':identifier+'_receipt','taskId':row['job_id']},row['fire_id'])
            if session:
                exists = conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner'), {'id':identifier,'owner':row['owner_id']}).first()
                if not exists:
                    WorkflowStore(store).put(conn,row['owner_id'],'reminder_message',{**payload,'sessionId':session,'createdAt':time.time()},session)
