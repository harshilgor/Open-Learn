"""Reviewed writes and children: real persistence, mock Google, no external effects."""
import json
import time
import base64
import os
from email import message_from_bytes
from urllib.parse import parse_qs,urlsplit
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException,FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.tests.test_agent_execution import env,start,answer
from backend.app.agent_execution.worker import AgentWorker
from backend.app.agent_execution.connected_actions import ConnectedActions
from backend.app.agent_execution.connected_contracts import Draft,Decision,ChildRequest,ConnectorError
from backend.app.agent_execution.google_connector import GoogleConnections,GoogleAdapter,vault
from backend.app.agent_execution.delegation import Delegation
from backend.app.agent_execution.connected_routes import build_connected_router
from backend.app.agent_execution.contracts import Command
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.workflow_store import encoded

class FakeGoogle:
    is_test_adapter=True
    def __init__(self):self.sent={};self.calls=0;self.ambiguous=False;self.confirm=True
    def event(self,*args):return {'id':'event1','etag':'"v1"','summary':'Old event'}
    def dispatch(self,owner,connection,operation,payload,attachments):
        self.calls+=1;self.sent[operation]={'providerId':'google-'+operation,'verified':True}
        if self.ambiguous:raise ConnectorError('timeout',True)
        return self.sent[operation]
    def reconcile(self,owner,connection,operation,payload):return self.sent.get(operation) if self.confirm else None

@pytest.fixture
def connected(env,monkeypatch):
    db,coordinator,repo=env
    monkeypatch.setenv('OPENLEARN_CONNECTORS_ENABLED','true');monkeypatch.setenv('OPENLEARN_DELEGATION_ENABLED','true');monkeypatch.setenv('AI_TUTOR_ENV','development')
    monkeypatch.setenv('OPENLEARN_CONNECTOR_VAULT_KEY',Fernet.generate_key().decode())
    with db.transaction() as conn:
        conn.execute(text("INSERT INTO agent_app_connections(id,owner_id,created_at,revision,status,payload,secret) VALUES('google','alice',:now,1,'connected',:payload,:secret)"),{'now':time.time(),'payload':encoded({'provider':'google','accountId':'subject1','email':'alice@example.com','capabilities':['gmail_send','gmail_read','calendar_write','drive_read'],'scopes':[]}), 'secret':vault().encrypt(encoded({'access_token':'test-only','expires_at':time.time()+3600}).encode()).decode()})
    _,run=start(env);fake=FakeGoogle();return db,coordinator,repo,run,fake,ConnectedActions(db,fake)

def mail(connected,key='draft1',**kwargs):
    db,_,_,run,_,service=connected
    return service.draft('alice',run['id'],Draft(connectionId='google',expectedTaskRevision=run['revision'],kind='gmail_send',mail={'to':['professor@example.com'],'subject':'Office hours','body':'Could we meet Tuesday?',**kwargs}),key)
def approve(connected,draft,key='decision1'):
    return connected[-1].decide('alice',draft['id'],Decision(decision='approve',expectedRevision=draft['revision'],actionHash=draft['actionHash']),key)

def test_explicit_review_single_write_duplicate_and_cross_owner(connected):
    draft=mail(connected);fake=connected[4];service=connected[-1]
    assert mail(connected)['id']==draft['id'];service.tick();assert fake.calls==0
    receipt=approve(connected,draft);assert approve(connected,draft)==receipt
    service.tick();service.tick();assert fake.calls==1
    assert service.list('alice',connected[3]['id'])[0]['operation']['status']=='succeeded'
    with pytest.raises(HTTPException) as error:service.list('bob',connected[3]['id'])
    assert error.value.status_code==404

def test_changed_draft_and_approval_hash_rejected(connected):
    draft=mail(connected)
    with pytest.raises(HTTPException):mail(connected,body='Changed content')
    with pytest.raises(HTTPException):connected[-1].decide('alice',draft['id'],Decision(decision='approve',expectedRevision=1,actionHash='0'*64),'bad')
    assert connected[4].calls==0

def test_rejection_never_dispatches_and_invalid_timezone_is_validation_error(connected):
    from pydantic import ValidationError
    from backend.app.agent_execution.connected_contracts import Event
    draft=mail(connected)
    receipt=connected[-1].decide('alice',draft['id'],Decision(decision='reject',expectedRevision=draft['revision'],actionHash=draft['actionHash']),'reject')
    assert receipt['operationId'] is None
    connected[-1].tick()
    assert connected[4].calls==0
    with pytest.raises(ValidationError):
        Event(calendarId='primary',summary='Review',start='2026-10-05T10:00:00+00:00',end='2026-10-05T11:00:00+00:00',timeZone='Invalid/Timezone')

