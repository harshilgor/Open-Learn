from pathlib import Path
import json
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.app.class_device_routes import DraftInput, PairInput, PairPreviewInput, ClaimInput, HeartbeatInput, CaptureCommandInput, AckInput
from backend.app.class_devices import ClassDeviceService
from backend.app.storage import Store


def test_abandoned_empty_phone_draft_expires_without_deleting_recording(setup):
    store,svc,class_id,body=setup
    with store.transaction() as conn:
        conn.execute(text('UPDATE class_sessions SET created_at=:before WHERE id=:id'),{'id':class_id,'before':time.time()-90000})
        svc.cleanup(conn)
        payload=json.loads(conn.execute(text('SELECT payload FROM class_sessions WHERE id=:id'),{'id':class_id}).scalar_one())
        assert payload['draftExpired'] and payload['cancelled']
        assert conn.execute(text('SELECT COUNT(*) FROM lecture_recordings WHERE id=:id'),{'id':payload['recordingId']}).scalar_one()==1
    with pytest.raises(HTTPException) as failure:svc.pairing('alice',class_id,PairInput(commandId='new',deviceId='laptop'))
    assert failure.value.detail['code']=='draft_expired'


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('OPENLEARN_CLASS_PHONE_PAIRING_ENABLED','true')
    root=Path('work')/('class-devices-'+uuid4().hex);root.mkdir(parents=True)
    monkeypatch.setenv('AI_TUTOR_NOTE_VAULT_DIR',str(root/'notes'))
    monkeypatch.setenv('AI_TUTOR_RECORDINGS_DIR',str(root/'audio'))
    store=Store(root/'data.sqlite')
    svc=ClassDeviceService(store)
    body=DraftInput(commandId='draft',deviceId='laptop',startedAtMs=1,title='Biology')
    draft=svc.draft('alice',body)
    yield store,svc,draft['session']['id'],body
    store.close()


def pair(svc,class_id,device='phone'):
    pairing=svc.pairing('alice',class_id,PairInput(commandId=uuid4().hex,deviceId='laptop'))
    body=ClaimInput(code=pairing['code'],deviceId=device,commandId=uuid4().hex,consent=True,captureCapability='c'*64)
    return pairing,body,svc.claim('alice',body)


def test_draft_is_idempotent_and_pairing_requires_same_owner_and_consent(setup):
    _store,svc,class_id,body=setup
    assert svc.draft('alice',body)['session']['id']==class_id
    pairing=svc.pairing('alice',class_id,PairInput(commandId='pair',deviceId='laptop'))
    assert '<svg' in pairing['qrSvg'] and len(pairing['code'])==12
    claim=ClaimInput(code=pairing['code'],deviceId='phone',commandId='claim',consent=False,captureCapability='c'*64)
    with pytest.raises(HTTPException) as error:svc.claim('alice',claim)
    assert error.value.detail['code']=='recording_consent_required'
    claim.consent=True
    with pytest.raises(HTTPException):svc.claim('bob',claim)
    first=svc.claim('alice',claim)
    assert svc.claim('alice',claim)==first
    assert 'captureCapability' not in str(first)


def test_pairing_replay_with_different_device_is_rejected(setup):
    _store,svc,class_id,_body=setup
    _pairing,claim,_run=pair(svc,class_id)
    claim.deviceId='other-phone'
    with pytest.raises(HTTPException) as error:svc.claim('alice',claim)
    assert error.value.detail['code']=='pairing_used'


