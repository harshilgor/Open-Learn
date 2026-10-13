import json
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.usage.admin_ops import UsageAdmin
from app.usage.ledger import Ledger, UsageError
from app.usage.policy import Policy


@pytest.fixture
def usage_admin(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'usage-admin.db')
    root = __import__('pathlib').Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'migrations'))
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, 'head')
    store = SimpleNamespace(engine=create_engine(url, connect_args={'timeout': 30}))
    clock = [100000.0]
    ledger = Ledger(store, Policy(), lambda: clock[0])
    admin = UsageAdmin(store, ledger)
    yield admin, ledger, clock
    store.engine.dispose()


def _settled_model(ledger, owner='learner-1', key='model-call'):
    row = ledger.reserve(owner, key, 'model', {'input_tokens': 1000, 'output_tokens': 0})
    ledger.dispatch(owner, row['id'])
    ledger.settle(owner, row['id'], {'input_tokens': 1000, 'output_tokens': 0})
    return row


def test_inspect_is_read_only_exact_owner_and_excludes_payloads(usage_admin):
    admin, ledger, _ = usage_admin
    with pytest.raises(ValueError, match='exact'):
        admin.inspect(' missing ')
    with pytest.raises(ValueError, match='Unknown owner'):
        admin.inspect('missing')
    with ledger.store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM usage_accounts')).scalar_one() == 0
    _settled_model(ledger)
    report = admin.inspect('learner-1')
    assert report['account']['owner_id'] == 'learner-1'
    assert report['allowance']['usedMicrocredits'] == 500_000
    assert report['reservations'][0]['state'] == 'settled'
    assert 'payload' not in report['reservations'][0]
    assert 'payload' not in report['events'][0]


def test_capability_disable_is_audited_and_blocks_only_new_matching_admissions(usage_admin):
    admin, ledger, _ = usage_admin
    disabled = admin.set_capability('search', True, actor='operator@example.test', reason='Vendor incident',
                                    idempotency_key='disable-search-0001')
    assert disabled['disabled'] is True
    with pytest.raises(UsageError) as error:
        ledger.reserve('learner-1', 'search-call', 'tool', {'requests': 1}, liability=100,
                       provider='exa', provider_rates={'usd_nano_per_request': 100})
    assert error.value.detail['code'] == 'usage_capability_disabled'
    allowed = ledger.reserve('learner-1', 'model-call', 'model', {'input_tokens': 1000, 'output_tokens': 0})
    assert allowed['component'] == 'model'
    replay = admin.set_capability('search', True, actor='operator@example.test', reason='Vendor incident',
                                  idempotency_key='disable-search-0001')
    assert replay['replayed'] is True
    enabled = admin.set_capability('search', False, actor='operator@example.test', reason='Vendor restored',
                                   idempotency_key='enable-search-0002')
    assert enabled['disabled'] is False
    row = ledger.reserve('learner-1', 'search-call', 'tool', {'requests': 1}, liability=100,
                         provider='exa', provider_rates={'usd_nano_per_request': 100})
    assert row['state'] == 'reserved'
    with ledger.store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM usage_admin_audit')).scalar_one() == 2


def test_alert_ack_is_idempotent_and_records_actor_reason(usage_admin):
    admin, ledger, clock = usage_admin
    with ledger.transaction() as conn:
        conn.execute(text('''INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload)
            VALUES('alert-1','learner-1','reservation-1','provider_liability_overrun',:now,'{}')'''), {'now': clock[0]})
    assert admin.open_alerts() == [{'id': 'alert-1', 'owner_id': 'learner-1', 'reservation_id': 'reservation-1',
                                    'kind': 'provider_liability_overrun', 'created_at': clock[0], 'payload': '{}'}]
    result = admin.acknowledge_alert('alert-1', actor='on-call', reason='Receipt verified',
                                     idempotency_key='ack-alert-0001')
    assert result['changed'] is True
    assert admin.acknowledge_alert('alert-1', actor='on-call', reason='Receipt verified',
                                   idempotency_key='ack-alert-0001')['replayed'] is True
    assert admin.open_alerts() == []
    with ledger.store.engine.connect() as conn:
        audit = conn.execute(text("SELECT actor,action,target,reason FROM usage_admin_audit WHERE idempotency_key='ack-alert-0001'")).one()
    assert audit == ('on-call', 'alert_ack', 'alert:alert-1', 'Receipt verified')


