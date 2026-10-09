import json
import pytest
from sqlalchemy import text

from backend.app.agent_execution.retention import AgentRetention, RetentionPolicy
from backend.tests.test_agent_execution import env, start


def test_retention_is_disabled_without_explicit_policy(monkeypatch):
    for name in ('OPENLEARN_AGENT_TERMINAL_ACTIVITY_RETENTION_SECONDS',
                 'OPENLEARN_AGENT_TERMINAL_CHECKPOINT_RETENTION_SECONDS',
                 'OPENLEARN_AGENT_TERMINAL_ARTIFACT_RETENTION_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    assert RetentionPolicy.configured() == RetentionPolicy()
    monkeypatch.setenv('OPENLEARN_AGENT_TERMINAL_ACTIVITY_RETENTION_SECONDS', '-1')
    with pytest.raises(RuntimeError, match='non-negative'):
        RetentionPolicy.configured()


def test_zero_default_keeps_terminal_activity_checkpoints_and_artifact(env,monkeypatch):
    for name in ('OPENLEARN_AGENT_TERMINAL_ACTIVITY_RETENTION_SECONDS',
                 'OPENLEARN_AGENT_TERMINAL_CHECKPOINT_RETENTION_SECONDS',
                 'OPENLEARN_AGENT_TERMINAL_ARTIFACT_RETENTION_SECONDS'):
        monkeypatch.delenv(name, raising=False)
    store, _, _ = env
    run = _old_terminal_run(env)
    assert AgentRetention(store).prune(now=1000) == {'activityItems':0,'checkpoints':0,'artifactsQueued':0}
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_activity WHERE owner_id=\'alice\'')).scalar_one() > 0
        assert conn.execute(text('SELECT count(*) FROM agent_checkpoints WHERE run_id=:id'),{'id':run['id']}).scalar_one() > 0
        assert conn.execute(text('SELECT status FROM agent_artifacts WHERE id=\'artifact-old\'')).scalar_one() == 'published'


def _old_terminal_run(env):
    store, coordinator, repo = env
    _, run = start(env, client='retention')
    with repo.transaction() as conn:
        run = repo.run(conn, 'alice', run['id'])
        run = repo.update(conn, run, status='completed', summary='Saved result')
        run = repo.checkpoint(conn, run)
        run = repo.checkpoint(conn, run)
        repo.activity(conn, run, 'retention-final', 'task.completed', text='Saved result')
        conn.execute(text('UPDATE assistant_runs SET updated_at=500 WHERE id=:id'), {'id':run['id']})
        conn.execute(text('UPDATE agent_checkpoints SET created_at=500 WHERE run_id=:id'), {'id':run['id']})
        conn.execute(text('''INSERT INTO agent_operations(id,owner_id,run_id,input_revision,step_key,status,payload,created_at)
            VALUES('receipt-succeeded','alice',:run,1,'lab_analysis','succeeded','{"effect":"result-published"}',500)'''), {'run':run['id']})
        conn.execute(text('''INSERT INTO agent_artifacts(id,owner_id,run_id,operation_id,name,object_key,sha256,status,payload,created_at)
            VALUES('artifact-old','alice',:run,'operation-old','result.txt','object-old',:sha,'published',:payload,500)'''),
            {'run':run['id'],'sha':'a'*64,'payload':json.dumps({'id':'artifact-old','name':'result.txt'})})
    return run


def test_terminal_retention_prunes_replay_and_old_checkpoints_but_keeps_receipts(env):
    store, coordinator, repo = env
    run = _old_terminal_run(env)
    with store.engine.connect() as conn:
        activity_count = conn.execute(text('SELECT count(*) FROM agent_activity WHERE owner_id=\'alice\' AND session_id=\'session\'')).scalar_one()
        checkpoint_count = conn.execute(text('SELECT count(*) FROM agent_checkpoints WHERE run_id=:id'),{'id':run['id']}).scalar_one()
    result = AgentRetention(store, RetentionPolicy(100, 100, 100)).prune(now=1000)
    assert result == {'activityItems':activity_count,'checkpoints':checkpoint_count-1,'artifactsQueued':1}
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_activity WHERE owner_id=\'alice\'')).scalar_one() == 0
        assert conn.execute(text('SELECT count(*) FROM agent_checkpoints WHERE run_id=:id'),{'id':run['id']}).scalar_one() == 1
        assert conn.execute(text('SELECT status FROM agent_artifacts WHERE id=\'artifact-old\'')).scalar_one() == 'cleanup_pending'
        assert conn.execute(text("SELECT count(*) FROM agent_operations WHERE run_id=:id AND id='receipt-succeeded'"),{'id':run['id']}).scalar_one() == 1
        assert conn.execute(text('SELECT pruned_through FROM agent_activity_cursors WHERE owner_id=\'alice\' AND session_id=\'session\'')).scalar_one() == activity_count
    stale = coordinator.snapshot('alice','session',after=0)
    assert stale['resnapshotRequired'] is True and stale['prunedThrough']==activity_count
    fresh = coordinator.snapshot('alice','session')
    assert fresh['resnapshotRequired'] is False and fresh['items']==[]


def test_retention_preserves_unknown_effect_and_pending_operation_receipts(env):
    store, _, repo = env
    run = _old_terminal_run(env)
    with store.engine.connect() as conn:
        activity_count = conn.execute(text('SELECT count(*) FROM agent_activity WHERE owner_id=\'alice\' AND session_id=\'session\'')).scalar_one()
    with store.transaction() as conn:
        conn.execute(text('''INSERT INTO agent_action_drafts(id,owner_id,created_at,run_id,input_revision,connection_id,
            connection_revision,revision,status,action_hash,expires_at,payload)
            VALUES('draft-unknown','alice',500,:run,1,'connection',1,1,'approved','hash',900,'{}')'''), {'run':run['id']})
        conn.execute(text('''INSERT INTO agent_action_operations(id,owner_id,created_at,draft_id,status,payload,updated_at)
            VALUES('operation-unknown','alice',500,'draft-unknown','outcome_unknown','{}',500)'''))
        conn.execute(text('''INSERT INTO agent_operations(id,owner_id,run_id,input_revision,step_key,status,payload,created_at)
            VALUES('operation-pending','alice',:run,1,'research','prepared','{}',500)'''), {'run':run['id']})
    result = AgentRetention(store, RetentionPolicy(100, 100, 100)).prune(now=1000)
    assert result == {'activityItems':0,'checkpoints':0,'artifactsQueued':0}
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM agent_activity WHERE owner_id=\'alice\'')).scalar_one() == activity_count
        assert conn.execute(text('SELECT status FROM agent_action_operations WHERE id=\'operation-unknown\'')).scalar_one() == 'outcome_unknown'
        assert conn.execute(text('SELECT status FROM agent_artifacts WHERE id=\'artifact-old\'')).scalar_one() == 'published'