@pytest.mark.parametrize('change',['expire','revoke','steer','cancel'])
def test_permission_input_expiry_fences_dispatch(connected,change):
    db,coordinator,repo,run,fake,service=connected;draft=mail(connected);approve(connected,draft)
    if change=='expire':
        with db.transaction() as conn:conn.execute(text('UPDATE agent_action_drafts SET expires_at=0 WHERE id=:id'),{'id':draft['id']})
    elif change=='revoke':GoogleConnections(db).disconnect('alice','google')
    else:coordinator.command('alice',run['id'],Command(commandId='change1',action=change,expectedRevision=run['revision'],text='Ignore trial 3' if change=='steer' else None))
    service.tick();assert fake.calls==0
    assert service.list('alice',run['id'])[0]['operation']['status']=='failed'

def test_unknown_email_never_resends_and_reconciles(connected):
    service=connected[-1];fake=connected[4];fake.ambiguous=True;fake.confirm=False
    draft=mail(connected);approve(connected,draft);service.tick();service.tick();service.reconcile('alice',draft['id'])
    assert fake.calls==1 and service.list('alice',connected[3]['id'])[0]['operation']['status']=='outcome_unknown'
    fake.confirm=True;service.reconcile('alice',draft['id']);assert fake.calls==1
    assert service.list('alice',connected[3]['id'])[0]['operation']['status']=='succeeded'

def test_feature_stop_allows_uncertain_read_reconciliation(connected,monkeypatch):
    service=connected[-1];connected[4].ambiguous=True;draft=mail(connected);approve(connected,draft);service.tick()
    monkeypatch.setenv('OPENLEARN_CONNECTORS_ENABLED','false');service.reconcile('alice',draft['id'])
    assert service.list('alice',connected[3]['id'])[0]['status']=='succeeded' and connected[4].calls==1

def test_crash_after_effect_reconciles_without_duplicate(connected):
    service=connected[-1];draft=mail(connected);receipt=approve(connected,draft)
    class Crash(BaseException):pass
    def die(*args):raise Crash()
    with pytest.raises(Crash):service.execute(receipt['operationId'],after_dispatch=die)
    with connected[0].transaction() as conn:conn.execute(text('UPDATE agent_action_operations SET updated_at=0'))
    service.tick();assert connected[4].calls==1
    assert service.list('alice',connected[3]['id'])[0]['status']=='succeeded'

def test_reconciliation_permission_loss_remains_unknown(connected):
    service=connected[-1];fake=connected[4];fake.ambiguous=True;draft=mail(connected);approve(connected,draft);service.tick()
    def denied(*args):raise ConnectorError('connection_scope_denied')
    fake.reconcile=denied;service.reconcile('alice',draft['id'])
    assert service.list('alice',connected[3]['id'])[0]['status']=='outcome_unknown'

def test_parent_child_limits_outputs_and_no_recursive_or_connector_grants(connected):
    db,coordinator,repo,run,_,service=connected;worker=AgentWorker(db);worker.tick();run=repo.read('alice',run['id']);answer(coordinator,repo,run);worker.tick();run=repo.read('alice',run['id'])
    delegation=Delegation(db);request=ChildRequest(expectedRevision=run['revision'],kind='lab_analysis',assignment='Independently check speeds')
    child=delegation.create('alice',run['id'],request,'child1');assert delegation.create('alice',run['id'],request,'child1')==child
    child_task=repo.read('alice',child['childId'])
    assert child_task['usageRootId']==run['usageRootId']
    with pytest.raises(HTTPException):delegation.create('alice',child_task['id'],ChildRequest(expectedRevision=child_task['revision'],kind='lab_analysis',assignment='Grandchild'),'grandchild')
    with pytest.raises(ConnectorError):service.draft('alice',child_task['id'],Draft(connectionId='google',expectedTaskRevision=child_task['revision'],kind='gmail_send',mail={'to':['p@example.com'],'subject':'Hello','body':'No'}),'child-write')
    worker.tick();delegation.tick();assert delegation.list('alice',run['id'])['items'][0]['status']=='accepted'
    from backend.app.agent_execution.contracts import Message
    child_task=repo.read('alice',child['childId'])
    with pytest.raises(HTTPException):coordinator.admit('alice',Message(clientMessageId='child-followup',sessionId='session',text='Change this child',targetTaskId=child_task['id'],expectedRevision=child_task['revision']),'child-followup')
    delegation.create('alice',run['id'],request,'child2')
    with pytest.raises(HTTPException) as error:delegation.create('alice',run['id'],request,'child3')
    assert error.value.status_code==429

