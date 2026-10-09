"""Official Google APIs, bounded reads and provider-specific reconciliation."""
import base64
import hashlib
import json
import os
import secrets
import time
from contextlib import nullcontext
from email.message import EmailMessage
from urllib.parse import urlencode, quote
import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded, uid
from .repository import Repository
from .connected_contracts import ConnectorError

SCOPES={
 'drive_read':'https://www.googleapis.com/auth/drive.readonly',
 'gmail_read':'https://www.googleapis.com/auth/gmail.readonly',
 'gmail_send':'https://www.googleapis.com/auth/gmail.send',
 'calendar_read':'https://www.googleapis.com/auth/calendar.events.readonly',
 'calendar_write':'https://www.googleapis.com/auth/calendar.events',
}

def enabled():return os.getenv('OPENLEARN_CONNECTORS_ENABLED','false').lower()=='true'

def vault():
    try:return Fernet(os.environ['OPENLEARN_CONNECTOR_VAULT_KEY'].encode())
    except (KeyError,ValueError):raise ConnectorError('connector_vault_setup_required') from None

class GoogleConnections:
    def __init__(self,store,client=None):self.store=store;self.repo=Repository(store);self.client=client
    def row(self,conn,owner,identifier):
        assert_owner_active(conn,owner)
        row=conn.execute(text('SELECT * FROM agent_app_connections WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
        if not row:fail('not_found','Connection unavailable.',404)
        return dict(row)
    def public(self,row):return {'id':row['id'],'revision':row['revision'],'status':row['status'],**json.loads(row['payload'])}
    def list(self,owner):
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            return [self.public(row) for row in conn.execute(text('SELECT * FROM agent_app_connections WHERE owner_id=:owner ORDER BY created_at'),{'owner':owner}).mappings()]
    def _request(self,method,url,**kwargs):
        try:
            with (nullcontext(self.client) if self.client else httpx.Client(timeout=15,follow_redirects=False)) as client:
                with client.stream(method,url,**kwargs) as response:
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>5_000_000:raise ConnectorError('provider_result_too_large',method!='GET')
                    return httpx.Response(response.status_code,headers=response.headers,content=bytes(content),request=response.request)
        except httpx.HTTPError:raise ConnectorError('provider_unavailable',True) from None
    def start(self,owner,capabilities):
        if not enabled():raise ConnectorError('connectors_disabled')
        vault()
        client_id=os.getenv('OPENLEARN_GOOGLE_CLIENT_ID');redirect=os.getenv('OPENLEARN_GOOGLE_REDIRECT_URI')
        if not client_id or not redirect or not os.getenv('OPENLEARN_GOOGLE_CLIENT_SECRET'):raise ConnectorError('google_oauth_setup_required')
        if not redirect.startswith('https://') and not redirect.startswith(('http://127.0.0.1:','http://localhost:')):raise ConnectorError('invalid_oauth_redirect')
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.repo.transaction() as conn:
            assert_owner_active(conn,owner)
            conn.execute(text('INSERT INTO agent_app_oauth(id,owner_id,created_at,state_hash,expires_at,payload) VALUES(:id,:owner,:now,:hash,:expiry,:payload)'),{'id':uid('oauth'),'owner':owner,'now':time.time(),'hash':hashlib.sha256(state.encode()).hexdigest(),'expiry':time.time()+600,'payload':vault().encrypt(encoded({'verifier':verifier,'capabilities':sorted(set(capabilities)),'redirect':redirect}).encode()).decode()})
        return {'authorizationUrl':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':client_id,'redirect_uri':redirect,'response_type':'code','scope':' '.join(['openid','email']+[SCOPES[c] for c in sorted(set(capabilities))]),'state':state,'code_challenge':challenge,'code_challenge_method':'S256','access_type':'offline','prompt':'consent'})}
    def callback(self,state,code):
        if not enabled():raise ConnectorError('connectors_disabled')
        with self.repo.transaction() as conn:
            row=conn.execute(text('SELECT * FROM agent_app_oauth WHERE state_hash=:hash'),{'hash':hashlib.sha256(state.encode()).hexdigest()}).mappings().first()
            if not row or row['expires_at']<=time.time():fail('oauth_state_invalid','Sign in again.',409)
            assert_owner_active(conn,row['owner_id']);owner=row['owner_id']
            payload=json.loads(vault().decrypt(row['payload'].encode()))
            conn.execute(text('DELETE FROM agent_app_oauth WHERE id=:id'),{'id':row['id']})
        result=self._request('POST','https://oauth2.googleapis.com/token',data={'client_id':os.environ['OPENLEARN_GOOGLE_CLIENT_ID'],'client_secret':os.environ['OPENLEARN_GOOGLE_CLIENT_SECRET'],'code':code,'code_verifier':payload['verifier'],'redirect_uri':payload['redirect'],'grant_type':'authorization_code'})
        if result.status_code!=200:raise ConnectorError('oauth_exchange_failed')
        tokens=result.json();token=tokens.get('access_token')
        if not token:raise ConnectorError('oauth_exchange_failed')
        profile=self._request('GET','https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+token})
        if profile.status_code!=200:raise ConnectorError('oauth_account_unavailable')
        account=profile.json()
        if not account.get('email_verified') or not account.get('sub'):raise ConnectorError('oauth_account_unverified')
        granted=set(tokens.get('scope','').split())
        capabilities=[c for c in payload['capabilities'] if SCOPES[c] in granted]
        if not capabilities:raise ConnectorError('oauth_scope_missing')
        tokens['expires_at']=time.time()+int(tokens.get('expires_in',3600))
        identifier=uid('app');public={'provider':'google','accountId':account['sub'],'email':account['email'],'capabilities':capabilities,'scopes':sorted(granted),'tokenExpiresAt':tokens['expires_at']}
        with self.repo.transaction() as conn:
            assert_owner_active(conn,owner)
            conn.execute(text("INSERT INTO agent_app_connections(id,owner_id,created_at,revision,status,payload,secret) VALUES(:id,:owner,:now,1,'connected',:payload,:secret)"),{'id':identifier,'owner':owner,'now':time.time(),'payload':encoded(public),'secret':vault().encrypt(encoded(tokens).encode()).decode()})
        return {'connection':{'id':identifier,'revision':1,'status':'connected',**public},'message':'Connected. Return to Open Learn. Each external action still requires review.'}
    def disconnect(self,owner,identifier):
        with self.repo.transaction() as conn:
            self.row(conn,owner,identifier)
            conn.execute(text("UPDATE agent_app_connections SET status='revoked',revision=revision+1,secret='' WHERE id=:id AND owner_id=:owner"),{'id':identifier,'owner':owner})
            conn.execute(text("UPDATE agent_action_drafts SET status='invalidated' WHERE connection_id=:id AND owner_id=:owner AND status IN ('draft','approved')"),{'id':identifier,'owner':owner})
            # Results derived from this account are private artifacts too. Tombstone
            # them in the same transaction as revocation so the normal worker
            # cleanup removes their object-store copies and future downloads fail.
            for artifact in conn.execute(text("SELECT id,payload FROM agent_artifacts WHERE owner_id=:owner AND status IN ('prepared','published')"),{'owner':owner}).mappings():
                try:lineage=json.loads(artifact['payload']).get('lineage',{})
                except (TypeError,ValueError):lineage={}
                if isinstance(lineage,dict) and lineage.get('connectionId')==identifier:
                    conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE id=:id AND owner_id=:owner AND status IN ('prepared','published')"),{'id':artifact['id'],'owner':owner})
    def token(self,owner,identifier,capability):
        with self.store.engine.connect() as conn:row=self.row(conn,owner,identifier)
        metadata=json.loads(row['payload'])
        if row['status']!='connected' or capability not in metadata['capabilities']:raise ConnectorError('connection_scope_denied')
        try:tokens=json.loads(vault().decrypt(row['secret'].encode()))
        except (InvalidToken,ValueError):raise ConnectorError('connection_credentials_unavailable') from None
        if tokens.get('expires_at',0)<=time.time()+30:
            if not tokens.get('refresh_token'):raise ConnectorError('connection_reauthentication_required')
            result=self._request('POST','https://oauth2.googleapis.com/token',data={'client_id':os.environ['OPENLEARN_GOOGLE_CLIENT_ID'],'client_secret':os.environ['OPENLEARN_GOOGLE_CLIENT_SECRET'],'refresh_token':tokens['refresh_token'],'grant_type':'refresh_token'})
            if result.status_code!=200:raise ConnectorError('connection_reauthentication_required')
            update=result.json();tokens.update(update);tokens['expires_at']=time.time()+int(update.get('expires_in',3600))
            with self.repo.transaction() as conn:
                fresh=self.row(conn,owner,identifier)
                if fresh['revision']!=row['revision'] or fresh['status']!='connected':raise ConnectorError('connection_revoked')
                metadata['tokenExpiresAt']=tokens['expires_at']
                conn.execute(text('UPDATE agent_app_connections SET secret=:secret,payload=:payload WHERE id=:id'),{'id':identifier,'secret':vault().encrypt(encoded(tokens).encode()).decode(),'payload':encoded(metadata)})
        return tokens['access_token']

class GoogleAdapter:
    is_test_adapter=False
    def __init__(self,connections):self.connections=connections
    def request(self,owner,connection,capability,method,path,**kwargs):
        token=self.connections.token(owner,connection,capability)
        response=self.connections._request(method,'https://www.googleapis.com/'+path,headers={'Authorization':'Bearer '+token,**kwargs.pop('headers',{})},**kwargs)
        if response.status_code in {401,403}:raise ConnectorError('provider_permission_denied')
        if response.status_code==412:raise ConnectorError('provider_version_changed')
        if response.status_code==404:raise ConnectorError('provider_not_found')
        if response.status_code>=500 or response.status_code==429:raise ConnectorError('provider_unavailable',method!='GET')
        if response.status_code>=400:raise ConnectorError('provider_rejected')
        if len(response.content)>5_000_000:raise ConnectorError('provider_result_too_large',method!='GET')
        return response
    def event(self,owner,connection,calendar,event):return self.request(owner,connection,'calendar_write','GET',f'calendar/v3/calendars/{quote(calendar,safe="")}/events/{quote(event,safe="")}').json()
    def dispatch(self,owner,connection,operation,payload,attachments):
        if payload['kind']=='gmail_send':
            mail=payload['mail'];message=EmailMessage();message['To']=', '.join(mail['to']);message['Subject']=mail['subject']
            message['Message-ID']=f'<{operation}@openlearn.invalid>';message['X-OpenLearn-Action']=payload['actionHash'];message.set_content(mail['body'])
            if mail['cc']:message['Cc']=', '.join(mail['cc'])
            for record,content in attachments:
                major,minor=record['mediaType'].split('/',1);message.add_attachment(content,maintype=major,subtype=minor,filename=record['name'])
            raw=base64.urlsafe_b64encode(message.as_bytes()).decode()
            result=self.request(owner,connection,'gmail_send','POST','gmail/v1/users/me/messages/send',json={'raw':raw}).json()
            if not result.get('id'):raise ConnectorError('provider_receipt_missing',True)
            return {'providerId':result['id'],'verified':True}
        event=payload['event'];path=f'calendar/v3/calendars/{quote(event["calendarId"],safe="")}/events'
        body={key:event[key] for key in ['summary','description']};body.update(start={'dateTime':event['start'],'timeZone':event['timeZone']},end={'dateTime':event['end'],'timeZone':event['timeZone']},attendees=[{'email':address} for address in event['attendees']],extendedProperties={'private':{'openlearnOperation':operation,'openlearnAction':payload['actionHash']}})
        if payload['kind']=='calendar_create':
            body['id']=hashlib.sha256(operation.encode()).hexdigest();result=self.request(owner,connection,'calendar_write','POST',path,json=body,params={'sendUpdates':event['sendUpdates']}).json()
        else:result=self.request(owner,connection,'calendar_write','PATCH',path+'/'+quote(event['eventId'],safe=''),json=body,headers={'If-Match':payload['baseEvent']['etag']},params={'sendUpdates':event['sendUpdates']}).json()
        if not result.get('id'):raise ConnectorError('provider_receipt_missing',True)
        return {'providerId':result['id'],'etag':result.get('etag'),'verified':True}
    def reconcile(self,owner,connection,operation,payload):
        if payload['kind']!='gmail_send':
            event=payload['event'];identifier=event['eventId'] if payload['kind']=='calendar_update' else hashlib.sha256(operation.encode()).hexdigest()
            try:result=self.event(owner,connection,event['calendarId'],identifier)
            except ConnectorError as exc:
                if exc.code=='provider_not_found':return None
                raise
            marker=result.get('extendedProperties',{}).get('private',{})
            if marker.get('openlearnOperation')==operation and marker.get('openlearnAction')==payload['actionHash']:return {'providerId':result['id'],'verified':True,'reconciled':True}
            return None
        try:
            result=self.request(owner,connection,'gmail_read','GET','gmail/v1/users/me/messages',params={'q':f'in:sent rfc822msgid:{operation}@openlearn.invalid','maxResults':5}).json()
            for item in result.get('messages',[]):
                detail=self.request(owner,connection,'gmail_read','GET','gmail/v1/users/me/messages/'+quote(item['id'],safe=''),params={'format':'metadata','metadataHeaders':['Message-ID','X-OpenLearn-Action']}).json()
                headers={h['name'].lower():h['value'] for h in detail.get('payload',{}).get('headers',[])}
                if headers.get('x-openlearn-action')==payload['actionHash'] and headers.get('message-id')==f'<{operation}@openlearn.invalid>':return {'providerId':item['id'],'verified':True,'reconciled':True}
        except ConnectorError as exc:
            if exc.code=='connection_scope_denied':return None
            raise
        return None
    def read(self,owner,connection,kind,identifier=None,page=None,*,calendar_id=None,time_min=None,time_max=None):
        if kind=='drive':
            result=self.request(owner,connection,'drive_read','GET','drive/v3/files',params={'pageSize':20,'fields':'files(id,name,mimeType,modifiedTime,size),nextPageToken','pageToken':page or ''}).json()
        elif kind=='gmail':
            if identifier:result=self.request(owner,connection,'gmail_read','GET','gmail/v1/users/me/messages/'+quote(identifier,safe=''),params={'format':'full'}).json()
            else:result=self.request(owner,connection,'gmail_read','GET','gmail/v1/users/me/messages',params={'maxResults':20,'pageToken':page or ''}).json()
        elif kind=='calendar':
            # Require a user-selected calendar and explicit time range so a
            # source read cannot silently become an unbounded calendar export.
            from datetime import datetime
            if not calendar_id or len(calendar_id)>300:
                raise ConnectorError('calendar_selection_required')
            try:
                start=datetime.fromisoformat((time_min or '').replace('Z','+00:00'))
                end=datetime.fromisoformat((time_max or '').replace('Z','+00:00'))
                if start.utcoffset() is None or end.utcoffset() is None or end<=start:
                    raise ValueError
            except (TypeError,ValueError):
                raise ConnectorError('calendar_range_invalid') from None
            result=self.request(owner,connection,'calendar_read','GET',
                'calendar/v3/calendars/'+quote(calendar_id,safe='')+'/events',
                params={'maxResults':20,'singleEvents':'true','orderBy':'startTime',
                        'timeMin':time_min,'timeMax':time_max,'pageToken':page or ''}).json()
        else:raise ConnectorError('unknown_read_capability')
        return {'data':result,'classification':'untrusted_source','coverage':'bounded_page','complete':not bool(result.get('nextPageToken')),'nextPageToken':result.get('nextPageToken')}
    def download(self,owner,connection,identifier):
        path='drive/v3/files/'+quote(identifier,safe='');metadata=self.request(owner,connection,'drive_read','GET',path,params={'fields':'id,name,mimeType,size'}).json()
        media=metadata.get('mimeType')
        if media not in {'application/pdf','text/plain','text/markdown'} or int(metadata.get('size',0))>5_000_000:raise ConnectorError('unsupported_drive_material')
        content=self.request(owner,connection,'drive_read','GET',path,params={'alt':'media'}).content
        return metadata,content
