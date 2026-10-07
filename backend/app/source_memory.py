"""Owner scoped immutable sources. Indexes never decide source eligibility."""
from __future__ import annotations
import hashlib, json, re, time
from uuid import uuid4
from sqlalchemy import text
from .identity import assert_owner_active, fail

class SourceMemory:
    def __init__(self, store): self.store=store

    @staticmethod
    def blocks(content):
        # Retain exact character locators; overlap never creates a new origin.
        return [{'originId':hashlib.sha256(f'{m.start()}:{m.group()}'.encode()).hexdigest(), 'start':m.start(), 'end':m.end(), 'text':m.group()} for m in re.finditer(r'\S[\s\S]*?(?=\n\s*\n|$)',content)]

    def revise(self, owner, source_id, content, *, kind='note', course_id=None, expected_revision=0, metadata=None):
        if len(content.encode())>10_000_000: fail('source_too_large','Source text exceeds 10 MB.',413)
        payload={'text':content,'blocks':self.blocks(content),'metadata':metadata or {}}
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            old=conn.execute(text('SELECT * FROM memory_sources WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':source_id}).mappings().first()
            if (old['revision'] if old else 0)!=expected_revision:
                from fastapi import HTTPException
                raise HTTPException(409,detail={'code':'revision_conflict','message':'Refresh the current source revision before saving.','currentRevision':old['revision'] if old else 0})
            rev=expected_revision+1
            args={'owner':owner,'id':source_id,'kind':kind,'course':course_id,'revision':rev,'now':time.time()}
            if old:
                changed=conn.execute(text('UPDATE memory_sources SET revision=:revision,deleted=false,updated_at=:now WHERE owner_id=:owner AND id=:id AND revision=:expected'),{**args,'expected':expected_revision}).rowcount
                if not changed: fail('revision_conflict','Source changed during save.',409)
            else: conn.execute(text('INSERT INTO memory_sources(owner_id,id,kind,course_id,revision,deleted,updated_at) VALUES(:owner,:id,:kind,:course,:revision,false,:now)'),args)
            conn.execute(text('INSERT INTO memory_revisions(owner_id,source_id,revision,sha256,payload,created_at) VALUES(:owner,:id,:revision,:sha,:payload,:now)'),{**args,'sha':hashlib.sha256(content.encode()).hexdigest(),'payload':json.dumps(payload)})
            self.invalidate(conn,owner,source_id)
        return {'id':source_id,'revision':rev,'blocks':len(payload['blocks'])}

    @staticmethod
    def invalidate(conn,owner,source_id):
        rows=conn.execute(text('SELECT id,payload FROM memory_derived WHERE owner_id=:owner AND valid=true'),{'owner':owner}).mappings()
        for row in rows:
            if any(d['sourceId']==source_id for d in json.loads(row['payload']).get('basis',[])):
                conn.execute(text('UPDATE memory_derived SET valid=false WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':row['id']})

    def remove(self,owner,source_id,expected_revision):
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            result=conn.execute(text('UPDATE memory_sources SET deleted=true,updated_at=:now WHERE owner_id=:owner AND id=:id AND revision=:revision'),{'owner':owner,'id':source_id,'revision':expected_revision,'now':time.time()})
            if not result.rowcount: fail('revision_conflict','Source unavailable or changed.',409)
            self.invalidate(conn,owner,source_id)
        return {'status':'removed','historicalRevisionsPreserved':True}

    def retrieve(self,conn,owner,query='',course_id=None,required_ids=(),purpose='teaching'):
        assert_owner_active(conn,owner)
        # A quiz may use notes, assigned material, and lecture sources to
        # establish scope. Conversation transcripts can contain prior answers
        # or worked solutions, so they are not admitted to assessment context.
        if purpose not in {'teaching','assessment','readiness','planning','execution','coordination'}:
            fail('invalid_context_purpose','Unknown context purpose.',422)
        sql='SELECT s.*,r.payload FROM memory_sources s JOIN memory_revisions r ON r.owner_id=s.owner_id AND r.source_id=s.id AND r.revision=s.revision WHERE s.owner_id=:owner AND s.deleted=false'
        params={'owner':owner}
        if course_id: sql+=' AND s.course_id=:course'; params['course']=course_id
        terms=set(re.findall(r'\w+',query.lower()))
        candidates=[]
        for row in conn.execute(text(sql),params).mappings():
            # Legacy content-addressed snapshots are retained for provenance;
            # active retrieval comes from their authoritative note/material/
            # transcript tables, which can enforce current access and deletion.
            if row['kind'].startswith('legacy_'):
                continue
            if purpose in {'execution','coordination'} and row['kind'] == 'conversation' and row['id'] not in required_ids:
                continue
            if purpose == 'assessment' and row['kind'] not in {'note','document','transcript'}:
                continue
            for block in json.loads(row['payload'])['blocks']:
                score=len(terms & set(re.findall(r'\w+',block['text'].lower())))
                if score or not terms or row['id'] in required_ids:
                    candidates.append({**block,'sourceId':row['id'],'revision':row['revision'],'kind':row['kind'],'score':score,'required':row['id'] in required_ids})
        return sorted(candidates,key=lambda b:(not b['required'],-b['score'],b['sourceId'],b['start']))

    def derive(self,owner,kind,value,basis,scope=None,explicit=False,identifier=None):
        if not basis: fail('memory_basis_required','Remembered facts require exact source references.',422)
        if kind=='preference' and not explicit: value={'tentative':True,'value':value}
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            for ref in basis:
                current=conn.execute(text('SELECT revision FROM memory_sources WHERE owner_id=:owner AND id=:id AND deleted=false'),{'owner':owner,'id':ref['sourceId']}).scalar_one_or_none()
                if current!=ref['revision']: fail('source_changed','Derived memory requires current sources.',409)
            payload=json.dumps({'value':value,'basis':basis,'scope':scope,'explicit':explicit})
            if identifier:
                existing=conn.execute(text('SELECT payload,valid FROM memory_derived WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':identifier}).first()
                if existing:
                    if existing[0]!=payload or not existing[1]:fail('memory_identity_conflict','This saved memory changed or was forgotten; a retry cannot replace it.',409)
                    return {'id':identifier}
            identifier=identifier or 'derived_'+uuid4().hex
            conn.execute(text('INSERT INTO memory_derived(owner_id,id,kind,payload,valid) VALUES(:owner,:id,:kind,:payload,true)'),{'owner':owner,'id':identifier,'kind':kind,'payload':json.dumps({'value':value,'basis':basis,'scope':scope,'explicit':explicit})})
        return {'id':identifier}

    def summarize(self,owner,source_id,revision):
        """Lossless bounded summary of continuity lines, with exact source ranges.

        Extractive output is labeled rather than claiming an inferred model
        summary. Required questions and constraints remain in exact sources.
        """
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text('SELECT r.payload FROM memory_revisions r JOIN memory_sources s ON s.owner_id=r.owner_id AND s.id=r.source_id WHERE r.owner_id=:owner AND r.source_id=:id AND r.revision=:revision AND s.revision=r.revision AND s.deleted=false'),{'owner':owner,'id':source_id,'revision':revision}).scalar_one_or_none()
            if row is None: fail('source_changed','Select a current source revision.',409)
            blocks=json.loads(row)['blocks']
        selected=[b for b in blocks if '?' in b['text'] or re.search(r'\b(decid|must|constraint|prefer|next|unresolved)\w*',b['text'],re.I)]
        if not selected: selected=blocks[:3]
        value={'method':'extractive-continuity-v1','ranges':[{'start':b['start'],'end':b['end'],'originId':b['originId']} for b in selected],'text':'\n\n'.join(b['text'] for b in selected),'omittedBlockCount':len(blocks)-len(selected),'exactHistoryRetained':True}
        return self.derive(owner,'summary',value,[{'sourceId':source_id,'revision':revision}])
