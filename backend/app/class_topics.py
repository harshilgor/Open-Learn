"""Incremental heading organization and revision-fenced student topic changes."""
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
    def assign(conn,item,block_id,title,start_ms):
        # Coalesce repeated headings incrementally, without rewriting class text.
        # Fuzzy semantic merges remain an explicit student action.
        heading=' '.join(re.findall(r'[^\W_]+',title.casefold())) or 'Lecture notes'
        topic_id='classtopic_'+hashlib.sha256(encoded([item['id'],heading]).encode()).hexdigest()[:32]
        payload={'id':topic_id,'title':title,'origin':'generated','headingKey':heading}
        conn.execute(text('INSERT INTO class_document_topics(id,owner_id,class_id,position,payload) VALUES(:id,:owner,:class,:position,:payload) ON CONFLICT(id) DO NOTHING'),{'id':topic_id,'owner':item['owner'],'class':item['id'],'position':float(start_ms),'payload':encoded(payload)})
        # Preserve student moves across automatic regeneration.
        conn.execute(text('UPDATE class_document_blocks SET topic_id=:topic,position=:position WHERE id=:id AND owner_id=:owner AND topic_id IS NULL'),{'id':block_id,'owner':item['owner'],'topic':topic_id,'position':float(start_ms)})
        return topic_id

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
            if body.action=='rename':
                if not body.title.strip():raise HTTPException(422,{'code':'invalid_title','message':'Enter a topic heading.'})
                saved.update(title=body.title.strip(),origin='student')
            elif body.action=='merge':
                target=conn.execute(text('SELECT revision FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':body.targetTopicId,'owner':owner,'class':class_id}).scalar_one_or_none()
                if target is None or target!=body.targetRevision or body.targetTopicId==topic_id:
                    raise HTTPException(409,{'code':'revision_conflict','message':'The destination topic changed. Reload it.'})
                conn.execute(text('UPDATE class_document_blocks SET topic_id=:target,revision=revision+1 WHERE owner_id=:owner AND class_id=:class AND topic_id=:id'),{'owner':owner,'class':class_id,'target':body.targetTopicId,'id':topic_id})
                conn.execute(text('UPDATE class_document_topics SET revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':body.targetTopicId,'owner':owner})
            else:
                conn.execute(text('UPDATE class_document_topics SET position=:position WHERE id=:id AND owner_id=:owner'),{'id':topic_id,'owner':owner,'position':body.position})
            conn.execute(text('UPDATE class_document_topics SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':topic_id,'owner':owner,'payload':encoded(saved)})
            self.classes.event(conn,item,'document.organized',{'topicId':topic_id,'action':body.action})
        return self.listing(owner,class_id)