def test_child_output_integrity_failure_is_rejected(connected):
    db,coordinator,repo,run,_,_=connected
    worker=AgentWorker(db);worker.tick();run=repo.read('alice',run['id']);answer(coordinator,repo,run);worker.tick();run=repo.read('alice',run['id'])
    delegation=Delegation(db)
    child=delegation.create('alice',run['id'],ChildRequest(expectedRevision=run['revision'],kind='lab_analysis',assignment='Check values'),'child-integrity')
    worker.tick()
    assert repo.read('alice',child['childId'])['status']=='completed'
    with db.transaction() as conn:
        conn.execute(text("UPDATE agent_artifacts SET sha256=:hash WHERE run_id=:child"),{'hash':'0'*64,'child':child['childId']})
    delegation.tick()
    receipt=delegation.list('alice',run['id'])['items'][0]
    assert receipt['status']=='rejected'
    assert receipt['verification']['reasonCode']=='child_output_unavailable'
    assert repo.read('alice',run['id'])['status']=='completed'

def test_shared_budget_charges_retries_once_and_bounds(connected):
    db,_,repo,run,_,_=connected;delegation=Delegation(db)
    child=delegation.create('alice',run['id'],ChildRequest(expectedRevision=run['revision'],kind='lab_analysis',assignment='Check values'),'child1')
    delegation.charge('alice',child['childId'],'read1','calls',1);delegation.charge('alice',child['childId'],'read1','calls',1)
    assert delegation.list('alice',run['id'])['budget']['calls_remaining']==23
    from backend.app.agent_execution.research_contracts import ResearchUnavailable
    with pytest.raises(ResearchUnavailable):delegation.charge('alice',child['childId'],'too-many','calls',12)
    delegation.charge('alice',run['id'],'parent-read','calls',23)
    with pytest.raises(ResearchUnavailable):delegation.charge('alice',child['childId'],'another','calls',1)

def test_parent_cancellation_propagates(connected):
    db,coordinator,repo,run,_,_=connected;delegation=Delegation(db)
    child=delegation.create('alice',run['id'],ChildRequest(expectedRevision=run['revision'],kind='lab_analysis',assignment='Check values'),'child1')
    coordinator.command('alice',run['id'],Command(commandId='stop',action='cancel',expectedRevision=run['revision']))
    delegation.tick();assert repo.read('alice',child['childId'])['status']=='cancelled'
    assert delegation.list('alice',run['id'])['items'][0]['status']=='rejected'

def test_google_calendar_provider_id_etag_and_mail_mime(connected):
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('messages/send'):return httpx.Response(200,json={'id':'message1'})
        if request.method=='GET':return httpx.Response(200,json={'id':'event1','etag':'"v1"','extendedProperties':{'private':{'openlearnOperation':'op','openlearnAction':'hash'}}})
        return httpx.Response(200,json={'id':'event1','etag':'"v2"'})
    adapter=GoogleAdapter(GoogleConnections(connected[0],httpx.Client(transport=httpx.MockTransport(handler))))
    event={'calendarId':'primary','summary':'Study','description':'Practice','start':'2026-10-05T10:00:00-07:00','end':'2026-10-05T11:00:00-07:00','timeZone':'America/Los_Angeles','attendees':[],'sendUpdates':'none'}
    adapter.dispatch('alice','google','op',{'kind':'calendar_create','event':event,'actionHash':'hash'},[])
    created=json.loads(requests[-1].content);assert len(created['id'])==64 and created['extendedProperties']['private']['openlearnOperation']=='op'
    adapter.dispatch('alice','google','op',{'kind':'calendar_update','event':{**event,'eventId':'event1'},'baseEvent':{'etag':'"v1"'},'actionHash':'hash'},[])
    assert requests[-1].headers['if-match']=='"v1"'
    adapter.dispatch('alice','google','op',{'kind':'gmail_send','mail':{'to':['p@example.com'],'cc':[],'subject':'Hello','body':'Review me'},'actionHash':'hash'},[])
    message=message_from_bytes(base64.urlsafe_b64decode(json.loads(requests[-1].content)['raw']))
    assert message['Message-ID']=='<op@openlearn.invalid>' and message['To']=='p@example.com'
    assert adapter.reconcile('alice','google','op',{'kind':'calendar_create','event':event,'actionHash':'hash'})['verified']

