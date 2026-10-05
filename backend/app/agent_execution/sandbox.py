"""Lazy, recoverable Daytona execution and durable verified object transfer."""
import hashlib
import csv
import inspect
import io
import json
import math
import os
import time
import zipfile
from xml.etree import ElementTree as ET
from sqlalchemy import text
from fastapi import HTTPException
from ..browser_assistant.evidence import evidence_objects
from ..workflow_store import encoded
from .repository import Repository, digest
from .sandbox_config import SandboxPolicy
from .daytona_adapter import DaytonaAdapter, SandboxError
from . import tools

OUTPUTS={'analysis.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'speeds.png':'image/png','analysis.csv':'text/csv','report.json':'application/json'}


def runner_source():
    # Trusted application code executes only in the isolated runtime. User text
    # lives in task.json and is never interpolated into Python or shell code.
    return (inspect.getsource(tools)+'''
if __name__ == '__main__':
    import pathlib, json
    task=json.loads(pathlib.Path('/workspace/uploads/task.json').read_text())
    result=analyze(task)
    directory=pathlib.Path('/workspace/outputs')
    for output in result['outputs']:
        (directory/output['name']).write_bytes(output['content'])
    report={'summary':result['summary'],'completion':result['completion']}
    (directory/'report.json').write_text(json.dumps(report,sort_keys=True))
''').encode()


def verify(task, outputs):
    """Independent numeric and format checks; remote assertions are not trust."""
    expected=tools.analyze(task)
    expected_rows=expected['completion']['checks'][0]['rows']
    if set(outputs)!=set(OUTPUTS):raise SandboxError('sandbox_output_manifest_invalid')
    # Preflight expansion before any parser/decompression of remote files.
    with zipfile.ZipFile(io.BytesIO(outputs['analysis.xlsx'])) as archive:
        if len(archive.infolist())>12 or sum(i.file_size for i in archive.infolist())>2_000_000:raise SandboxError('sandbox_workbook_invalid')
    # Exact PNG bytes prevent decompression bombs before the generic parser.
    if outputs['speeds.png']!=expected['outputs'][1]['content']:raise SandboxError('sandbox_chart_validation_failed')
    for name,content in outputs.items():tools.validate_output({'name':name,'mediaType':OUTPUTS[name],'content':content})
    parsed=list(csv.DictReader(io.StringIO(outputs['analysis.csv'].decode())))
    retained=[r for r in tools.parse_csv(task['csvText']) if r['trial'] not in task['constraints']['excludedTrials']]
    if len(parsed)!=len(retained):raise SandboxError('sandbox_numeric_validation_failed')
    for actual,source in zip(parsed,retained):
        if int(actual['trial'])!=source['trial'] or not math.isclose(float(actual['speed']),source['distance']/source['time'],rel_tol=1e-12,abs_tol=1e-12):raise SandboxError('sandbox_numeric_validation_failed')
    if outputs['analysis.csv']!=expected['outputs'][2]['content']:raise SandboxError('sandbox_numeric_validation_failed')
    # The trusted generator is deterministic. Matching PNG verifies its actual
    # axis labels, rows and bars, rather than trusting a claimed manifest.
    if outputs['speeds.png']!=expected['outputs'][1]['content']:raise SandboxError('sandbox_chart_validation_failed')
    with zipfile.ZipFile(io.BytesIO(outputs['analysis.xlsx'])) as book:
        if len(book.infolist())>12 or sum(i.file_size for i in book.infolist())>2_000_000:raise SandboxError('sandbox_workbook_invalid')
        if any(i.filename.startswith('/') or '..' in i.filename.split('/') or i.filename.endswith('.bin') for i in book.infolist()):raise SandboxError('sandbox_workbook_invalid')
        sheet=book.read('xl/worksheets/sheet1.xml')
        if b'<!DOCTYPE' in sheet or b'<!ENTITY' in sheet:raise SandboxError('sandbox_workbook_invalid')
        root=ET.fromstring(sheet);ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rows=root.findall('s:sheetData/s:row',ns)
        if len(rows)!=len(expected_rows)+1:raise SandboxError('sandbox_numeric_validation_failed')
        if sheet!=zip_sheet(expected['outputs'][0]['content']):raise SandboxError('sandbox_workbook_validation_failed')
    report=json.loads(outputs['report.json'])
    if report.get('summary')!=expected['summary'] or report.get('completion')!=expected['completion']:raise SandboxError('sandbox_report_validation_failed')
    expected['outputs'].append({'name':'report.json','mediaType':'application/json','content':outputs['report.json'],'lineage':expected['outputs'][0]['lineage']})
    return expected


def zip_sheet(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:return archive.read('xl/worksheets/sheet1.xml')


class SandboxService:
    def __init__(self,store,adapter=None,policy=None):
        self.store=store;self.repo=Repository(store);self.objects=evidence_objects(store)
        self.policy=policy or SandboxPolicy.configured();self.adapter=adapter

    def provider(self):
        if self.adapter is None:self.adapter=DaytonaAdapter()
        return self.adapter

    def _reserve(self,conn,owner):
        day=int(time.time()//86400)
        # Hash owner identity in compact non-content spending receipts. The
        # global receipt cannot race between different account/session locks.
        for scope,limit in [('global',self.policy.max_global_creations_day),('owner:'+digest(owner),self.policy.max_owner_creations_day)]:
            conn.execute(text('INSERT INTO agent_sandbox_budgets(scope,day,reserved_creations) VALUES(:scope,:day,0) ON CONFLICT(scope,day) DO NOTHING'),{'scope':scope,'day':day})
            changed=conn.execute(text('UPDATE agent_sandbox_budgets SET reserved_creations=reserved_creations+1 WHERE scope=:scope AND day=:day AND reserved_creations<:limit'),{'scope':scope,'day':day,'limit':limit})
            if changed.rowcount!=1:raise SandboxError('sandbox_daily_budget_exhausted')

    def _check(self,task,current):
        if current:current()
        if getattr(self.adapter,'is_test_adapter',False) and os.getenv('AI_TUTOR_ENV','development').lower() in {'production','deployed'}:raise SandboxError('sandbox_test_adapter_denied')
        fresh=self.repo.read(task['owner_id'],task['id'])
        from .sandbox_inputs import validate_material
        validate_material(self.store,task['owner_id'],fresh)
        if fresh.get('inputSourceDeleted'):raise SandboxError('sandbox_source_deleted')
        from ..material_service import MaterialService
        session=MaterialService(self.store).session(task['owner_id'],task['sessionId'])
        if session.active_quiz_id or getattr(session,'active_review_id',None):raise SandboxError('sandbox_assessment_active')
        if fresh['desired_input_revision']!=task['desired_input_revision'] or fresh['status'] in {'cancelled','paused','failed'}:
            raise HTTPException(409,{'code':'revision_conflict','message':'Sandbox input changed.'})

    def _save(self,lease,**changes):
        # Lease ownership is provider lifecycle state; cancelled task cleanup
        # must remain possible without reauthorizing its learner account.
        with self.store.transaction() as conn:
            row=conn.execute(text('SELECT * FROM agent_sandbox_leases WHERE id=:id'),{'id':lease['id']}).mappings().first()
            if not row:raise SandboxError('sandbox_lease_deleted')
            data=dict(row);payload=json.loads(data['payload']);payload.update(changes.pop('payload',{}))
            if data['status']=='deleted' and changes.get('status') not in {None,'deleted','cleanup_pending'}:
                changes['status']='cleanup_pending'
            data.update(changes)
            conn.execute(text('UPDATE agent_sandbox_leases SET status=:status,provider_id=:provider,payload=:payload WHERE id=:id'),
                {'id':data['id'],'status':data['status'],'provider':data['provider_id'],'payload':encoded(payload)})
        return {**data,'payload':payload}

    def acquire(self,task,current=None):
        self._check(task,current)
        if not self.policy.enabled:raise SandboxError('sandbox_disabled')
        key='ol-'+digest([task['owner_id'],task['id'],task['desired_input_revision']])[:40]
        new=False
        with self.repo.transaction() as conn:
            self.repo.run(conn,task['owner_id'],task['id'])
            row=conn.execute(text('SELECT * FROM agent_sandbox_leases WHERE owner_id=:owner AND run_id=:run AND input_revision=:revision'),{'owner':task['owner_id'],'run':task['id'],'revision':task['desired_input_revision']}).mappings().first()
            if not row:
                self._reserve(conn,task['owner_id'])
                count=conn.execute(text("SELECT count(*) FROM agent_sandbox_leases WHERE owner_id=:owner AND status NOT IN ('released','ready','deleted')"),{'owner':task['owner_id']}).scalar_one()
                if count>=self.policy.max_owner_resources:raise SandboxError('sandbox_resource_limit',True)
                now=time.time();row={'id':key,'owner_id':task['owner_id'],'run_id':task['id'],'input_revision':task['desired_input_revision'],
                    'creation_key':key,'provider_id':None,'status':'creating','payload':'{}','created_at':now,'expires_at':now+self.policy.lifetime_seconds}
                conn.execute(text('INSERT INTO agent_sandbox_leases(id,owner_id,run_id,input_revision,creation_key,provider_id,status,payload,created_at,expires_at) VALUES(:id,:owner_id,:run_id,:input_revision,:creation_key,:provider_id,:status,:payload,:created_at,:expires_at)'),row);new=True
        lease={**dict(row),'payload':json.loads(row['payload'])}
        key=lease['creation_key']
        if lease['payload'].get('outputsReady'):return lease
        if lease['expires_at']<=time.time():raise SandboxError('sandbox_lease_expired')
        if lease['status']=='released':
            # Only a confirmed deletion can start a fresh compute generation.
            generation=lease['payload'].get('generation',1)+1
            if generation>3:raise SandboxError('sandbox_restart_limit')
            key=lease['id']+'-'+str(generation)
            with self.repo.transaction() as conn:
                self.repo.run(conn,task['owner_id'],task['id'])
                changed=conn.execute(text("UPDATE agent_sandbox_leases SET creation_key=:key,status='creating',provider_id=NULL,payload=:payload WHERE id=:id AND status='released'"),{'id':lease['id'],'key':key,'payload':encoded({'generation':generation})})
                new=changed.rowcount==1
                if new:self._reserve(conn,task['owner_id'])
                row=conn.execute(text('SELECT * FROM agent_sandbox_leases WHERE id=:id'),{'id':lease['id']}).mappings().one()
            lease={**dict(row),'payload':json.loads(row['payload'])};key=lease['creation_key']
        if lease['status']=='creating':
            if new:
                identifier=self.provider().create(key,self.policy)
            else:
                identifier=self.provider().reconcile(key)
                if not identifier:raise SandboxError('sandbox_creation_unknown',True)
            lease=self._save(lease,status='active',provider_id=identifier)
        if lease['status'] not in {'active','executing','collected'}:raise SandboxError('sandbox_lease_unavailable')
        self._check(task,current)
        return lease

    def prepare(self,task,current=None):
        try:return self._prepare(task,current)
        except BaseException:
            # A stale upload can finish after cleanup deleted its object.
            with self.store.engine.begin() as conn:
                conn.execute(text("UPDATE agent_sandbox_leases SET status='cleanup_pending',expires_at=0 WHERE owner_id=:owner AND run_id=:run AND input_revision=:revision AND status='deleted'"),{'owner':task['owner_id'],'run':task['id'],'revision':task['desired_input_revision']})
                exists=conn.execute(text('SELECT id FROM agent_sandbox_leases WHERE owner_id=:owner AND run_id=:run AND input_revision=:revision'),{'owner':task['owner_id'],'run':task['id'],'revision':task['desired_input_revision']}).first()
                if not exists:
                    # Account erasure can remove the lease during an upload.
                    # Renew cleanup obligations after that upload has returned.
                    from uuid import uuid4
                    lease_id='ol-'+digest([task['owner_id'],task['id'],task['desired_input_revision']])[:40]
                    for name in OUTPUTS:
                        conn.execute(text("INSERT INTO identity_object_cleanup(id,owner_id,kind,recording_id,object_key) VALUES(:id,:owner,'assistant',NULL,:key)"),{'id':uuid4().hex,'owner':task['owner_id'],'key':'sandbox-'+digest([lease_id,name])[:48]})
            raise

    def _prepare(self,task,current=None):
        lease=self.acquire(task,current)
        if lease['payload'].get('outputsReady'):
            data={name:self.objects.read(task['owner_id'],item['key']) for name,item in lease['payload']['outputs'].items()}
            for name,item in lease['payload']['outputs'].items():
                if hashlib.sha256(data[name]).hexdigest()!=item['sha256']:raise SandboxError('sandbox_object_integrity_failed')
        else:
            self._check(task,current)
            remote_task={key:task[key] for key in ('csvText','constraints','inputHash','desired_input_revision')}
            inputs=encoded(remote_task).encode();code=runner_source()
            lease=self._save(lease,payload={'workspaceManifest':{'inputHash':hashlib.sha256(inputs).hexdigest(),'codeHash':hashlib.sha256(code).hexdigest(),
                'inputRevision':task['desired_input_revision'],'inputMaterial':task.get('inputMaterial'),'snapshot':self.policy.snapshot,
                'runtimeVersion':getattr(self.provider(),'runtime_version','test-adapter'),'network':'blocked','timeoutSeconds':self.policy.timeout_seconds}})
            self.provider().stage(lease['provider_id'],{'/workspace/uploads/task.json':inputs,'/workspace/working/runner.py':code})
            lease=self._save(lease,status='executing')
            started=time.monotonic()
            self.provider().execute(lease['provider_id'],self.policy.timeout_seconds)
            lease=self._save(lease,payload={'executionReceipt':{'exitCode':0,'elapsedSeconds':round(time.monotonic()-started,3),'codeHash':hashlib.sha256(code).hexdigest()}})
            self._check(task,current)
            data={name:self.provider().download(lease['provider_id'],'/workspace/outputs/'+name,self.policy.max_output_bytes) for name in OUTPUTS}
            if sum(len(v) for v in data.values())>self.policy.max_output_bytes:raise SandboxError('sandbox_output_limit')
            verify(task,data)
            manifest={name:{'key':'sandbox-'+digest([lease['id'],name])[:48],'sha256':hashlib.sha256(content).hexdigest()} for name,content in data.items()}
            # Reserve keys before object writes so erasure and crash cleanup
            # can always enumerate partially uploaded output objects.
            lease=self._save(lease,status='collected',payload={'outputs':manifest,'outputsReady':False})
            for name,item in manifest.items():self.objects.put(task['owner_id'],item['key'],data[name])
            lease=self._save(lease,status='collected',payload={'outputsReady':True})
        self._check(task,current)
        result=verify(task,data)
        for output in result['outputs']:output['lineage']={**output['lineage'],'toolVersion':'sandbox-lab-v1','sandboxLeaseId':lease['id'],'runtime':getattr(self.provider(),'runtime','test_adapter'),'inputMaterial':task.get('inputMaterial'),'snapshot':self.policy.snapshot,'codeHash':hashlib.sha256(runner_source()).hexdigest()}
        result['completion']['policyVersion']='sandbox-lab-v1'
        result['completion']['checks'].extend([{'criterion':'remote_output_formats','status':'pass'}, {'criterion':'remote_result_recomputed','status':'pass'}])
        self.release(lease)
        return result

    def release(self,lease):
        if not lease['provider_id']:return False
        try:self.provider().release(lease['provider_id'])
        except SandboxError:
            try:
                if self.provider().reconcile(lease['creation_key']):return False
            except SandboxError:return False
        self._save(lease,status='released')
        return True

    def cleanup(self):
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT l.*,r.status AS task_status,r.desired_input_revision AS current_revision FROM agent_sandbox_leases l LEFT JOIN assistant_runs r ON r.id=l.run_id WHERE l.status<>'deleted' LIMIT 100")).mappings().all()
            obligations=conn.execute(text('SELECT * FROM agent_sandbox_cleanup LIMIT 20')).mappings().all()
        for row in rows:
            terminal=row['task_status'] in {'completed','completed_partial','failed','cancelled',None}
            stale=row['current_revision']!=row['input_revision']
            expired=row['expires_at']<=time.time()
            lease={**dict(row),'payload':json.loads(row['payload'])}
            if row['status']=='released' and not terminal and not stale and not expired:continue
            if not terminal and not stale and not expired and row['task_status']!='paused':continue
            if not lease['provider_id'] and lease['status']=='creating':
                try:identifier=self.provider().reconcile(lease['creation_key'])
                except SandboxError:continue
                if identifier:lease=self._save(lease,provider_id=identifier)
                elif not expired:continue
            if lease['provider_id'] and not self.release(lease):continue
            # Pausing deletes compute; cached outputs remain recoverable until
            # task completion. A paused pre-output operation requires restart.
            if row['task_status']=='paused' and not terminal and not stale and not expired:continue
            for item in lease['payload'].get('outputs',{}).values():self.objects.delete(lease['owner_id'],item['key'])
            # Retain compact object-key tombstones for late upload cleanup.
            self._save(lease,status='deleted',payload={'outputsReady':False})
        for obligation in obligations:
            try:
                identifier=obligation['provider_id'] or self.provider().reconcile(obligation['creation_key'])
                if identifier:self.provider().release(identifier)
                elif time.time()-obligation['created_at']<1800:continue
            except SandboxError:
                try:
                    if self.provider().reconcile(obligation['creation_key']):continue
                except SandboxError:continue
            with self.store.transaction() as conn:conn.execute(text('DELETE FROM agent_sandbox_cleanup WHERE id=:id'),{'id':obligation['id']})
