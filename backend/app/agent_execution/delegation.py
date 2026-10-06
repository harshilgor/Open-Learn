"""One-level children with shared, atomic parent limits and verified outputs."""
import json
import os
import time
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded
from .repository import Repository, digest, TERMINAL
from .coordinator import Coordinator
from .contracts import Command
from .artifacts import Artifacts
from .research_contracts import ResearchUnavailable

def delegation_enabled():return os.getenv('OPENLEARN_DELEGATION_ENABLED','false').lower()=='true'

class Delegation:
    def __init__(self,store):self.store=store;self.repo=Repository(store);self.coordinator=Coordinator(store)
    def list(self,owner,parent):
        with self.repo.transaction() as conn:
            self.repo.run(conn,owner,parent)
            rows=conn.execute(text('SELECT * FROM agent_delegated_children WHERE parent_id=:parent AND owner_id=:owner ORDER BY created_at'),{'parent':parent,'owner':owner}).mappings().all()
            budget=conn.execute(text('SELECT children_remaining,calls_remaining,tokens_remaining FROM agent_delegation_budgets WHERE run_id=:parent AND owner_id=:owner ORDER BY created_at DESC LIMIT 1'),{'parent':parent,'owner':owner}).mappings().first()
            return {'items':[{'id':r['id'],'childId':r['child_id'],'status':r['status'],**json.loads(r['payload'])} for r in rows],'budget':dict(budget) if budget else None,'maximumDepth':1,'externalWrites':False}
    def create(self,owner,parent,body,key):
        if not delegation_enabled():fail('delegation_disabled','New child tasks are disabled.',503)
        if not key or len(key)>160:fail('invalid_input','Provide a stable child key.',422)
        identifier='child_'+digest([owner,parent,key])[:32];request_hash=digest(body.model_dump())
        with self.repo.transaction() as conn:
            run=self.repo.run(conn,owner,parent)
            existing=conn.execute(text('SELECT * FROM agent_delegated_children WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if existing:
                if existing['request_hash']!=request_hash:fail('idempotency_conflict','Child key has different content.',409)
                return {'id':identifier,'childId':existing['child_id'],'status':existing['status']}
            if run['revision']!=body.expectedRevision:fail('revision_conflict','Refresh the parent task.',409)
            if run['status'] in {'cancelled','failed','paused','waiting'}:fail('parent_inactive','Parent cannot start child work.',409)
            if conn.execute(text('SELECT 1 FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':parent,'owner':owner}).first():fail('delegation_depth_denied','Children cannot delegate.',403)
            if (body.kind=='research' and run['kind']!='research') or (body.kind=='lab_analysis' and run['kind'] not in {'lab_analysis','sandbox_lab'}):fail('child_capability_denied','Child cannot expand the parent capability.',403)
            budget_id='budget_'+digest([owner,parent,run['desired_input_revision']])[:32]
            conn.execute(text('INSERT INTO agent_delegation_budgets(id,owner_id,created_at,run_id,input_revision,children_remaining,calls_remaining,tokens_remaining) VALUES(:id,:owner,:now,:run,:revision,2,24,50000) ON CONFLICT(id) DO NOTHING'),{'id':budget_id,'owner':owner,'now':time.time(),'run':parent,'revision':run['desired_input_revision']})
            reserved=conn.execute(text('UPDATE agent_delegation_budgets SET children_remaining=children_remaining-1 WHERE id=:id AND children_remaining>0'),{'id':budget_id})
            if reserved.rowcount!=1:fail('delegation_budget_exhausted','This parent has reached its child limit.',429)
            spec={**run['researchSpec'],'query':body.assignment} if body.kind=='research' else None
            child=self.coordinator.create(conn,owner,run['sessionId'],body.assignment,'delegation:'+identifier,run.get('csvText'),dict(run['constraints']),parent=parent,kind=body.kind,research_spec=spec,input_material=run.get('inputMaterial'),usage_root_id=run.get('usageRootId') or run['id'])
            payload={'assignment':body.assignment,'budgetId':budget_id,'callsRemaining':12,'tokensRemaining':25000,'sourcePolicy':spec.get('sourcePolicy') if spec else 'inherited_input','externalWrites':False,'verification':None}
            conn.execute(text("INSERT INTO agent_delegated_children(id,owner_id,created_at,parent_id,child_id,input_revision,status,request_hash,payload) VALUES(:id,:owner,:now,:parent,:child,:revision,'running',:hash,:payload)"),{'id':identifier,'owner':owner,'now':time.time(),'parent':parent,'child':child['id'],'revision':run['desired_input_revision'],'hash':request_hash,'payload':encoded(payload)})
            self.repo.activity(conn,run,'child:'+identifier,'child.created',childTaskId=child['id'],text='Started a bounded child task without connector-write grants.')
            return {'id':identifier,'childId':child['id'],'status':'running'}
    def charge(self,owner,task,key,kind,amount):
        if kind not in {'calls','tokens'} or amount<1:raise ValueError('Invalid budget charge.')
        with self.repo.transaction() as conn:
            child=conn.execute(text('SELECT * FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':task,'owner':owner}).mappings().first()
            if child:
                budget_id=json.loads(child['payload'])['budgetId'];parent=child['parent_id']
            else:
                budget=conn.execute(text('SELECT * FROM agent_delegation_budgets WHERE run_id=:id AND owner_id=:owner ORDER BY created_at DESC LIMIT 1'),{'id':task,'owner':owner}).mappings().first()
                if not budget:return
                budget_id=budget['id'];parent=task
            identifier='charge_'+digest([budget_id,task,key,kind])[:32]
            if conn.execute(text('SELECT 1 FROM agent_delegation_charges WHERE id=:id'),{'id':identifier}).first():return
            run=self.repo.run(conn,owner,parent)
            if child and (run['status'] in {'cancelled','failed','paused','waiting'} or run['desired_input_revision']!=child['input_revision']):raise ResearchUnavailable('parent_inactive')
            if child:
                payload=json.loads(child['payload']);remaining='callsRemaining' if kind=='calls' else 'tokensRemaining'
                if payload[remaining]<amount:raise ResearchUnavailable('delegation_budget_exhausted')
                payload[remaining]-=amount
                conn.execute(text('UPDATE agent_delegated_children SET payload=:payload WHERE id=:id'),{'id':child['id'],'payload':encoded(payload)})
            field='calls_remaining' if kind=='calls' else 'tokens_remaining'
            reserved=conn.execute(text(f'UPDATE agent_delegation_budgets SET {field}={field}-:amount WHERE id=:id AND {field}>=:amount'),{'id':budget_id,'amount':amount})
            if reserved.rowcount!=1:raise ResearchUnavailable('delegation_budget_exhausted')
            conn.execute(text('INSERT INTO agent_delegation_charges(id,owner_id,created_at,budget_id,kind,amount) VALUES(:id,:owner,:now,:budget,:kind,:amount)'),{'id':identifier,'owner':owner,'now':time.time(),'budget':budget_id,'kind':kind,'amount':amount})
    def guard(self,conn,owner,task):
        relation=conn.execute(text('SELECT * FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':task['id'],'owner':owner}).mappings().first()
        if not relation:return
        parent=self.repo.run(conn,owner,relation['parent_id'])
        if parent['status'] in {'cancelled','failed','paused','waiting'} or parent['desired_input_revision']!=relation['input_revision']:raise ResearchUnavailable('parent_inactive')
    def tick(self,limit=10):
        with self.store.engine.connect() as conn:rows=conn.execute(text("SELECT id,owner_id FROM agent_delegated_children WHERE status='running' ORDER BY created_at LIMIT :limit"),{'limit':limit}).mappings().all()
        for item in rows:
            try:self.verify(item['owner_id'],item['id'])
            except Exception:continue # Owner deletion/fencing cannot revive work.
    def verify(self,owner,identifier):
        with self.repo.transaction() as conn:
            assert_owner_active(conn,owner)
            relation=conn.execute(text('SELECT * FROM agent_delegated_children WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if not relation:fail('not_found','Child unavailable.',404)
            if relation['status']!='running':return
            parent=self.repo.run(conn,owner,relation['parent_id']);child=self.repo.run(conn,owner,relation['child_id'])
            stale=parent['status'] in {'cancelled','failed','paused','waiting'} or parent['desired_input_revision']!=relation['input_revision']
            if stale and child['status'] not in TERMINAL:
                self.coordinator.apply_command(conn,owner,child['id'],Command(commandId='parent_cancel_'+identifier,action='cancel',expectedRevision=child['revision']))
                child=self.repo.run(conn,owner,child['id'])
            if child['status'] not in TERMINAL:return
            payload=json.loads(relation['payload']);status='rejected' if stale or child['status'] not in {'completed','completed_partial'} else 'verify'
        if status=='verify':
            try:
                if not child['artifacts']:raise ValueError('No child outputs.')
                receipts=[]
                for artifact in child['artifacts']:
                    record,content=Artifacts(self.store).download(owner,artifact['id'])
                    if record['taskId']!=child['id'] or record['inputRevision']!=child['desired_input_revision']:raise ValueError('Child output scope changed.')
                    receipts.append({'artifactId':record['id'],'sha256':record['sha256'],'size':len(content)})
                payload['verification']={'status':'accepted_partial' if child['status']=='completed_partial' else 'accepted','checks':['owner','input_revision','object_hash','source_access'],'artifacts':receipts,'completion':child['completion'],'semanticSupport':'not_independently_verified' if child['kind']=='research' else 'deterministic_analysis'};status=payload['verification']['status']
            except Exception:status='rejected';payload['verification']={'status':'rejected','reasonCode':'child_output_unavailable'}
        with self.repo.transaction() as conn:
            parent=self.repo.run(conn,owner,relation['parent_id'])
            if parent['status'] in {'cancelled','failed','paused','waiting'} or parent['desired_input_revision']!=relation['input_revision']:status='rejected';payload['verification']={'status':'rejected','reasonCode':'parent_changed'}
            changed=conn.execute(text("UPDATE agent_delegated_children SET status=:status,payload=:payload WHERE id=:id AND status='running'"),{'id':identifier,'status':status,'payload':encoded(payload)})
            if changed.rowcount:self.repo.activity(conn,parent,'child-result:'+identifier,'child.verified',childTaskId=child['id'],text='Child result '+status.replace('_',' ')+'. Parent completion remains independently controlled.')
