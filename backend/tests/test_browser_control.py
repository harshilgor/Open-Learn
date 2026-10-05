"""Handoff races, identity, stale input, privacy and failed release boundaries."""
import time
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_browser_assistant import environment
from backend.app.identity import Principal
from backend.app.browser_assistant.connections import Connections
from backend.app.browser_assistant.contracts import ConnectionCreate,TaskCreate,TaskCommand,BrowserResult,Observation
from backend.app.browser_assistant.service import AssistantService
from backend.app.browser_assistant.control import BrowserControl
from backend.app.browser_assistant.workers import AssistantWorker
from backend.app.browser_assistant.executors.cloud import CloudExecutor


def setup(store, executor='local'):
    sites=Connections(store)
    site=sites.create('alice',ConnectionCreate(label='Study',origin='https://study.example.org',executor=executor))
    device=None
    if executor=='local':
        grant=sites.pair('alice',site['id']);device=Principal('alice','browser',grant['deviceId'])
    task=AssistantService(store).create('alice',TaskCreate(message='Open https://study.example.org',connection_id=site['id']))
    return task,device


def command(control, task, action):
    return control.command('alice',task['id'],TaskCommand(action=action,expected_revision=task['revision']))


def test_local_handoff_waits_for_device_and_fences_old_result(environment):
    store,_=environment;task,device=setup(store);svc=AssistantService(store);control=BrowserControl(store)
    AssistantWorker(store).tick()
    old=svc.poll(device)['commands'][0]
    task=control.repo.read('assistant_runs','alice',task['id'])
    task=command(control,task,'takeover')
    assert task['browserControl']['owner']=='requesting'
    assert not svc.poll(device)['commands']
    with pytest.raises(HTTPException):control.view('alice',task['id'])
    with pytest.raises(HTTPException):command(control,task,'return_control')
    with pytest.raises(HTTPException):svc.acknowledge(device,old['id'],BrowserResult(generation=old['generation'],connection_revision=old['connectionRevision'],observation=Observation(url='https://study.example.org',document_revision='stale')))
    handoff=svc.poll(device)['handoffs'][0]
    assert control.acknowledge(device,task['id'],handoff['generation'])['status']=='accepted'
    assert control.acknowledge(device,task['id'],handoff['generation'])['duplicate']
    assert control.view('alice',task['id'])['kind']=='local'
    task=control.repo.read('assistant_runs','alice',task['id'])
    with pytest.raises(HTTPException):svc.command('alice',task['id'],TaskCommand(action='resume',expected_revision=task['revision']))
    returned=command(control,task,'return_control')
    assert returned['browserControl']['owner']=='agent'
    AssistantWorker(store).tick()
    fresh=svc.poll(device)['commands'][0]
    assert fresh['action']['tool']=='observe'
    assert not fresh['snapshotBasis']


def test_cloud_waits_for_inflight_input_and_discards_stale_access(environment,monkeypatch):
    store,_=environment;task,_=setup(store,'cloud');control=BrowserControl(store)
    with store.transaction() as conn:
        run=control.repo.run(conn,'alice',task['id'])
        task=control.repo.update_run(conn,run,status='running',pendingCommand='operation')
    assert control.begin('alice',task['id'],'operation')
    task=control.repo.read('assistant_runs','alice',task['id'])
    task=command(control,task,'takeover')
    assert task['browserControl']['owner']=='requesting'
    assert not control.begin('alice',task['id'],'operation')
    with pytest.raises(HTTPException):control.view('alice',task['id'])
    with pytest.raises(HTTPException):command(control,task,'return_control')
    control.end('alice',task['id'],'operation')
    task=control.repo.read('assistant_runs','alice',task['id'])
    assert task['browserControl']['owner']=='human'
    generation=task['browserControl']['generation']
    monkeypatch.setattr(CloudExecutor,'release_control',lambda *_:True)
    task=command(control,task,'return_control')
    assert task['browserControl']['generation']!=generation
    with pytest.raises(HTTPException):control.view('alice',task['id'])


