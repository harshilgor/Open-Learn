"""Review exact actions; persist uncertain effects instead of retrying writes."""
import json
import os
import time
from sqlalchemy import text
from ..identity import assert_owner_active, fail, hosted
from ..workflow_store import encoded, uid
from .repository import Repository, digest
from .artifacts import Artifacts
from .google_connector import GoogleConnections, GoogleAdapter, enabled
from .connected_contracts import ConnectorError

class ConnectedActions:
    def __init__(self,store,adapter=None):
        self.store=store;self.repo=Repository(store);self.connections=GoogleConnections(store);self.adapter=adapter or GoogleAdapter(self.connections);self.artifacts=Artifacts(store)
    def row(self,conn,owner,identifier):
        assert_owner_active(conn,owner)
        args={'id':identifier,'owner':owner}
        task=conn.execute(text('SELECT run_id FROM agent_action_drafts WHERE id=:id AND owner_id=:owner'),args).scalar_one_or_none()
        if not task:fail('not_found','Action unavailable.',404)
        self.repo.run(conn,owner,task)
        suffix=' FOR UPDATE' if conn.dialect.name=='postgresql' else ''
        row=conn.execute(text('SELECT * FROM agent_action_drafts WHERE id=:id AND owner_id=:owner'+suffix),args).mappings().first()
        if not row:fail('not_found','Action unavailable.',404)
        return dict(row)
    def public(self,conn,row):
        operation=conn.execute(text('SELECT id,status,payload FROM agent_action_operations WHERE draft_id=:id AND owner_id=:owner'),{'id':row['id'],'owner':row['owner_id']}).mappings().first()
        return {'id':row['id'],'taskId':row['run_id'],'revision':row['revision'],'status':row['status'],'actionHash':row['action_hash'],'expiresAt':row['expires_at'],**json.loads(row['payload']),'operation':{'id':operation['id'],'status':operation['status'],**json.loads(operation['payload'])} if operation else None}
    def list(self,owner,task):
        with self.repo.transaction() as conn:
            self.repo.run(conn,owner,task)
            return [self.public(conn,row) for row in conn.execute(text('SELECT * FROM agent_action_drafts WHERE owner_id=:owner AND run_id=:run ORDER BY created_at'),{'owner':owner,'run':task}).mappings()]
    def _connection(self,conn,owner,identifier,kind):
        row=self.connections.row(conn,owner,identifier);metadata=json.loads(row['payload']);capability='gmail_send' if kind=='gmail_send' else 'calendar_write'
        if row['status']!='connected' or capability not in metadata['capabilities']:raise ConnectorError('connection_scope_denied')
        return row,metadata
    def _validate(self,conn,row,*,approved=False):
        run=self.repo.run(conn,row['owner_id'],row['run_id'])
        if conn.execute(text('SELECT 1 FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':run['id'],'owner':row['owner_id']}).first():raise ConnectorError('child_write_denied')
        if run['status'] in {'cancelled','failed','paused','waiting'} or run['desired_input_revision']!=row['input_revision']:raise ConnectorError('task_changed_or_inactive')
        if row['expires_at']<=time.time():raise ConnectorError('approval_expired')
        payload=json.loads(row['payload']);connection,_=self._connection(conn,row['owner_id'],row['connection_id'],payload['kind'])
        if connection['revision']!=row['connection_revision']:raise ConnectorError('connection_changed')
        if digest({key:value for key,value in payload.items() if key!='actionHash'})!=row['action_hash']:raise ConnectorError('action_integrity_failed')
        if approved and row['status']!='approved':raise ConnectorError('approval_required')
        return run,payload
    def _attachments(self,owner,payload):
        values=[];size=0
        for saved in payload.get('attachments',[]):
            record,content=self.artifacts.download(owner,saved['id'])
            if record['sha256']!=saved['sha256'] or record['taskId']!=payload['taskId']:raise ConnectorError('attachment_changed')
            size+=len(content)
            if size>3_000_000:raise ConnectorError('attachments_too_large')
            values.append((record,content))
        return values
    def draft(self,owner,task,body,key):
        if not enabled():raise ConnectorError('connectors_disabled')
        if not key or len(key)>160:fail('invalid_input','Provide a stable action key.',422)
        identifier='action_'+digest([owner,task,key])[:32];request_hash=digest(body.model_dump(mode='json'))
        with self.repo.transaction() as conn:
            run=self.repo.run(conn,owner,task)
            if conn.execute(text('SELECT 1 FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':task,'owner':owner}).first():raise ConnectorError('child_write_denied')
            existing=conn.execute(text('SELECT * FROM agent_action_drafts WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if existing:
                if json.loads(existing['payload'])['requestHash']!=request_hash:fail('idempotency_conflict','Action key already has different content.',409)
                return self.public(conn,existing)
            if run['revision']!=body.expectedTaskRevision:fail('revision_conflict','Refresh the task before drafting.',409)
            if run['status'] not in {'running','queued','completed','completed_partial'}:raise ConnectorError('task_inactive')
            connection,metadata=self._connection(conn,owner,body.connectionId,body.kind)
            revision=connection['revision'];input_revision=run['desired_input_revision']
        payload=body.model_dump(mode='json');payload.update(taskId=task,account=metadata['email'],accountId=metadata['accountId'],requestHash=request_hash,attachments=[])
        if body.mail:
            for artifact_id in body.mail.attachmentIds:
                record,content=self.artifacts.download(owner,artifact_id)
                if record['taskId']!=task:raise ConnectorError('attachment_scope_denied')
                payload['attachments'].append({'id':artifact_id,'name':record['name'],'mediaType':record['mediaType'],'size':len(content),'sha256':record['sha256']})
            self._attachments(owner,payload)
        if body.kind=='calendar_update':
            current=self.adapter.event(owner,body.connectionId,body.event.calendarId,body.event.eventId)
            if not current.get('etag'):raise ConnectorError('event_version_unavailable')
            payload['baseEvent']={key:current.get(key) for key in ['id','etag','summary','description','start','end','attendees']}
        action_hash=digest(payload);payload['actionHash']=action_hash
        with self.repo.transaction() as conn:
            fresh=self.repo.run(conn,owner,task);current,_=self._connection(conn,owner,body.connectionId,body.kind)
            if fresh['revision']!=body.expectedTaskRevision or current['revision']!=revision:fail('revision_conflict','Task or connection changed; regenerate review.',409)
            conn.execute(text("INSERT INTO agent_action_drafts(id,owner_id,created_at,run_id,input_revision,connection_id,connection_revision,revision,status,action_hash,expires_at,payload) VALUES(:id,:owner,:now,:run,:input,:connection,:connection_revision,1,'draft',:hash,:expiry,:payload) ON CONFLICT(id) DO NOTHING"),{'id':identifier,'owner':owner,'now':time.time(),'run':task,'input':input_revision,'connection':body.connectionId,'connection_revision':revision,'hash':action_hash,'expiry':time.time()+900,'payload':encoded(payload)})
            row=self.row(conn,owner,identifier)
            if json.loads(row['payload'])['requestHash']!=request_hash:fail('idempotency_conflict','Action key content conflict.',409)
            self.repo.activity(conn,fresh,'approval:'+identifier,'approval.required',actionId=identifier,text='Review the exact connected-app action before execution.')
            return self.public(conn,row)
    def decide(self,owner,identifier,body,key):
        if not key or len(key)>160:fail('invalid_input','Provide a stable decision key.',422)
        decision_id='decision_'+digest([owner,key])[:32];hash_value=digest([identifier,body.model_dump()])
        with self.repo.transaction() as conn:
            existing=conn.execute(text('SELECT * FROM agent_action_decisions WHERE id=:id AND owner_id=:owner'),{'id':decision_id,'owner':owner}).mappings().first()
            if existing:
                if existing['request_hash']!=hash_value:fail('idempotency_conflict','Decision key content conflict.',409)
                return json.loads(existing['payload'])
            row=self.row(conn,owner,identifier)
            if row['revision']!=body.expectedRevision or row['action_hash']!=body.actionHash:fail('revision_conflict','Review the current exact action.',409)
            if row['status']!='draft':fail('invalid_state','This review has already been decided.',409)
            run,_=self._validate(conn,row)
            if body.decision=='approve' and not enabled():raise ConnectorError('connectors_disabled')
            status='approved' if body.decision=='approve' else 'rejected'
            conn.execute(text('UPDATE agent_action_drafts SET status=:status,revision=revision+1 WHERE id=:id'),{'id':identifier,'status':status})
            operation=uid('write') if status=='approved' else None
            if operation:conn.execute(text("INSERT INTO agent_action_operations(id,owner_id,created_at,draft_id,status,payload,updated_at) VALUES(:id,:owner,:now,:draft,'queued','{}',:now)"),{'id':operation,'owner':owner,'now':time.time(),'draft':identifier})
            receipt={'actionId':identifier,'decision':body.decision,'revision':row['revision']+1,'operationId':operation}
            conn.execute(text('INSERT INTO agent_action_decisions(id,owner_id,created_at,draft_id,request_hash,payload) VALUES(:id,:owner,:now,:draft,:hash,:payload)'),{'id':decision_id,'owner':owner,'now':time.time(),'draft':identifier,'hash':hash_value,'payload':encoded(receipt)})
            self.repo.activity(conn,run,'decision:'+identifier,'approval.decided',actionId=identifier,text='Action '+status+'.')
            return receipt
    def _settle(self,operation,status,receipt):
        with self.repo.transaction() as conn:
            assert_owner_active(conn,operation['owner_id'])
            row=self.row(conn,operation['owner_id'],operation['draft_id'])
            conn.execute(text('UPDATE agent_action_operations SET status=:status,payload=:payload,updated_at=:now WHERE id=:id'),{'id':operation['id'],'status':status,'payload':encoded(receipt),'now':time.time()})
            conn.execute(text('UPDATE agent_action_drafts SET status=:status WHERE id=:id'),{'id':row['id'],'status':status})
            run=self.repo.run(conn,row['owner_id'],row['run_id'])
            self.repo.activity(conn,run,'action-result:'+operation['id']+':'+status,'action.'+status,actionId=row['id'],text='Connected action '+status.replace('_',' ')+'.',receipt=receipt)
    def execute(self,operation_id,after_dispatch=None):
        if hosted() and getattr(self.adapter,'is_test_adapter',False):raise ConnectorError('test_adapter_denied')
        operation=None
        try:
            with self.repo.transaction() as conn:
                operation=conn.execute(text('SELECT * FROM agent_action_operations WHERE id=:id'),{'id':operation_id}).mappings().first()
                if not operation:return
                operation=dict(operation)
                if operation['status'] not in {'queued','outcome_unknown','dispatching'}:return
                if operation['status']=='queued' and not enabled():return
                if operation['status']=='dispatching' and operation['updated_at']>time.time()-90:return
                draft=self.row(conn,operation['owner_id'],operation['draft_id'])
                if operation['status']=='queued':
                    _,payload=self._validate(conn,draft,approved=True)
                    claimed=conn.execute(text("UPDATE agent_action_operations SET status='dispatching',updated_at=:now WHERE id=:id AND status='queued'"),{'id':operation_id,'now':time.time()})
                    if claimed.rowcount!=1:return
                else:payload=json.loads(draft['payload'])
            if operation['status']!='queued':
                receipt=self.adapter.reconcile(operation['owner_id'],draft['connection_id'],operation_id,payload)
                if receipt:self._settle(operation,'succeeded',receipt)
                elif operation['status']=='dispatching':self._settle(operation,'outcome_unknown',{'reasonCode':'provider_outcome_unconfirmed','automaticResend':False})
                return
            attachments=self._attachments(operation['owner_id'],payload)
            # Recheck revocation/input immediately before network dispatch. The
            # durable dispatching marker means a crash is reconciled, never replayed.
            with self.repo.transaction() as conn:self._validate(conn,self.row(conn,operation['owner_id'],draft['id']),approved=True)
            receipt=self.adapter.dispatch(operation['owner_id'],draft['connection_id'],operation_id,payload,attachments)
            if after_dispatch:after_dispatch(operation,receipt)
            self._settle(operation,'succeeded',receipt)
        except ConnectorError as exc:
            if operation:self._settle(operation,'outcome_unknown' if exc.uncertain or operation['status']!='queued' else 'failed',{'reasonCode':exc.code,'automaticResend':False})
        except Exception:
            if operation:self._settle(operation,'outcome_unknown',{'reasonCode':'operation_interrupted','automaticResend':False})
    def tick(self,limit=5):
        with self.repo.transaction() as conn:conn.execute(text('DELETE FROM agent_app_oauth WHERE expires_at<:now'),{'now':time.time()})
        with self.store.engine.connect() as conn:
            ids=conn.execute(text("SELECT id FROM agent_action_operations WHERE status='queued' OR (status='dispatching' AND updated_at<:stale) ORDER BY created_at LIMIT :limit"),{'stale':time.time()-90,'limit':limit}).scalars().all()
        for identifier in ids:self.execute(identifier)
        return len(ids)
    def reconcile(self,owner,action_id):
        with self.repo.transaction() as conn:
            row=self.row(conn,owner,action_id)
            operation=conn.execute(text('SELECT id,status FROM agent_action_operations WHERE draft_id=:draft AND owner_id=:owner'),{'draft':action_id,'owner':owner}).first()
            if not operation or operation[1]!='outcome_unknown':fail('invalid_state','Only uncertain actions need reconciliation.',409)
        self.execute(operation[0])
        return self.list(owner,row['run_id'])
