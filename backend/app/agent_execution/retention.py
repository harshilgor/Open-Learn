"""Configurable, conservative retention for terminal agent activity/results.

Retention is disabled unless an operator supplies explicit positive durations.
This module never deletes task, command, operation, connector, usage, or
uncertain-effect receipts. It removes only replayable activity/checkpoints and
queues old result objects for the existing retryable object cleanup worker.
"""
from dataclasses import dataclass
import json
import os

from sqlalchemy import text


def _seconds(name):
    raw = os.getenv(name, '0')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise RuntimeError(f'{name} must be a non-negative number of seconds.') from None
    if value < 0 or value > 2_147_483_647:
        raise RuntimeError(f'{name} must be a non-negative number of seconds.')
    return value


@dataclass(frozen=True)
class RetentionPolicy:
    terminal_activity_seconds: int = 0
    terminal_checkpoint_seconds: int = 0
    terminal_artifact_seconds: int = 0

    @classmethod
    def configured(cls):
        return cls(
            terminal_activity_seconds=_seconds('OPENLEARN_AGENT_TERMINAL_ACTIVITY_RETENTION_SECONDS'),
            terminal_checkpoint_seconds=_seconds('OPENLEARN_AGENT_TERMINAL_CHECKPOINT_RETENTION_SECONDS'),
            terminal_artifact_seconds=_seconds('OPENLEARN_AGENT_TERMINAL_ARTIFACT_RETENTION_SECONDS'),
        )


class AgentRetention:
    def __init__(self, store, policy=None):
        self.store = store
        self.policy = policy or RetentionPolicy.configured()

    @staticmethod
    def _eligible(conn, owner, task_id):
        task = conn.execute(text('''SELECT status,updated_at FROM assistant_runs
            WHERE id=:task AND owner_id=:owner AND runtime_owner='agent_v2' '''),
            {'task': task_id, 'owner': owner}).first()
        if not task or task[0] not in {'completed', 'completed_partial', 'failed', 'cancelled'}:
            return False, None
        # A terminal projection is not sufficient evidence that retry or an
        # external effect is settled. Keep history while human input or a
        # prepared/unknown operation can still be reconciled.
        open_input = conn.execute(text("SELECT 1 FROM agent_input_requests WHERE owner_id=:owner AND run_id=:task AND status='open' LIMIT 1"),
                                  {'owner': owner, 'task': task_id}).first()
        pending_operation = conn.execute(text("SELECT 1 FROM agent_operations WHERE owner_id=:owner AND run_id=:task AND status NOT IN ('succeeded','failed') LIMIT 1"),
                                        {'owner': owner, 'task': task_id}).first()
        pending_action = conn.execute(text('''SELECT 1 FROM agent_action_drafts d
            JOIN agent_action_operations o ON o.draft_id=d.id AND o.owner_id=d.owner_id
            WHERE d.owner_id=:owner AND d.run_id=:task
              AND o.status IN ('queued','dispatching','outcome_unknown') LIMIT 1'''),
                                      {'owner': owner, 'task': task_id}).first()
        pending_child = conn.execute(text("SELECT 1 FROM agent_delegated_children WHERE owner_id=:owner AND parent_id=:task AND status='running' LIMIT 1"),
                                     {'owner': owner, 'task': task_id}).first()
        pending_learning = conn.execute(text("SELECT 1 FROM agent_learning_continuations WHERE owner_id=:owner AND run_id=:task AND status<>'completed' LIMIT 1"),
                                        {'owner': owner, 'task': task_id}).first()
        if open_input or pending_operation or pending_action or pending_child or pending_learning:
            return False, float(task[1])
        return True, float(task[1])

    def prune(self, *, now=None, limit=500):
        """Prune eligible data in bounded batches; return counts, never content."""
        import time
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError('Retention batch limit must be between 1 and 5000.')
        now = time.time() if now is None else float(now)
        policy = self.policy
        result = {'activityItems': 0, 'checkpoints': 0, 'artifactsQueued': 0}
        with self.store.transaction() as conn:
            if policy.terminal_activity_seconds:
                sessions = conn.execute(text('''SELECT owner_id,session_id,sequence,pruned_through
                    FROM agent_activity_cursors ORDER BY owner_id,session_id''')).mappings().all()
                for cursor in sessions:
                    floor = int(cursor['pruned_through'] or 0)
                    rows = conn.execute(text('''SELECT sequence,id,payload FROM agent_activity
                        WHERE owner_id=:owner AND session_id=:session AND sequence>:floor
                        ORDER BY sequence LIMIT :limit'''), {'owner': cursor['owner_id'],
                        'session': cursor['session_id'], 'floor': floor, 'limit': limit}).mappings().all()
                    advanced = floor
                    for row in rows:
                        try:
                            task_id = json.loads(row['payload']).get('taskId')
                        except (TypeError, ValueError):
                            task_id = None
                        if not task_id:
                            break
                        eligible, updated_at = self._eligible(conn, cursor['owner_id'], task_id)
                        if not eligible or updated_at is None or updated_at > now-policy.terminal_activity_seconds:
                            break
                        conn.execute(text('DELETE FROM agent_activity WHERE id=:id'), {'id': row['id']})
                        advanced = int(row['sequence'])
                        result['activityItems'] += 1
                    if advanced > floor:
                        conn.execute(text('''UPDATE agent_activity_cursors SET pruned_through=:floor
                            WHERE owner_id=:owner AND session_id=:session AND pruned_through<:floor'''),
                            {'floor': advanced, 'owner': cursor['owner_id'], 'session': cursor['session_id']})

            if policy.terminal_checkpoint_seconds:
                rows = conn.execute(text('''SELECT c.id,c.owner_id,c.run_id,c.version FROM agent_checkpoints c
                    JOIN assistant_runs r ON r.id=c.run_id AND r.owner_id=c.owner_id
                    WHERE r.runtime_owner='agent_v2' AND r.status IN ('completed','completed_partial','failed','cancelled')
                      AND r.updated_at<=:cutoff
                      AND EXISTS (SELECT 1 FROM agent_checkpoints latest
                        WHERE latest.run_id=c.run_id AND latest.owner_id=c.owner_id AND latest.version>c.version)
                    ORDER BY c.created_at LIMIT :limit'''), {'cutoff': now-policy.terminal_checkpoint_seconds,
                    'limit': limit}).mappings().all()
                for row in rows:
                    eligible, _ = self._eligible(conn, row['owner_id'], row['run_id'])
                    if not eligible:
                        continue
                    conn.execute(text('DELETE FROM agent_checkpoints WHERE id=:id'), {'id': row['id']})
                    result['checkpoints'] += 1

            if policy.terminal_artifact_seconds:
                rows = conn.execute(text('''SELECT a.id,a.owner_id,a.run_id FROM agent_artifacts a
                    JOIN assistant_runs r ON r.id=a.run_id AND r.owner_id=a.owner_id
                    WHERE a.status='published' AND r.runtime_owner='agent_v2'
                      AND r.status IN ('completed','completed_partial','failed','cancelled')
                      AND a.created_at<=:cutoff ORDER BY a.created_at LIMIT :limit'''),
                    {'cutoff': now-policy.terminal_artifact_seconds, 'limit': limit}).mappings().all()
                for row in rows:
                    eligible, _ = self._eligible(conn, row['owner_id'], row['run_id'])
                    if not eligible:
                        continue
                    changed = conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE id=:id AND status='published'"),
                                           {'id': row['id']})
                    result['artifactsQueued'] += changed.rowcount
        return result
