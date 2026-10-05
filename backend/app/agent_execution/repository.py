"""One aggregate writer, task CAS, atomic event/activity counters and checkpoints."""
import hashlib
import json
import time
from contextlib import contextmanager
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded, uid, WorkflowStore
from ..execution_outbox import ExecutionOutbox
from ..browser_assistant.store import AssistantStore

TERMINAL = {'completed', 'completed_partial', 'failed', 'cancelled'}


def digest(value): return hashlib.sha256(encoded(value).encode()).hexdigest()


class Repository:
    def __init__(self, store):
        self.store = store
        self.shared = AssistantStore(store)
        self.jobs = WorkflowStore(store)
        self.outbox = ExecutionOutbox(store)

    @contextmanager
    def transaction(self):
        with self.store.transaction() as conn:
            # Store's principal guard can begin a SQLite read first. Acquire a
            # writer with a harmless UPDATE before any aggregate reads.
            if conn.dialect.name == 'sqlite': conn.execute(text('UPDATE agent_activity_cursors SET sequence=sequence WHERE 1=0'))
            yield conn

    def session(self, conn, owner, session):
        assert_owner_active(conn, owner)
        if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id': session, 'owner': owner}).first():
            fail('not_found', 'Conversation unavailable.', 404)
        conn.execute(text('INSERT INTO agent_activity_cursors(owner_id,session_id,sequence) VALUES(:owner,:session,0) ON CONFLICT(owner_id,session_id) DO NOTHING'), {'owner':owner, 'session':session})
        suffix = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
        conn.execute(text('SELECT sequence FROM agent_activity_cursors WHERE owner_id=:owner AND session_id=:session' + suffix), {'owner':owner,'session':session}).first()

    def run(self, conn, owner, identifier):
        # Every v2 writer locks session -> task -> job, including commands and
        # workers. Opposite lock order can deadlock a reply against completion.
        row=conn.execute(text('SELECT session_id,runtime_owner FROM assistant_runs WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).first()
        if not row or row[1]!='agent_v2':fail('not_found','Execution task unavailable.',404)
        self.session(conn,owner,row[0])
        run = self.shared.run(conn, owner, identifier)
        if run['runtime_owner'] != 'agent_v2': fail('not_found', 'Execution task unavailable.', 404)
        return run

    def read(self, owner, identifier):
        with self.store.engine.connect() as conn: return self.run(conn, owner, identifier)

    def update(self, conn, run, **changes):
        result = self.shared.update_run(conn, run, **changes)
        if 'desired_input_revision' in changes:
            conn.execute(text('UPDATE assistant_runs SET desired_input_revision=:revision WHERE id=:id'), {'revision':changes['desired_input_revision'],'id':run['id']})
        return result

    def event(self, conn, run, kind, **payload):
        seq = conn.execute(text('UPDATE assistant_runs SET event_sequence=event_sequence+1 WHERE id=:id AND owner_id=:owner RETURNING event_sequence'), {'id':run['id'],'owner':run['owner_id']}).scalar_one()
        identifier = uid('ae')
        value = {'schemaVersion':2,'eventId':identifier,'taskId':run['id'],'taskRevision':run['revision'],'type':kind,'timestamp':time.time(),'status':run['status'],'payload':payload}
        conn.execute(text('INSERT INTO assistant_events(id,owner_id,run_id,sequence,payload,created_at) VALUES(:id,:owner,:run,:seq,:payload,:now)'), {'id':identifier,'owner':run['owner_id'],'run':run['id'],'seq':seq,'payload':encoded(value),'now':time.time()})

    def activity(self, conn, run, key, kind, **payload):
        self.session(conn, run['owner_id'], run['sessionId'])
        args = {'owner':run['owner_id'],'session':run['sessionId'],'key':key}
        if conn.execute(text('SELECT 1 FROM agent_activity WHERE owner_id=:owner AND session_id=:session AND item_key=:key'), args).first(): return
        sequence = conn.execute(text('UPDATE agent_activity_cursors SET sequence=sequence+1 WHERE owner_id=:owner AND session_id=:session RETURNING sequence'), args).scalar_one()
        identifier = uid('activity')
        value = {'id':identifier,'taskId':run['id'],'type':kind,'revision':1,**payload}
        conn.execute(text('INSERT INTO agent_activity(id,owner_id,session_id,sequence,item_key,payload,created_at) VALUES(:id,:owner,:session,:seq,:key,:payload,:now)'), {**args,'id':identifier,'seq':sequence,'payload':encoded(value),'now':time.time()})

    def checkpoint(self, conn, run):
        version = run.get('checkpointVersion', 0) + 1
        value = {key:run.get(key) for key in ('constraints','commandCursor','desired_input_revision','inputHash','phase','pendingRequests','operationId')}
        conn.execute(text('INSERT INTO agent_checkpoints(id,owner_id,run_id,version,payload,created_at) VALUES(:id,:owner,:run,:version,:payload,:now)'), {'id':uid('checkpoint'),'owner':run['owner_id'],'run':run['id'],'version':version,'payload':encoded(value),'now':time.time()})
        return self.update(conn, run, checkpointVersion=version)

    def schedule(self, conn, run):
        self.outbox.append(conn, run['owner_id'], 'agent.step', f"step:{run['id']}:{run['revision']}", {'runId':run['id'],'revision':run['revision'],'inputRevision':run['desired_input_revision']})

    def descriptor(self, run):
        state = run['status']
        allowed = [] if state in TERMINAL else ['cancel', 'steer'] + (['resume'] if state == 'paused' else ['pause'])
        if state == 'waiting': allowed += ['answer_input']
        return {'schemaVersion':2, **{k:run.get(k) for k in ('id','revision','sessionId','message','kind','status','phase','waitReason','pendingRequests','artifacts','sources','completion','summary','constraints','checkpointVersion','parentTaskId','error','deckId','resultReferences')},
                'pendingRequest': next(iter(run.get('pendingRequests', [])), None), 'inputRevision':run['desired_input_revision'], 'allowedCommands':allowed}