def test_oauth_state_single_use_scopes_and_encrypted_export_boundary(connected,monkeypatch):
    db=connected[0];monkeypatch.setenv('OPENLEARN_GOOGLE_CLIENT_ID','client-test');monkeypatch.setenv('OPENLEARN_GOOGLE_CLIENT_SECRET','secret-test');monkeypatch.setenv('OPENLEARN_GOOGLE_REDIRECT_URI','http://127.0.0.1:8000/oauth/google/callback')
    def handler(request):
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'access_token':'test-token','refresh_token':'test-refresh','scope':'https://www.googleapis.com/auth/gmail.send','expires_in':3600})
        return httpx.Response(200,json={'sub':'account2','email':'new@example.com','email_verified':True})
    service=GoogleConnections(db,httpx.Client(transport=httpx.MockTransport(handler)))
    state=parse_qs(urlsplit(service.start('alice',['gmail_send'])['authorizationUrl']).query)['state'][0]
    result=service.callback(state,'test-code');assert result['connection']['email']=='new@example.com'
    with pytest.raises(HTTPException):service.callback(state,'test-code')
    with db.engine.connect() as conn:
        secret=conn.execute(text('SELECT secret FROM agent_app_connections WHERE id=:id'),{'id':result['connection']['id']}).scalar_one();assert 'test-refresh' not in secret
    from backend.app.identity_data import PRIVATE_TABLES
    from backend.app.identity_import import OMIT
    assert 'agent_app_connections' in PRIVATE_TABLES and 'agent_action_operations' in OMIT

def test_drive_intake_retries_reuse_material_and_preserve_provenance(connected,monkeypatch):
    from backend.app.agent_execution.connector_intake import ConnectorIntake
    monkeypatch.setenv('AI_TUTOR_MATERIAL_DIR','work/connected-material-'+str(time.time_ns()))
    class Drive:
        content=b'Lecture notes about speed'
        def download(self,*args):return {'name':'Lecture','mimeType':'text/plain'},self.content
    adapter=Drive();service=ConnectorIntake(connected[0],adapter)
    first=service.drive('alice','google','file1','import1');second=service.drive('alice','google','file1','import1')
    assert first['materialId']==second['materialId']
    assert first['provenance']['classification']=='untrusted_source'
    adapter.content=b'Changed notes'
    with pytest.raises(HTTPException):service.drive('alice','google','file1','import1')

def test_google_version_conflict_oversize_and_mail_reconciliation(connected):
    def handler(request):
        if request.method=='PATCH':return httpx.Response(412,json={})
        if request.url.path.endswith('/messages'):return httpx.Response(200,json={'messages':[{'id':'sent1'}]})
        if request.url.path.endswith('/sent1'):return httpx.Response(200,json={'payload':{'headers':[{'name':'Message-ID','value':'<op@openlearn.invalid>'},{'name':'X-OpenLearn-Action','value':'hash'}]}})
        return httpx.Response(200,content=b'x'*5_000_001)
    adapter=GoogleAdapter(GoogleConnections(connected[0],httpx.Client(transport=httpx.MockTransport(handler))))
    with pytest.raises(ConnectorError,match='provider_version_changed'):adapter.request('alice','google','calendar_write','PATCH','calendar/v3/test')
    with pytest.raises(ConnectorError,match='provider_result_too_large'):adapter.request('alice','google','drive_read','GET','drive/v3/test')
    assert adapter.reconcile('alice','google','op',{'kind':'gmail_send','actionHash':'hash'})['providerId']=='sent1'

def test_http_approval_identity_and_payload_validation(connected,monkeypatch):
    monkeypatch.setenv('AI_TUTOR_DEV_IDENTITY','true');db=connected[0];app=FastAPI();app.add_middleware(IdentityMiddleware,store_provider=lambda:db);app.include_router(build_connected_router(lambda:db));client=TestClient(app)
    response=client.post('/v1/assistant/tasks/'+connected[3]['id']+'/actions',headers={'X-Dev-Learner-Id':'alice','Idempotency-Key':'http1'},json={'connectionId':'google','expectedTaskRevision':connected[3]['revision'],'kind':'gmail_send','mail':{'to':['p@example.com'],'subject':'Hello','body':'Review'}})
    assert response.status_code==201,response.text;draft=response.json()
    assert client.get('/v1/assistant/tasks/'+connected[3]['id']+'/actions',headers={'X-Dev-Learner-Id':'bob'}).status_code==404
    assert client.post('/v1/assistant/approvals/'+draft['id']+'/decision',headers={'X-Dev-Learner-Id':'alice','Idempotency-Key':'d1'},json={'decision':'approve','expectedRevision':1,'actionHash':draft['actionHash']}).status_code==202
    assert client.post('/v1/assistant/tasks/'+connected[3]['id']+'/actions',headers={'X-Dev-Learner-Id':'alice','Idempotency-Key':'bad'},json={'connectionId':'google','expectedTaskRevision':1,'kind':'gmail_send','mail':{'to':['p@example.com\nBcc: victim@example.com'],'subject':'Bad','body':'No'}}).status_code==422
