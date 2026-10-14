"""Persistent note blocks with optimistic student edits and explicit AI suggestions."""
import hashlib
import json
import time
from fastapi import HTTPException
from sqlalchemy import text
from .in_class_service import InClassService
from .workflow_store import encoded


class ClassDocumentService:
    def __init__(self, store):
        self.store = store
        self.classes = InClassService(store)

    @staticmethod
    def backfill_ranges(conn,limit=50):
        rows=conn.execute(text('SELECT id,owner_id,revision,payload FROM class_document_blocks WHERE source_end_ms IS NULL ORDER BY created_at,id LIMIT :limit'),{'limit':min(50,limit)}).mappings().all()
        for row in rows:
            manifest=(json.loads(row['payload']).get('generated',{}).get('sourceManifest') or {})
            start,end=manifest.get('startMs'),manifest.get('endMs')
            if start is not None and end is not None:
                conn.execute(text('UPDATE class_document_blocks SET source_start_ms=:start,source_end_ms=:end WHERE id=:id AND owner_id=:owner AND revision=:revision AND source_end_ms IS NULL'),{'id':row['id'],'owner':row['owner_id'],'revision':row['revision'],'start':start,'end':end})
            else:
                conn.execute(text('UPDATE class_document_blocks SET source_start_ms=-1,source_end_ms=-1 WHERE id=:id AND owner_id=:owner AND revision=:revision AND source_end_ms IS NULL'),{'id':row['id'],'owner':row['owner_id'],'revision':row['revision']})
        return len(rows)

    @staticmethod
    def invalidate_source(conn, owner, recording, segment_id):
        classes = conn.execute(text('SELECT id FROM class_sessions WHERE owner_id=:owner AND recording_id=:recording'), {'owner': owner, 'recording': recording}).scalars().all()
        for class_id in classes:
            for table in ('class_document_blocks', 'class_visual_artifacts'):
                rows = conn.execute(text('SELECT id,payload FROM ' + table + ' WHERE owner_id=:owner AND class_id=:class AND state=\'ready\''), {'owner': owner, 'class': class_id}).mappings().all()
                for row in rows:
                    saved = json.loads(row['payload'])
                    source = saved.get('generated') if table == 'class_document_blocks' else saved.get('source')
                    if segment_id in (source or {}).get('segmentIds', []):
                        conn.execute(text('UPDATE ' + table + " SET state='stale',revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner"), {'id': row['id'], 'owner': owner, 'now': time.time()})

    @staticmethod
    def publish(conn, item, output):
        if output.get('kind') != 'notes' or output.get('status') != 'ready':
            return
        for block in output.get('result', {}).get('blocks', []):
            sources = sorted(set(block.get('segmentIds', [])))
            if not sources:
                continue
            identifier = 'classblock_' + hashlib.sha256(encoded([item['id'], sources]).encode()).hexdigest()[:32]
            manifest=block.get('sourceManifest') or {}
            start,end=manifest.get('startMs'),manifest.get('endMs')
            if start is not None and end is not None:
                candidates=conn.execute(text("SELECT id,source_start_ms,source_end_ms FROM class_document_blocks WHERE owner_id=:owner AND class_id=:class AND state='stale' AND source_start_ms<=:end AND source_end_ms>=:start ORDER BY source_start_ms,id LIMIT 20"),{'owner':item['owner'],'class':item['id'],'start':start,'end':end}).mappings().all()
                # Only near-identical coverage maps automatically. Ambiguous
                # merges keep their old blocks for explicit student review.
                matches=[candidate for candidate in candidates if max(0,min(end,candidate['source_end_ms'])-max(start,candidate['source_start_ms']))/max(1,max(end,candidate['source_end_ms'])-min(start,candidate['source_start_ms']))>=.95]
                if len(matches)==1:identifier=matches[0]['id']
            prior = conn.execute(text('SELECT payload FROM class_document_blocks WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': item['owner']}).scalar_one_or_none()
            generated = {'title': block['title'], 'body': block['body'], 'segmentIds': sources, 'sourceManifest': block.get('sourceManifest', {}), 'outputId': output['id'], 'settlement': output.get('settlement', 'provisional')}
            now = time.time()
            if prior:
                saved = json.loads(prior)
                if saved.get('generated') == generated:
                    continue
                if saved.get('studentEdited'):
                    saved['suggestion'] = generated
                else:
                    saved.update(title=generated['title'], body=generated['body'], generated=generated)
                conn.execute(text("UPDATE class_document_blocks SET payload=:payload,state='ready',revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner"), {'id': identifier, 'owner': item['owner'], 'now': now, 'payload': encoded(saved)})
                from .class_buddy import ClassBuddyService
                ClassBuddyService.invalidate_note(conn,item['owner'],item['id'],identifier)
            else:
                saved = {'id': identifier,'schemaVersion':1,'blockType':'paragraph','generatorVersion':'class-notes-v2', 'title': generated['title'], 'body': generated['body'], 'generated': generated, 'studentEdited': False, 'suggestion': None}
                conn.execute(text("INSERT INTO class_document_blocks(id,owner_id,class_id,state,created_at,updated_at,payload) VALUES(:id,:owner,:class,'ready',:now,:now,:payload)"), {'id': identifier, 'owner': item['owner'], 'class': item['id'], 'now': now, 'payload': encoded(saved)})
            from .class_topics import ClassTopicService
            ClassTopicService.assign(conn,item,identifier,block['title'],(block.get('sourceManifest') or {}).get('startMs',now*1000))
            conn.execute(text('UPDATE class_document_blocks SET source_start_ms=:start,source_end_ms=:end WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':item['owner'],'start':start,'end':end})

    def page(self, owner, class_id, cursor=''):
        with self.store.engine.connect() as conn:
            self.classes.row(conn, owner, class_id)
            after = None
            if cursor:
                after = conn.execute(text('SELECT created_at FROM class_document_blocks WHERE id=:id AND owner_id=:owner AND class_id=:class'), {'id': cursor, 'owner': owner, 'class': class_id}).scalar_one_or_none()
                if after is None:
                    raise HTTPException(400, {'code': 'invalid_cursor', 'message': 'Reload the class notes.'})
            condition = ' AND (created_at>:after OR (created_at=:after AND id>:cursor))' if after is not None else ''
            rows = conn.execute(text('SELECT id,revision,state,payload,topic_id,position FROM class_document_blocks WHERE owner_id=:owner AND class_id=:class' + condition + ' ORDER BY created_at,id LIMIT 51'), {'owner': owner, 'class': class_id, 'after': after, 'cursor': cursor}).mappings().all()
            total=conn.execute(text('SELECT COUNT(*) FROM class_document_blocks WHERE owner_id=:owner AND class_id=:class'),{'owner':owner,'class':class_id}).scalar_one()
        return {'items': [{**json.loads(row['payload']), 'revision': row['revision'], 'state': row['state'],'topicId':row['topic_id'],'position':row['position']} for row in rows[:50]], 'nextCursor': rows[49]['id'] if len(rows) > 50 else None,'totalCount':total}

    def edit(self, owner, class_id, identifier, body):
        with self.store.transaction() as conn:
            item = self.classes.row(conn, owner, class_id, True)
            row = conn.execute(text('SELECT revision,state,payload,topic_id,position FROM class_document_blocks WHERE id=:id AND owner_id=:owner AND class_id=:class'), {'id': identifier, 'owner': owner, 'class': class_id}).mappings().first()
            if not row or row['revision'] != body.expectedRevision:
                raise HTTPException(409, {'code': 'revision_conflict', 'message': 'These notes changed. Reload before saving.'})
            saved = json.loads(row['payload'])
            state=row['state']
            topic_id,position=row['topic_id'],row['position']
            if body.action=='move':
                if not conn.execute(text('SELECT 1 FROM class_document_topics WHERE id=:id AND owner_id=:owner AND class_id=:class'),{'id':body.topicId,'owner':owner,'class':class_id}).first():raise HTTPException(404,{'code':'topic_unavailable','message':'Choose a topic from this class.'})
                topic_id,position=body.topicId,body.position
            elif body.action == 'accept_suggestion':
                if not saved.get('suggestion'):
                    raise HTTPException(409, {'code': 'suggestion_unavailable', 'message': 'There is no update to accept.'})
                generated = saved['suggestion']
                for source in (generated.get('sourceManifest') or {}).get('segments',[]):
                    revision=conn.execute(text('SELECT normalization_version FROM lecture_transcript_segments WHERE id=:id AND recording_id=:recording'),{'id':source['segmentId'],'recording':item['recordingId']}).scalar_one_or_none()
                    if revision!=source['revision']:
                        raise HTTPException(409,{'code':'source_stale','message':'This suggestion uses earlier transcript wording. Wait for updated notes.'})
                saved.update(title=generated['title'], body=generated['body'], generated=generated, suggestion=None, studentEdited=False)
                state='ready'
            elif body.action == 'dismiss_suggestion':
                saved['suggestion'] = None
            else:
                saved.update(title=body.title, body=body.body, studentEdited=True)
            changed = conn.execute(text('UPDATE class_document_blocks SET payload=:payload,state=:state,topic_id=:topic,position=:position,revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner AND revision=:revision'), {'id': identifier, 'owner': owner,'state':state,'topic':topic_id,'position':position,'revision': body.expectedRevision, 'payload': encoded(saved), 'now': time.time()})
            if changed.rowcount != 1:
                raise HTTPException(409, {'code': 'revision_conflict', 'message': 'These notes changed. Reload before saving.'})
            self.classes.event(conn, item, 'document.updated', {'blockId': identifier})
            from .class_buddy import ClassBuddyService
            ClassBuddyService.invalidate_note(conn,owner,class_id,identifier)
            return {**saved, 'revision': body.expectedRevision + 1, 'state': state,'topicId':topic_id,'position':position}
