"""One owner-scoped CAS boundary; immutable content/attempt records."""
import hashlib
import json
import time
from contextlib import contextmanager
from sqlalchemy import text
from ..identity import assert_owner_active, fail
from ..workflow_store import encoded
TABLES={'decks':'flashcard_decks','cards':'flashcards','versions':'flashcard_versions','candidates':'flashcard_generation_candidates','sessions':'flashcard_review_sessions','attempts':'flashcard_review_attempts','schedule':'flashcard_schedule_state','preferences':'flashcard_preferences'}
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
class Repository:
    def __init__(self,store):self.store=store
    @contextmanager
    def transaction(self,owner):
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            if conn.dialect.name=='sqlite':conn.execute(text('UPDATE flashcard_decks SET revision=revision WHERE 1=0'))
            yield conn
    def get(self,conn,owner,kind,identifier,lock=False):
        suffix=' FOR UPDATE' if lock and conn.dialect.name=='postgresql' else ''
        row=conn.execute(text(f'SELECT * FROM {TABLES[kind]} WHERE id=:id AND owner_id=:owner'+suffix),{'id':identifier,'owner':owner}).mappings().first()
        if not row:fail('not_found','Flashcard activity unavailable.',404)
        return {**json.loads(row['payload']),'id':row['id'],'revision':row['revision']}
    def rows(self,conn,owner,kind,parent=None):
        query=f'SELECT * FROM {TABLES[kind]} WHERE owner_id=:owner'+(' AND parent_id=:parent' if parent is not None else '')+' ORDER BY created_at,id'
        return [{**json.loads(r['payload']),'id':r['id'],'revision':r['revision']} for r in conn.execute(text(query),{'owner':owner,'parent':parent}).mappings()]
    def put(self,conn,owner,kind,value,parent=None,new=False):
        args={'id':value['id'],'owner':owner,'parent':parent,'payload':encoded(value),'now':time.time(),'revision':value.get('revision',1)}
        if new:conn.execute(text(f'INSERT INTO {TABLES[kind]}(id,owner_id,parent_id,revision,payload,created_at) VALUES(:id,:owner,:parent,1,:payload,:now)'),args)
        else:
            if kind in {'versions','attempts'}:raise ValueError('Immutable flashcard record')
            changed=conn.execute(text(f'UPDATE {TABLES[kind]} SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner AND revision=:revision'),args)
            if changed.rowcount!=1:fail('revision_conflict','Flashcards changed. Refresh and reconcile your edits.',409)
        return self.get(conn,owner,kind,value['id'])
    def replay(self,conn,owner,target,body):
        row=conn.execute(text('SELECT * FROM flashcard_commands WHERE id=:id AND owner_id=:owner'),{'id':body.command_id,'owner':owner}).mappings().first()
        if row:
            if row['target_id']!=target or row['request_hash']!=digest(body.model_dump(by_alias=True)):fail('idempotency_conflict','Command identity has different content.',409)
            return json.loads(row['payload'])
        if conn.execute(text('SELECT 1 FROM flashcard_commands WHERE id=:id'),{'id':body.command_id}).first():fail('idempotency_conflict','Use a new command identity.',409)
    def receipt(self,conn,owner,target,body,result):
        conn.execute(text('INSERT INTO flashcard_commands(id,owner_id,target_id,request_hash,payload,created_at) VALUES(:id,:owner,:target,:hash,:payload,:now)'),{'id':body.command_id,'owner':owner,'target':target,'hash':digest(body.model_dump(by_alias=True)),'payload':encoded(result),'now':time.time()})
        return result