def test_operations_snapshot_is_read_only_aggregate_and_surfaces_recovery_work(usage_admin):
    admin, ledger, clock = usage_admin
    with ledger.store.engine.begin() as conn:
        conn.execute(text('''INSERT INTO learning_jobs(id,owner_id,target_id,kind,command_key,request_hash,status,
            lease,expires,payload,attempt_count,max_attempts,next_retry_at,queue,priority,created_at)
            VALUES('queued-1','private-owner','target','agent_step','key-queued','hash','queued',NULL,NULL,'{}',0,3,0,'interactive',50,:old),
                  ('lease-1','private-owner','target','agent_step','key-lease','hash','running','lease',:expired,'{}',1,3,0,'interactive',50,:old),
                  ('dead-1','private-owner','target','agent_step','key-dead','hash','failed',NULL,NULL,'{}',3,3,0,'batch',0,:old)'''),
            {'old': clock[0]-600, 'expired': clock[0]-1})
        conn.execute(text('''INSERT INTO agent_action_operations(id,owner_id,created_at,draft_id,status,payload,updated_at)
            VALUES('write-1','private-owner',:old,'draft','outcome_unknown','{"secret":"must not leak"}',:old),
                  ('dispatch-1','private-owner',:old,'draft','dispatching','{}',:old)'''),
            {'old': clock[0]-600})
        conn.execute(text('''INSERT INTO agent_sandbox_cleanup(id,owner_id,creation_key,provider_id,created_at)
            VALUES('sandbox-cleanup-1','private-owner','key','provider',:old)'''), {'old': clock[0]-600})
        conn.execute(text('''INSERT INTO identity_object_cleanup(id,owner_id,kind,object_key)
            VALUES('object-cleanup-1','private-owner','assistant','private-object-key')'''))
        conn.execute(text('''INSERT INTO browser_provider_cleanup(id,owner_id,context_id,session_id,created_at)
            VALUES('browser-cleanup-1','private-owner','context',NULL,:old)'''), {'old': clock[0]-600})
        conn.execute(text('''INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at)
            VALUES('delivery-1','private-owner','reminder','push','failed','{"body":"private text"}',:old)'''),
            {'old': clock[0]-600})

    report = admin.operations_snapshot()
    assert report['metrics']['staleQueuedJobs']['count'] == 1
    assert report['metrics']['expiredJobLeases']['count'] == 1
    assert report['metrics']['exhaustedJobs']['count'] == 1
    assert report['metrics']['unknownExternalWrites']['count'] == 1
    assert report['metrics']['staleExternalDispatches']['count'] == 1
    assert report['metrics']['sandboxCleanupObligations']['count'] == 1
    assert report['metrics']['assistantObjectCleanupObligations']['count'] == 1
    assert report['metrics']['browserCleanupObligations']['count'] == 1
    assert report['metrics']['failedNotificationDeliveries']['count'] == 1
    assert {item['kind'] for item in report['alerts']} >= {'stale_jobs', 'expired_leases', 'write_unknown'}
    serialized = json.dumps(report)
    assert 'private-owner' not in serialized
    assert 'must not leak' not in serialized
    assert 'private-object-key' not in serialized
    assert 'private text' not in serialized
    with ledger.store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM usage_alerts')).scalar_one() == 0
        assert conn.execute(text('SELECT count(*) FROM usage_admin_audit')).scalar_one() == 0


def test_operations_snapshot_rejects_unbounded_thresholds(usage_admin):
    admin, _, _ = usage_admin
    with pytest.raises(ValueError, match='threshold'):
        admin.operations_snapshot(stale_queue_seconds=0)


def test_operations_monitor_persists_redacted_hourly_alerts_and_tracks_expired_sandbox_lease(usage_admin):
    admin, ledger, _ = usage_admin
    with ledger.store.engine.begin() as conn:
        conn.execute(text('''INSERT INTO agent_sandbox_leases(id,owner_id,run_id,input_revision,creation_key,provider_id,
            status,payload,created_at,expires_at)
            VALUES('lease-expired','private-owner','run-secret',1,'creation-secret','provider-secret',
                   'active','{"secret":"do not expose"}',100,200)'''))
    report = admin.operations_snapshot()
    assert report['metrics']['expiredSandboxLeases']['count'] == 1
    assert report['metrics']['activeSandboxLeases']['count'] == 1
    assert report['metrics']['activeSandboxLeases']['oldestAgeSeconds'] is not None
    assert any(item['kind'] == 'sandbox_lease_expiry' for item in report['alerts'])
    alert_snapshot = {'sampledAt':7200,'alerts':[{'kind':'write_unknown','count':2,'oldestAgeSeconds':30}]}
    assert admin.emit_operations_alerts(snapshot=alert_snapshot) == {'observed':1,'created':1}
    assert admin.emit_operations_alerts(snapshot=alert_snapshot) == {'observed':1,'created':0}
    with ledger.store.engine.connect() as conn:
        rows=conn.execute(text("SELECT id,owner_id,kind,payload FROM usage_alerts WHERE kind='agent_write_unknown'")).mappings().all()
    assert len(rows)==1 and rows[0]['owner_id'] is None
    assert rows[0]['id']=='agent-ops:write_unknown:2'
    assert json.loads(rows[0]['payload'])=={'metric':'write_unknown','count':2,'oldestAgeSeconds':30}
    assert 'private-owner' not in rows[0]['payload'] and 'secret' not in rows[0]['payload']


