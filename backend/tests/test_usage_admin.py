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