def test_remote_stop_is_pending_until_real_state_ack_and_handoff_preserves_ranges(setup):
    store,svc,class_id,_body=setup
    _pairing,_claim,run=pair(svc,class_id)
    svc.heartbeat('alice',class_id,run['runId'],HeartbeatInput(state='recording',audioEndMs=5000,sealedChunkCount=1), 'c'*64)
    status=svc.status('alice',class_id)
    request=CaptureCommandInput(commandId='handoff',runId=run['runId'],expectedRevision=status['run']['revision'],action='handoff')
    command=svc.command('alice',class_id,request)
    assert command['state']=='pending'
    assert svc.status('alice',class_id)['run']['state']=='recording'
    with pytest.raises(HTTPException):svc.pairing('alice',class_id,PairInput(commandId='second',deviceId='laptop'))
    with pytest.raises(HTTPException):svc.ack('alice',class_id,command['id'],AckInput(accepted=True,state='recording'), 'c'*64)
    svc.ack('alice',class_id,command['id'],AckInput(accepted=True,state='stopped',audioEndMs=6000,sealedChunkCount=2), 'c'*64)
    _pairing,_claim,next_run=pair(svc,class_id,'second-phone')
    assert next_run['epoch']==run['epoch']+1 and next_run['sequenceBase']==2 and next_run['startMs']==6000
    with pytest.raises(HTTPException) as error:
        svc.heartbeat('alice',class_id,run['runId'],HeartbeatInput(state='recording',audioEndMs=7000,sealedChunkCount=2), 'c'*64)
    assert error.value.detail['code']=='stale_capture_epoch'
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM class_capture_runs WHERE class_id=:class'),{'class':class_id}).scalar_one()==2


def test_resume_expires_and_cannot_restart_stopped_microphone(setup):
    store,svc,class_id,_body=setup
    _pairing,_claim,run=pair(svc,class_id)
    svc.heartbeat('alice',class_id,run['runId'],HeartbeatInput(state='paused',audioEndMs=1000,sealedChunkCount=1), 'c'*64)
    status=svc.status('alice',class_id)
    command=svc.command('alice',class_id,CaptureCommandInput(commandId='resume',runId=run['runId'],expectedRevision=status['run']['revision'],action='resume'))
    with store.transaction() as conn:
        conn.execute(text('UPDATE class_capture_commands SET created_at=0 WHERE id=:id'),{'id':command['id']})
    received=svc.heartbeat('alice',class_id,run['runId'],HeartbeatInput(state='paused',audioEndMs=1000,sealedChunkCount=1), 'c'*64)
    assert received['commands']==[]
    assert svc.status('alice',class_id)['commands'][0]['state']=='expired'


def test_pairing_attempt_budget_is_durable(setup):
    _store,svc,_class,_body=setup
    for _ in range(10):svc.rate('alice','phone','same-network')
    with pytest.raises(HTTPException) as error:svc.rate('alice','phone','same-network')
    assert error.value.status_code==429


def test_pairing_preview_is_owned_read_only_and_expires(setup):
    store,svc,class_id,_=setup
    pairing=svc.pairing('alice',class_id,PairInput(commandId='preview-pair',deviceId='laptop',deviceName='Library laptop'))
    body=PairPreviewInput(code=pairing['code'],deviceId='phone')
    preview=svc.preview('alice',body)
    assert preview['title']=='Biology' and preview['ownerId']=='alice' and preview['requestingDeviceName']=='Library laptop'
    assert preview['classId']==class_id and 'captureCapability' not in str(preview)
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM class_capture_runs WHERE class_id=:id'),{'id':class_id}).scalar_one()==0
        assert conn.execute(text('SELECT state FROM class_pairings WHERE id=:id'),{'id':pairing['id']}).scalar_one()=='pending'
    with pytest.raises(HTTPException) as failure:svc.preview('bob',body)
    assert failure.value.status_code==404
    with store.transaction() as conn:conn.execute(text('UPDATE class_pairings SET expires_at=0 WHERE id=:id'),{'id':pairing['id']})
    with pytest.raises(HTTPException) as failure:svc.preview('alice',body)
    assert failure.value.detail['code']=='pairing_expired'


def test_phone_status_retains_confirmed_duration_backlog_and_battery(setup):
    store,svc,class_id,_=setup
    _,_,run=pair(svc,class_id)
    svc.heartbeat('alice',class_id,run['runId'],HeartbeatInput(state='paused',audioEndMs=61000,sealedChunkCount=3,backlog=2,batteryPercent=0),'c'*64)
    status=svc.status('alice',class_id)['run']
    assert status['state']=='paused' and status['audioEndMs']==61000 and status['backlog']==2 and status['batteryPercent']==0
    with store.transaction() as conn:conn.execute(text('UPDATE class_capture_runs SET last_seen_at=0 WHERE id=:id'),{'id':run['runId']})
    assert svc.status('alice',class_id)['run']['stale']
