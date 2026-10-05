"""Compatibility adapter for class-window drafts and older practice_records."""
import hashlib,json,time
from sqlalchemy import text
from ..workflow_store import WorkflowStore,uid
from .service import DeckService
from .repository import digest

def class_deck_id(class_id):return 'deck_'+hashlib.sha256(class_id.encode()).hexdigest()[:32]
def save_class(store,conn,owner,item,wid,result,manifest):
    svc=DeckService(store);identifier=class_deck_id(item['id'])
    row=conn.execute(text('SELECT 1 FROM flashcard_decks WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).first()
    deck=svc.repo.get(conn,owner,'decks',identifier,True) if row else svc.create(conn,owner,'Class flashcards · '+item['title'],manifest,identifier=identifier,class_id=item['id'])
    svc.append(conn,owner,deck,result,manifest,'class:'+wid)
    # Keep legacy draft payloads readable for old clients; new UI uses deck IDs.
    records=WorkflowStore(store);exists=conn.execute(text("SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner AND kind='flashcard_deck'"),{'id':identifier,'owner':owner}).first()
    legacy=records.read(owner,identifier,'flashcard_deck',conn) if exists else {'id':identifier,'classId':item['id'],'courseId':item['courseId'],'status':'draft','windows':{},'scheduled':False}
    legacy['windows'][wid]=[{**c,'segmentIds':c['sourceIds']} for c in result['cards']];legacy['cards']=[c for key,cards in legacy['windows'].items() if key in item['activeWindows'] for c in cards]
    records.put(conn,owner,'flashcard_deck',legacy,parent=item['id'],expected=legacy['revision'] if exists else None)
    return identifier

def migrate_legacy(store,conn,owner):
    svc=DeckService(store)
    for old in WorkflowStore(store).listing(owner,'flashcard_deck'):
        if conn.execute(text('SELECT 1 FROM flashcard_decks WHERE id=:id AND owner_id=:owner'),{'id':old['id'],'owner':owner}).first():continue
        row=conn.execute(text('SELECT payload FROM class_sessions WHERE id=:id AND owner_id=:owner'),{'id':old.get('classId'),'owner':owner}).scalar_one_or_none()
        if not row:continue
        item=json.loads(row);manifest={'sessionId':item['sessionId'],'courseId':item.get('courseId'),'buddyId':item.get('buddyId'),'sources':[],'partial':True}
        deck=svc.create(conn,owner,'Imported class draft · '+item['title'],manifest,identifier=old['id'],class_id=old['classId'])
        for card in old.get('cards',[]):
            refs=[]
            for sid in card.get('segmentIds',[]):
                seg=conn.execute(text('SELECT * FROM lecture_transcript_segments WHERE id=:id AND recording_id=:rid'),{'id':sid,'rid':item['recordingId']}).mappings().first()
                if seg:refs.append({'id':sid,'title':item['title'],'ref':{'kind':'lecture','id':sid,'revision':seg['normalization_version'],'recordingId':item['recordingId'],'startMs':seg['start_ms'],'endMs':seg['end_ms']},'hash':digest(seg['normalized_text'] or seg['raw_text']),'text':seg['normalized_text'] or seg['raw_text']})
            if not refs:continue
            content={'type':'qa','prompt':card['prompt'],'answer':card['answer'],'explanation':'','sourceIds':[r['id'] for r in refs],'supportQuote':refs[0]['text'][:2500],'conceptIds':[]}
            svc.repo.put(conn,owner,'candidates',{'id':uid('candidate'),'deckId':deck['id'],'status':'pending','reason':'legacy_unchecked','content':content},parent=deck['id'],new=True)
            manifest['sources'].extend(refs)
        deck['coverage']={'partial':True,'sources':[{k:v for k,v in r.items() if k!='text'} for r in manifest['sources']]};svc.repo.put(conn,owner,'decks',deck)

def invalidate_source(store,conn,owner,source_id):
    svc=DeckService(store)
    for deck in svc.repo.rows(conn,owner,'decks'):
        affected=False
        for card in svc.repo.rows(conn,owner,'cards',deck['id']):
            version=svc.repo.get(conn,owner,'versions',card['versionId'])
            published=svc.repo.get(conn,owner,'versions',card['publishedVersionId']) if card.get('publishedVersionId') else None
            def depends(content):
                return bool(content and (source_id in content['sourceIds'] or (content.get('image') or {}).get('versionId')==source_id))
            current_affected=depends(version);published_affected=depends(published)
            if (current_affected and not card.get('stale')) or (published_affected and not card.get('publishedStale')):
                card['stale']=bool(card.get('stale') or current_affected or published_affected)
                card['publishedStale']=bool(card.get('publishedStale') or published_affected)
                svc.repo.put(conn,owner,'cards',card);affected=True
        if affected:deck['updatedAt']=time.time();svc.repo.put(conn,owner,'decks',deck)
