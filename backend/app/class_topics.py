"""Bounded semantic organization and revision-fenced student topic changes."""
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import text
from .workflow_store import encoded


class ClassTopicService:
    def __init__(self, classes):
        self.classes=classes;self.store=classes.store

    @staticmethod
    def assign(conn,item,block_id,title,start_ms,semantic_id=None,context=None):
        heading=' '.join(re.findall(r'[^\W_]+',title.casefold())) or 'Lecture notes'
        topic_id='classtopic_'+hashlib.sha256(encoded([item['id'],heading]).encode()).hexdigest()[:32]
        candidate=next((entry for entry in context or [] if entry['id']==semantic_id),None)
        if candidate:
            current=conn.execute(text('SELECT revision FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':semantic_id,'owner':item['owner'],'class':item['id']}).scalar_one_or_none()
            if current==candidate['revision']:topic_id=semantic_id
        # Resolve merged headings so later mentions retain the same section.
        for _ in range(8):
            previous=conn.execute(text('SELECT payload FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':topic_id,'owner':item['owner'],'class':item['id']}).scalar_one_or_none()
            target=json.loads(previous).get('mergedInto') if previous else None
            if not target:break
            topic_id=target
        payload={'id':topic_id,'title':title,'origin':'generated','headingKey':heading}
        conn.execute(text('INSERT INTO class_document_topics(id,owner_id,class_id,position,payload) VALUES(:id,:owner,:class,:position,:payload) ON CONFLICT(id) DO NOTHING'),{'id':topic_id,'owner':item['owner'],'class':item['id'],'position':float(start_ms),'payload':encoded(payload)})
        # Preserve student moves across automatic regeneration.
        conn.execute(text('UPDATE class_document_blocks SET topic_id=:topic,position=:position WHERE id=:id AND owner_id=:owner AND topic_id IS NULL'),{'id':block_id,'owner':item['owner'],'topic':topic_id,'position':float(start_ms)})
        return topic_id

    @staticmethod
    def context(conn,item):
        rows=conn.execute(text('SELECT t.id,t.revision,t.position,t.payload FROM class_document_topics t WHERE t.owner_id=:owner AND t.class_id=:class AND EXISTS(SELECT 1 FROM class_document_blocks b WHERE b.topic_id=t.id AND b.owner_id=t.owner_id AND b.class_id=t.class_id) ORDER BY t.position DESC,t.id LIMIT 20'),{'owner':item['owner'],'class':item['id']}).mappings().all()
        result=[]
        for row in reversed(rows):
            saved=json.loads(row['payload'])
            samples=conn.execute(text('SELECT id,revision,payload FROM class_document_blocks WHERE owner_id=:owner AND class_id=:class AND topic_id=:topic ORDER BY position DESC,id LIMIT 2'),{'owner':item['owner'],'class':item['id'],'topic':row['id']}).mappings().all()
            result.append({'id':row['id'],'revision':row['revision'],'title':saved['title'][:240],'studentOrganized':saved.get('origin')=='student','samples':[json.loads(value['payload']).get('generated',{}).get('body','')[:160] for value in samples],'blockRefs':[{'id':value['id'],'revision':value['revision']} for value in samples]})
        return result

    @staticmethod
    def semantic_merges(conn,item,merges,context):
        frozen={entry['id']:entry for entry in context or []};used=set()
        for merge in merges[:4]:
            source,target=merge['sourceTopicId'],merge['targetTopicId']
            if source==target or source not in frozen or target not in frozen or source in used or target in used:continue
            rows=[]
            for identifier in (source,target):
                row=conn.execute(text('SELECT revision,payload FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':identifier,'owner':item['owner'],'class':item['id']}).mappings().first()
                if not row or row['revision']!=frozen[identifier]['revision'] or json.loads(row['payload']).get('origin')=='student' or json.loads(row['payload']).get('mergedInto'):break
                rows.append(row)
            if len(rows)!=2:continue
            references=[reference for identifier in (source,target) for reference in frozen[identifier].get('blockRefs',[])]
            if any(conn.execute(text('SELECT revision FROM class_document_blocks WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':reference['id'],'owner':item['owner'],'class':item['id']}).scalar_one_or_none()!=reference['revision'] for reference in references):continue
            blocks=conn.execute(text('SELECT payload FROM class_document_blocks WHERE owner_id=:owner AND class_id=:class AND topic_id IN (:source,:target)'),{'owner':item['owner'],'class':item['id'],'source':source,'target':target}).scalars().all()
            if any(json.loads(value).get('studentEdited') or json.loads(value).get('organizationLocked') for value in blocks):continue
            conn.execute(text('UPDATE class_document_blocks SET topic_id=:target,revision=revision+1 WHERE owner_id=:owner AND class_id=:class AND topic_id=:source'),{'owner':item['owner'],'class':item['id'],'source':source,'target':target})
            saved=json.loads(rows[0]['payload']);saved['mergedInto']=target
            conn.execute(text('UPDATE class_document_topics SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':source,'owner':item['owner'],'payload':encoded(saved)})
            conn.execute(text('UPDATE class_document_topics SET revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':target,'owner':item['owner']})
            frozen[source]['revision']+=1;frozen[target]['revision']+=1
            used.update((source,target))

    def listing(self,owner,class_id,cursor=''):
        with self.store.engine.connect() as conn:
            self.classes.row(conn,owner,class_id)
            after=None
            if cursor:
                after=conn.execute(text('SELECT position FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':cursor,'owner':owner,'class':class_id}).scalar_one_or_none()
                if after is None:raise HTTPException(400,{'code':'invalid_cursor','message':'Reload the topic outline.'})
            condition=' AND (t.position>:after OR (t.position=:after AND t.id>:cursor))' if after is not None else ''
            rows=conn.execute(text('SELECT t.id,t.revision,t.position,t.payload,COUNT(b.id) AS block_count FROM class_document_topics t LEFT JOIN class_document_blocks b ON b.topic_id=t.id AND b.owner_id=t.owner_id AND b.class_id=t.class_id WHERE t.owner_id=:owner AND t.class_id=:class'+condition+' GROUP BY t.id,t.revision,t.position,t.payload HAVING COUNT(b.id)>0 ORDER BY t.position,t.id LIMIT 201'),{'owner':owner,'class':class_id,'after':after,'cursor':cursor}).mappings().all()
        return {'items':[{**json.loads(row['payload']),'revision':row['revision'],'position':row['position'],'blockCount':row['block_count']} for row in rows[:200]], 'hasMore':len(rows)>200,'nextCursor':rows[199]['id'] if len(rows)>200 else None}

    def change(self,owner,class_id,topic_id,body):
        with self.store.transaction() as conn:
            item=self.classes.row(conn,owner,class_id,True)
            topic=conn.execute(text('SELECT revision,payload FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':topic_id,'owner':owner,'class':class_id}).mappings().first()
            if not topic or topic['revision']!=body.expectedRevision:
                raise HTTPException(409,{'code':'revision_conflict','message':'This topic changed. Reload it.'})
            saved=json.loads(topic['payload'])
            if saved.get('mergedInto'):raise HTTPException(409,{'code':'topic_merged','message':'This topic has been merged. Reload the outline.'})
            saved['origin']='student'
            if body.action=='rename':
                if not body.title.strip():raise HTTPException(422,{'code':'invalid_title','message':'Enter a topic heading.'})
                saved.update(title=body.title.strip(),origin='student')
            elif body.action=='merge':
                target=conn.execute(text('SELECT revision FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':body.targetTopicId,'owner':owner,'class':class_id}).scalar_one_or_none()
                if target is None or target!=body.targetRevision or body.targetTopicId==topic_id:
                    raise HTTPException(409,{'code':'revision_conflict','message':'The destination topic changed. Reload it.'})
                target_payload=json.loads(conn.execute(text('SELECT payload FROM class_document_topics WHERE id=:id AND owner_id=:owner'),{'id':body.targetTopicId,'owner':owner}).scalar_one())
                if target_payload.get('mergedInto'):raise HTTPException(409,{'code':'topic_merged','message':'Choose a current destination topic.'})
                conn.execute(text('UPDATE class_document_blocks SET topic_id=:target,revision=revision+1 WHERE owner_id=:owner AND class_id=:class AND topic_id=:id'),{'owner':owner,'class':class_id,'target':body.targetTopicId,'id':topic_id})
                conn.execute(text('UPDATE class_document_topics SET revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':body.targetTopicId,'owner':owner})
                saved['mergedInto']=body.targetTopicId
                target_payload=json.loads(conn.execute(text('SELECT payload FROM class_document_topics WHERE id=:id AND owner_id=:owner'),{'id':body.targetTopicId,'owner':owner}).scalar_one())
                target_payload['origin']='student'
                conn.execute(text('UPDATE class_document_topics SET payload=:payload WHERE id=:id AND owner_id=:owner'),{'id':body.targetTopicId,'owner':owner,'payload':encoded(target_payload)})
            else:
                conn.execute(text('UPDATE class_document_topics SET position=:position WHERE id=:id AND owner_id=:owner'),{'id':topic_id,'owner':owner,'position':body.position})
            conn.execute(text('UPDATE class_document_topics SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':topic_id,'owner':owner,'payload':encoded(saved)})
            self.classes.event(conn,item,'document.organized',{'topicId':topic_id,'action':body.action})
        return self.listing(owner,class_id)