def test_worker_monitor_tick_emits_the_durable_operations_alert(usage_admin, monkeypatch):
    _, ledger, _ = usage_admin
    with ledger.store.engine.begin() as conn:
        conn.execute(text('''INSERT INTO agent_sandbox_leases(id,owner_id,run_id,input_revision,creation_key,provider_id,
            status,payload,created_at,expires_at)
            VALUES('lease-expired-worker','private-owner','run-secret',1,'creation-secret','provider-secret',
                   'active','{}',100,200)'''))
    from backend.app import worker
    monkeypatch.setattr(worker,'_last_usage_monitor',0)
    result=worker.monitor_usage_if_due(ledger.store,now=1000)
    assert result is not None
    with ledger.store.engine.connect() as conn:
        alert=conn.execute(text("SELECT kind,payload FROM usage_alerts WHERE kind='agent_sandbox_lease_expiry'")).mappings().one()
    assert json.loads(alert['payload'])['metric']=='sandbox_lease_expiry'
    assert 'private-owner' not in alert['payload'] and 'provider-secret' not in alert['payload']


def test_refund_is_bounded_idempotent_and_reversible_without_refilling_a_new_period(usage_admin):
    admin, ledger, clock = usage_admin
    reservation = _settled_model(ledger)
    refund = admin.refund('learner-1', reservation['id'], 200_000, actor='support-1',
                          reason='Duplicate provider response', idempotency_key='refund-model-0001')
    assert ledger.allowance('learner-1')['usedMicrocredits'] == 300_000
    activity = ledger.activity('learner-1')
    assert activity['items'][0]['microcredits'] == 300_000
    assert activity['items'][0]['adjustments'][0]['kind'] == 'refund'
    assert activity['adjustments'][0]['id'] == refund['adjustmentId']
    replay = admin.refund('learner-1', reservation['id'], 200_000, actor='support-1',
                          reason='Duplicate provider response', idempotency_key='refund-model-0001')
    assert replay['adjustmentId'] == refund['adjustmentId']
    assert replay['replayed'] is True
    with pytest.raises(ValueError, match='remaining original debit'):
        admin.refund('learner-1', reservation['id'], 300_001, actor='support-1', reason='Too much',
                     idempotency_key='refund-model-0002')
    reversal = admin.reverse_refund('learner-1', refund['adjustmentId'], actor='support-1',
                                    reason='Correction entered in error', idempotency_key='reverse-refund-0001')
    assert ledger.allowance('learner-1')['usedMicrocredits'] == 500_000
    with pytest.raises(ValueError, match='already been reversed'):
        admin.reverse_refund('learner-1', refund['adjustmentId'], actor='support-1', reason='Duplicate reversal',
                             idempotency_key='reverse-refund-0002')
    assert ledger.activity('learner-1')['items'][0]['microcredits'] == 500_000
    assert {row['kind'] for row in ledger.activity('learner-1')['adjustments']} == {'refund', 'refund_reversal'}
    assert reversal['reverses'] == refund['adjustmentId']

    old = _settled_model(ledger, key='old-period-call')
    clock[0] += 18_000
    assert ledger.allowance('learner-1')['usedMicrocredits'] == 0
    admin.refund('learner-1', old['id'], 100_000, actor='support-1', reason='Late adjustment',
                 idempotency_key='refund-old-window-01')
    assert ledger.allowance('learner-1')['usedMicrocredits'] == 0


def test_admin_idempotency_keys_cannot_be_reused_for_other_actions(usage_admin):
    admin, ledger, clock = usage_admin
    reservation = ledger.reserve('learner-1', 'pending', 'model', {'input_tokens': 1000, 'output_tokens': 0})
    ledger.dispatch('learner-1', reservation['id'])
    clock[0] += 300
    first = admin.reconcile(actor='on-call', reason='Expired operation check', idempotency_key='reconcile-00001')
    assert first['settledOrReleased'] == 1
    replay = admin.reconcile(actor='on-call', reason='Expired operation check', idempotency_key='reconcile-00001')
    assert replay['replayed'] is True
    with pytest.raises(UsageError) as error:
        admin.set_capability('browser', True, actor='on-call', reason='Incident',
                             idempotency_key='reconcile-00001')
    assert error.value.detail['code'] == 'usage_admin_idempotency_conflict'


def test_capability_and_identifiers_are_strict(usage_admin):
    admin, _, _ = usage_admin
    with pytest.raises(ValueError, match='Unsupported capability'):
        admin.set_capability('user-input', True, actor='operator', reason='Bad', idempotency_key='invalid-cap-0001')
    with pytest.raises(ValueError, match='Actor'):
        admin.set_capability('browser', True, actor=' operator ', reason='Bad', idempotency_key='invalid-actor-001')


def test_operator_control_migration_downgrades_and_reapplies(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'migration.db')
    root = __import__('pathlib').Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'migrations'))
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, 'head')
    engine = create_engine(url)
    try:
        command.downgrade(config, '0074_usage_accounting_hardening')
        with engine.connect() as conn:
            names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert 'usage_admin_audit' not in names
            assert 'usage_capability_controls' not in names
            assert 'usage_accounts' in names
        command.upgrade(config, 'head')
        with engine.connect() as conn:
            names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {'usage_admin_audit', 'usage_capability_controls'} <= names
    finally:
        engine.dispose()
