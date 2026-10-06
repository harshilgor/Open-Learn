from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine, text
from alembic import command
from alembic.config import Config
from pathlib import Path
from app.usage.ledger import Ledger, UsageError
from app.usage.policy import Policy
from app.usage.pricing import price


@pytest.fixture
def ledger(tmp_path):
    url='sqlite:///'+str(tmp_path/'usage.db')
    root=Path(__file__).resolve().parents[1]
    config=Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'migrations'))
    config.set_main_option('sqlalchemy.url',url)
    command.upgrade(config,'head')
    store=SimpleNamespace(engine=create_engine(url,connect_args={'timeout':30}))
    clock=[100000.0]
    value=Ledger(store,Policy(),lambda:clock[0])
    yield value,clock
    store.engine.dispose()


def test_examples_and_billing_validation():
    assert price('model',{'input_tokens':4000,'output_tokens':800})==3_600_000
    assert price('stt',{'milliseconds':60000})+price('tts',{'characters':450})+price('voice',{'milliseconds':60000})+3_600_000==55_600_000
    assert price('browser',{'milliseconds':180000})+5*3_600_000==33_000_000
    assert price('model',{'input_tokens':1000,'cached_tokens':1000,'output_tokens':0})==100000
    with pytest.raises(ValueError):price('model',{'input_tokens':1,'cached_tokens':2})


def test_test_account_allowance_bypass_retains_spending_caps_and_can_be_revoked(ledger, monkeypatch):
    l, _ = ledger
    owner = 'account_test'
    monkeypatch.setenv('OPENLEARN_USAGE_TEST_EMAILS', 'tester@example.com')
    with l.store.engine.begin() as conn:
        conn.execute(text("INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at,verified_email) VALUES(:id,'test-subject','Tester','active',1,'tester@example.com')"), {'id': owner})
    for index in range(7):
        r = l.reserve(owner, 'exempt:' + str(index), 'tts', {'characters':2000}, root='test:' + str(index))
        l.dispatch(owner, r['id'])
        l.settle(owner, r['id'])
    snapshot = l.allowance(owner)
    assert snapshot['testUnlimited'] and snapshot['availability'] == 'available'
    assert snapshot['usedMicrocredits'] > l.policy.grant
    with pytest.raises(UsageError) as error:
        l.reserve(owner, 'platform-overrun', 'voice', {'milliseconds':1000}, liability=l.policy.daily+1)
    assert error.value.detail['code'] == 'usage_capacity_unavailable'
    with pytest.raises(UsageError):
        l.reserve('other', 'not-exempt', 'tts', {'characters':2000})
    monkeypatch.delenv('OPENLEARN_USAGE_TEST_EMAILS')
    assert not l.allowance(owner)['testUnlimited']
    assert l.allowance(owner)['availability'] == 'unavailable'
    with pytest.raises(UsageError):
        l.reserve(owner, 'revoked', 'tts', {'characters':2000}, root='test:0')


def test_reads_rejections_and_reset(ledger):
    l,clock=ledger
    assert l.allowance('a')['windowState']=='ready'
    with pytest.raises(UsageError):l.reserve('a','too-large','tts',{'characters':2000})
    assert l.allowance('a')['windowState']=='ready'
    r=l.reserve('a','first','tts',{'characters':1000})
    assert l.allowance('a')['heldMicrocredits']==60_000_000
    l.dispatch('a',r['id']);l.settle('a',r['id'],{'characters':900})
    l.settle('a',r['id'],{'characters':900})
    assert l.allowance('a')['usedMicrocredits']==54_000_000
    clock[0]+=18000
    assert l.allowance('a')['windowState']=='ready'
    assert l.allowance('a')['usedMicrocredits']==0
    assert l.activity('a')['items'][0]['microcredits']==54_000_000
    assert l.activity('b')['items']==[]


def test_simultaneous_admission_cannot_overspend(ledger):
    l,_=ledger
    def reserve(i):
        try:return l.reserve('a',str(i),'tts',{'characters':1000})['id']
        except UsageError:return None
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(reserve,range(2)))
    assert sum(bool(r) for r in results)==1
    assert l.allowance('a')['heldMicrocredits']==60_000_000


def test_account_admission_rate_limits_new_roots_but_allows_existing_root(ledger):
    l,_=ledger
    for index in range(5):
        l.reserve('a',f'rate-{index}','model',{'input_tokens':1,'output_tokens':1},root=f'task-{index}')
    # A new provider operation in an already-admitted task is not a new user
    # admission and still shares its original task cap.
    l.reserve('a','rate-existing-root','model',{'input_tokens':1,'output_tokens':1},root='task-0')
    with pytest.raises(UsageError) as error:
        l.reserve('a','rate-sixth','model',{'input_tokens':1,'output_tokens':1},root='task-5')
    assert error.value.status_code==429
    assert error.value.detail['code']=='usage_admission_rate_limited'
    assert error.value.detail['resetsAt']==100060.0