def test_preview_is_read_only_and_withheld_during_handoff(environment):
    store,_=environment;task,device=setup(store);control=BrowserControl(store)
    assert control.preview('alice',task['id'])['state']=='waiting'
    AssistantWorker(store).tick()
    service=AssistantService(store);operation=service.poll(device)['commands'][0]
    service.acknowledge(device,operation['id'],BrowserResult(generation=operation['generation'],connection_revision=operation['connectionRevision'],observation=Observation(url='https://study.example.org',document_revision='current',title='Study')))
    preview=control.preview('alice',task['id'])
    assert preview['title']=='Study' and 'generation' not in preview and 'connectUrl' not in preview
    task=control.repo.read('assistant_runs','alice',task['id'])
    command(control,task,'takeover')
    with pytest.raises(HTTPException):control.preview('alice',task['id'])


def test_failed_provider_release_keeps_automation_paused(environment,monkeypatch):
    store,_=environment;task,_=setup(store,'cloud');control=BrowserControl(store)
    task=command(control,task,'takeover')
    monkeypatch.setattr(CloudExecutor,'release_control',lambda *_:False)
    with pytest.raises(HTTPException) as error:command(control,task,'return_control')
    assert error.value.status_code==503
    fresh=control.repo.read('assistant_runs','alice',task['id'])
    assert fresh['status']=='paused' and fresh['browserControl']['owner']=='returning'
    with pytest.raises(HTTPException):control.view('alice',task['id'])
    monkeypatch.setattr(CloudExecutor,'release_control',lambda *_:True)
    assert command(control,fresh,'return_control')['status']=='queued'


def test_owner_device_revision_and_revocation_fences(environment):
    store,_=environment;task,device=setup(store);control=BrowserControl(store)
    with pytest.raises(HTTPException):control.command('bob',task['id'],TaskCommand(action='takeover',expected_revision=task['revision']))
    task=command(control,task,'takeover')
    with pytest.raises(HTTPException):control.acknowledge(Principal('alice','browser','other'),task['id'],task['browserControl']['generation'])
    with pytest.raises(HTTPException):control.acknowledge(device,task['id'],'old')
    with pytest.raises(HTTPException):control.command('alice',task['id'],TaskCommand(action='return_control',expected_revision=1))
    Connections(store).revoke('alice',task['connectionId'])
    with pytest.raises(HTTPException):control.acknowledge(device,task['id'],task['browserControl']['generation'])
    with pytest.raises(HTTPException):control.view('alice',task['id'])


def test_public_reader_has_no_takeover(environment):
    store,_=environment;task,_=setup(store,'public_fetch')
    with pytest.raises(HTTPException):command(BrowserControl(store),task,'takeover')


def test_cloud_view_private_gate_and_short_lived_url(environment,monkeypatch):
    store,_=environment;task,_=setup(store,'cloud');control=BrowserControl(store)
    task=command(control,task,'takeover')
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload) VALUES('lease','alice',:run,:connection,'provider','active',:expires,'{}')"),{'run':task['id'],'connection':task['connectionId'],'expires':time.time()+600})
    monkeypatch.setattr('backend.app.browser_assistant.executors.cloud.readiness',lambda:{'privateLoginVerified':False})
    with pytest.raises(HTTPException):control.view('alice',task['id'])
    monkeypatch.setattr('backend.app.browser_assistant.executors.cloud.readiness',lambda:{'privateLoginVerified':True})
    monkeypatch.setattr('backend.app.browser_assistant.executors.cloud.BrowserbaseProvider.live_view',lambda *_:'https://debug.browserbase.com/view')
    view=control.view('alice',task['id'])
    assert 0<view['expiresAt']-time.time()<=60
    monkeypatch.setattr('backend.app.browser_assistant.executors.cloud.BrowserbaseProvider.live_view',lambda *_:'https://attacker.example/view')
    with pytest.raises(HTTPException):control.view('alice',task['id'])