def test_replay_dispatch_and_uncertainty(ledger):
    l,clock=ledger
    r=l.reserve('a','key','model',{'input_tokens':1000,'output_tokens':1000})
    assert l.reserve('a','key','model',{'input_tokens':1000,'output_tokens':1000})['id']==r['id']
    with pytest.raises(UsageError):l.reserve('a','key','model',{'input_tokens':1001,'output_tokens':1000})
    l.dispatch('a',r['id'])
    with pytest.raises(UsageError):l.dispatch('a',r['id'])
    with pytest.raises(ValueError):l.settle('a',r['id'],release=True)
    clock[0]+=300
    assert l.allowance('a')['reasonCode']=='usage_reconciliation_pending'
    assert l.reconcile()==1
    assert l.allowance('a')['usedMicrocredits']==2_500_000


def test_provider_cost_atomic_limits_and_overrun(ledger):
    l,_=ledger
    l.policy=Policy(daily=100,monthly=100)
    r=l.reserve('a','key','tool',{},liability=80)
    with pytest.raises(UsageError):l.reserve('b','key','tool',{},liability=30)
    l.dispatch('a',r['id']);l.settle('a',r['id'],{},cost=110)
    assert l.allowance('a')['reasonCode']=='usage_capacity_unavailable'
    with l.store.engine.connect() as conn:
        assert conn.execute(text("SELECT used_nano FROM usage_platform_periods WHERE id LIKE 'day:%'")).scalar_one()==110
        assert conn.execute(text("SELECT kind FROM usage_alerts WHERE reservation_id=:id"),{'id':r['id']}).scalar_one()=='provider_liability_overrun'
        budget_alerts=conn.execute(text("SELECT id FROM usage_alerts WHERE kind='platform_budget_threshold'")).scalars().all()
        assert len(budget_alerts)==6
        assert {item.rsplit(':',1)[-1] for item in budget_alerts}=={'50','80','95'}
    assert l.unblock('a','on-call','Provider receipt reconciled') is True
    with l.store.engine.connect() as conn:
        assert conn.execute(text("SELECT actor,kind FROM usage_adjustments WHERE owner_id='a'")).one()==('on-call','unblock')


def test_activity_is_task_grouped_and_cursor_pages_ties(ledger):
    l,_=ledger
    first=l.reserve('a','one','model',{'input_tokens':1000,'output_tokens':0},root='z-task')
    l.dispatch('a',first['id']);l.settle('a',first['id'],{'input_tokens':1000,'output_tokens':0})
    second=l.reserve('a','two','tts',{'characters':100},root='z-task')
    l.dispatch('a',second['id']);l.settle('a',second['id'],{'characters':100})
    third=l.reserve('a','three','stt',{'milliseconds':1000},root='a-task')
    l.dispatch('a',third['id']);l.settle('a',third['id'],{'milliseconds':1000})
    page=l.activity('a',limit=1)
    assert len(page['items'])==1
    assert page['items'][0]['root_id']=='z-task'
    assert {part['component'] for part in page['items'][0]['components']}=={'model','tts'}
    assert page['nextCursor']
    next_page=l.activity('a',cursor=page['nextCursor'],limit=1)
    assert [item['root_id'] for item in next_page['items']]==['a-task']
    assert next_page['nextCursor'] is None


def test_activity_includes_pending_reservation_and_component_hold(ledger):
    l,_=ledger
    row=l.reserve('a','pending-task','model',{'input_tokens':1000,'output_tokens':0},root='task-pending')
    page=l.activity('a')
    assert len(page['items'])==1
    item=page['items'][0]
    assert item['id']==f"task-pending:{row['period_id']}"
    assert item['status']=='pending'
    assert item['microcredits']==0
    assert item['held_micro']==500_000
    assert item['components']==[{'root_id':'task-pending','period_id':row['period_id'],'component':'model',
                                 'microcredits':0,'held_micro':500_000,'created_at':100000.0,'source':'pending'}]
    assert page['adjustments']==[]


def test_usage_activity_route_returns_owner_scoped_mobile_web_contract(ledger):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.material_routes import material_owner
    from app.usage_routes import build_usage_router

    l,_=ledger
    l.reserve('a','route-pending','model',{'input_tokens':1000,'output_tokens':0},root='route-task')
    app=FastAPI()
    app.include_router(build_usage_router(lambda:l.store))
    app.dependency_overrides[material_owner]=lambda:'a'
    response=TestClient(app).get('/v1/usage/activity?includeComponents=true')
    assert response.status_code==200
    body=response.json()
    assert response.headers['cache-control']=='private, no-store'
    assert body['items'][0]['id'].startswith('route-task:')
    assert body['items'][0]['status']=='pending'
    assert body['items'][0]['held_micro']==500_000
    assert body['items'][0]['components'][0]['component']=='model'
    assert body['adjustments']==[]


def test_task_cap_is_atomic_and_survives_window_reset(ledger):
    l,clock=ledger
    with l.transaction() as conn:
        l.accept_task_cap_in_transaction(conn,'a','long-task',600_000,clock[0])
    first=l.reserve('a','long-first','model',{'input_tokens':1000,'output_tokens':0},root='long-task')
    l.dispatch('a',first['id']);l.settle('a',first['id'],{'input_tokens':1000,'output_tokens':0})
    with pytest.raises(UsageError) as error:
        l.reserve('a','long-second','model',{'input_tokens':201,'output_tokens':0},root='long-task')
    assert error.value.detail['code']=='usage_task_cap_exhausted'
    with l.transaction() as conn:
        l.accept_task_cap_in_transaction(conn,'a','reset-root',l.policy.grant,clock[0])
    clock[0]+=18_000
    with pytest.raises(UsageError) as reset_error:
        l.reserve('a','reset-second','model',{'input_tokens':1000,'output_tokens':0},root='reset-root')
    assert reset_error.value.detail['code']=='usage_task_window_changed'
    assert l.allowance('a')['windowState']=='ready'
    with l.store.engine.connect() as conn:
        cap=conn.execute(text('SELECT maximum_micro FROM usage_task_caps WHERE owner_id=:owner AND root_id=:root'),{'owner':'a','root':'long-task'}).scalar_one()
        assert cap==600_000


def test_undispatched_expiry_releases_hold_without_platform_cost(ledger):
    l,clock=ledger
    row=l.reserve('a','never-sent','tool',{},liability=20_000_000)
    clock[0]+=300
    assert l.reconcile()==1
    assert l.allowance('a')['usedMicrocredits']==0
    assert l.allowance('a')['heldMicrocredits']==0
    with l.store.engine.connect() as conn:
        platform=conn.execute(text("SELECT used_nano,held_nano FROM usage_platform_periods WHERE id LIKE 'day:%'")).one()
        event=conn.execute(text('SELECT cost_nano,source FROM usage_events WHERE reservation_id=:id'),{'id':row['id']}).one()
    assert platform==(0,0)
    assert event==(0,'released')


def test_rate_snapshot_is_immutable_per_provider_version(ledger):
    l,_=ledger
    l.policy=Policy(provider_rate_version='rates-1')
    l.reserve('a','provider-call','search',{'requests':1},liability=10,provider='exa',model='search',
              provider_rates={'usd_nano_per_request':10})
    with pytest.raises(UsageError) as error:
        l.reserve('a','second-call','search',{'requests':1},liability=20,provider='exa',model='search',
                  provider_rates={'usd_nano_per_request':20})
    assert error.value.detail['code']=='usage_rate_version_conflict'


def test_hosted_worker_reconciles_expired_holds(ledger):
    from app import worker
    l,_=ledger
    row=l.reserve('a','worker-reconcile','model',{'input_tokens':1000,'output_tokens':100})
    l.dispatch('a',row['id'])
    worker._last_usage_reconcile=0
    assert worker.reconcile_usage_if_due(l.store,now=100)==1
    assert worker.reconcile_usage_if_due(l.store,now=114)==0
    assert worker.reconcile_usage_if_due(l.store,now=115)==0
    assert l.allowance('a')['reasonCode'] is None


def test_usage_monitor_alerts_stale_reconciliation_and_outbox_growth(ledger):
    l,clock=ledger
    row=l.reserve('a','monitor-lag','model',{'input_tokens':1000,'output_tokens':100},seconds=20)
    l.dispatch('a',row['id'])
    clock[0]+=100
    result=l.monitor(outbox_threshold=1)
    assert result=={'staleReconciliationCount':1,'outboxEventCount':1}
    # Polls are idempotent: they do not create an alert storm for one incident.
    l.monitor(outbox_threshold=1)
    with l.store.engine.connect() as conn:
        alerts=conn.execute(text("SELECT kind,reservation_id FROM usage_alerts ORDER BY id")).all()
    assert ('usage_reconciliation_lag',row['id']) in alerts
    assert ('usage_outbox_growth',None) in alerts
    assert len(alerts)==2


def test_direct_live_transcription_stays_gated_until_metered(monkeypatch):
    from app.live_transcription import live_transcription_enabled
    monkeypatch.setenv('OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED','true')
    assert live_transcription_enabled() is False


def test_accounting_hardening_migration_can_downgrade_and_reapply(tmp_path):
    url='sqlite:///'+str(tmp_path/'migration.db')
    root=Path(__file__).resolve().parents[1]
    config=Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'migrations'))
    config.set_main_option('sqlalchemy.url',url)
    command.upgrade(config,'head')
    command.downgrade(config,'0073_unified_usage')
    command.upgrade(config,'head')
    engine=create_engine(url)
    try:
        with engine.connect() as conn:
            names={row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {'usage_adjustments','usage_alerts','usage_provider_rate_cards'} <= names
    finally:
        engine.dispose()
