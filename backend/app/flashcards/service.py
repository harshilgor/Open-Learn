"""Deck lifecycle. Scheduling and content versions are independent of agent tasks."""
import time
from sqlalchemy import text
from ..identity import fail
from ..workflow_store import uid
from .repository import Repository,digest
from .generation import normalized
class DeckService:
    def __init__(self,store):self.store=store;self.repo=Repository(store)
    def create(self,conn,owner,title,manifest,request=None,identifier=None,class_id=None):
        deck={'id':identifier or uid('deck'),'title':title[:240],'status':'draft','courseId':manifest.get('courseId'),'sessionId':manifest.get('sessionId'),'buddyId':manifest.get('buddyId'),'classId':class_id,'origin':request.origin if request else 'in_class','createdAt':time.time(),'updatedAt':time.time(),'coverage':{'partial':manifest.get('partial',False),'sources':[{'id':s['id'],'title':s['title'],'ref':s['ref'],'hash':s['hash']} for s in manifest.get('sources',[])]},'generationRuns':[]}
        return self.repo.put(conn,owner,'decks',deck,new=True)
    def add_card(self,conn,owner,deck,content,creator='agent'):
        identifier=uid('card');version={'id':uid('fcv'),'cardId':identifier,**content,'contentHash':digest(content),'creatorKind':creator,'createdAt':time.time(),'sourceRefs':[s for s in deck['coverage']['sources'] if s['id'] in content['sourceIds']]}
        self.repo.put(conn,owner,'versions',version,parent=deck['id'],new=True)
        card={'id':identifier,'deckId':deck['id'],'versionId':version['id'],'publishedVersionId':None,'state':'active','stale':False,'order':time.time()}
        return self.repo.put(conn,owner,'cards',card,parent=deck['id'],new=True)
    def append(self,conn,owner,deck,result,manifest,task_id):
        if deck['status'] in {'deleted','archived'}:fail('invalid_state','Restore the deck before appending cards.',409)
        if task_id in deck.get('generationRuns',[]):return deck
        old_sources={s['id']:s for s in deck['coverage']['sources']}
        old_sources.update({s['id']:{k:v for k,v in s.items() if k!='text'} for s in manifest['sources']})
        deck['coverage']['sources']=list(old_sources.values())
        existing=self.repo.rows(conn,owner,'cards',deck['id'])
        keys=set()
        from difflib import SequenceMatcher
        prompts=[]
        for card in existing:
            version=self.repo.get(conn,owner,'versions',card['versionId']);keys.add(digest([normalized(version['prompt']),normalized(version['answer'])]));prompts.append(normalized(version['prompt']))
        for content in result['cards']:
            key=digest([normalized(content['prompt']),normalized(content['answer'])])
            stale=next((c for c in existing if c.get('stale') and normalized(self.repo.get(conn,owner,'versions',c['versionId'])['prompt'])==normalized(content['prompt'])),None)
            if stale:
                self.repo.put(conn,owner,'candidates',{'id':uid('candidate'),'deckId':deck['id'],'cardId':stale['id'],'status':'pending','reason':'source_corrected','content':content,'taskId':task_id},parent=deck['id'],new=True);continue
            if key in keys:continue
            if any(SequenceMatcher(None,p,normalized(content['prompt'])).ratio()>.86 for p in prompts):
                self.repo.put(conn,owner,'candidates',{'id':uid('candidate'),'deckId':deck['id'],'status':'pending','reason':'possible_duplicate','content':content,'taskId':task_id},parent=deck['id'],new=True);continue
            self.add_card(conn,owner,deck,content);keys.add(key);prompts.append(normalized(content['prompt']))
        for content in result['candidates']:
            self.repo.put(conn,owner,'candidates',{'id':uid('candidate'),'deckId':deck['id'],'status':'pending','reason':content.get('reason'),'content':{k:v for k,v in content.items() if k not in {'reason','validationReason'}},'validationReason':content.get('validationReason'),'taskId':task_id},parent=deck['id'],new=True)
        deck['generationRuns']=deck.get('generationRuns',[])+[task_id];deck['generationVersions']=result['versions'];deck['updatedAt']=time.time()
        old={s['id']:s for s in deck['coverage']['sources']}
        old.update({s['id']:{k:v for k,v in s.items() if k!='text'} for s in manifest['sources']})
        deck['coverage']={'partial':result['partial'],'sources':list(old.values())}
        return self.repo.put(conn,owner,'decks',deck)
    def snapshot(self,conn,owner,identifier,offset=0,limit=100):
        deck=self.repo.get(conn,owner,'decks',identifier)
        if deck['status']=='deleted':fail('not_found','Deck deleted.',404)
        cards=self.repo.rows(conn,owner,'cards',identifier);visible=[c for c in cards if c['state']!='deleted']
        return {**deck,'cards':[{**c,'content':self.repo.get(conn,owner,'versions',c['versionId'])} for c in visible[offset:offset+limit]],'cardCount':len(visible),'nextOffset':offset+limit if offset+limit<len(visible) else None,'candidates':[c for c in self.repo.rows(conn,owner,'candidates',identifier) if c['status']=='pending']}
    def get(self,owner,identifier,offset=0,limit=100):
        with self.repo.transaction(owner) as conn:
            from .class_adapter import migrate_legacy
            migrate_legacy(self.store,conn,owner)
            return self.snapshot(conn,owner,identifier,offset,limit)
    def listing(self,owner,course=None,status=None,offset=0,limit=30):
        with self.repo.transaction(owner) as conn:
            from .class_adapter import migrate_legacy
            migrate_legacy(self.store,conn,owner)
            values=[d for d in self.repo.rows(conn,owner,'decks') if d['status']!='deleted' and (not course or d.get('courseId')==course) and (not status or d['status']==status)]
            values.sort(key=lambda d:d.get('updatedAt',0),reverse=True)
            summaries=[]
            for d in values[offset:offset+limit]:
                cards=self.repo.rows(conn,owner,'cards',d['id']);schedules={s['id']:s for s in self.repo.rows(conn,owner,'schedule',d['id'])}
                d['cardCount']=sum(c['state']!='deleted' for c in cards);d['dueCount']=sum(c['state']=='active' and not c.get('stale') and bool(c.get('publishedVersionId')) and schedules.get(c['id'],{}).get('dueAt',float('inf'))<=time.time() for c in cards)
                summaries.append(d)
            return {'decks':summaries,'nextOffset':offset+limit if offset+limit<len(values) else None}
    def command(self,owner,identifier,body):
        with self.repo.transaction(owner) as conn:
            cached=self.repo.replay(conn,owner,identifier,body)
            if cached is not None:return cached
            deck=self.repo.get(conn,owner,'decks',identifier,True)
            if deck['revision']!=body.expected_revision:fail('revision_conflict','Deck changed. Reload and reconcile your edit.',409)
            if deck['status']=='deleted':fail('invalid_state','This deck was deleted.',409)
            action=body.action
            if action=='rename':
                if not body.title:fail('invalid_input','Provide a title.',422)
                deck['title']=body.title
            elif action in {'archive','restore','delete'}:
                deck['status']={'archive':'archived','restore':'published' if any(c.get('publishedVersionId') for c in self.repo.rows(conn,owner,'cards',identifier)) else 'draft','delete':'deleted'}[action]
                if action=='delete':
                    for session in self.repo.rows(conn,owner,'sessions'):
                        if any(p['deckId']==identifier for p in session['selection']) and session['status']=='active':session['status']='cancelled';self.repo.put(conn,owner,'sessions',session)
            elif action in {'accept_candidate','dismiss_candidate'}:
                candidate=self.repo.get(conn,owner,'candidates',body.candidate_id)
                if candidate['deckId']!=identifier or candidate['status']!='pending':fail('invalid_state','Candidate unavailable.',409)
                if action=='accept_candidate':
                    if candidate.get('cardId'):
                        card=self.repo.get(conn,owner,'cards',candidate['cardId'],True)
                        version={'id':uid('fcv'),'cardId':card['id'],**candidate['content'],'contentHash':digest(candidate['content']),'creatorKind':'student_accepted','createdAt':time.time(),'sourceRefs':[s for s in deck['coverage']['sources'] if s['id'] in candidate['content']['sourceIds']]}
                        self.repo.put(conn,owner,'versions',version,parent=identifier,new=True);card['versionId']=version['id'];card['stale']=False;self.repo.put(conn,owner,'cards',card)
                    else:self.add_card(conn,owner,deck,candidate['content'],'student_accepted')
                candidate['status']='accepted' if action=='accept_candidate' else 'dismissed';self.repo.put(conn,owner,'candidates',candidate)
            else:
                ids=body.card_ids if action=='publish' else [body.card_id]
                if not ids:fail('invalid_input','Choose cards.',422)
                for cid in sorted(set(ids)):
                    card=self.repo.get(conn,owner,'cards',cid,True)
                    if card['deckId']!=identifier or card['state']=='deleted':fail('not_found','Card unavailable in this deck.',404)
                    if action=='edit':
                        if not body.content:fail('invalid_input','Provide card content.',422)
                        content=body.content.model_dump(by_alias=True)
                        allowed={s['id'] for s in deck['coverage']['sources']}
                        if not set(content['sourceIds'])<=allowed:fail('invalid_input','Choose cited sources belonging to this deck.',422)
                        version={'id':uid('fcv'),'cardId':cid,**content,'contentHash':digest(content),'creatorKind':'student','createdAt':time.time()}
                        self.repo.put(conn,owner,'versions',version,parent=identifier,new=True);card['versionId']=version['id'];card['stale']=False
                    elif action=='publish':
                        if deck['status']=='archived' or card.get('stale'):fail('invalid_state','Restore or revalidate cards before publication.',409)
                        card['publishedVersionId']=card['versionId'];deck['status']='published'
                    elif action in {'suspend','activate','remove'}:card['state']={'suspend':'suspended','activate':'active','remove':'deleted'}[action]
                    schedules=self.repo.rows(conn,owner,'schedule',identifier);schedule=next((s for s in schedules if s['id']==cid),None)
                    if action=='publish' and schedule is None or action=='reset_schedule' or body.reset_schedule:
                        value={'id':cid,'deckId':identifier,'dueAt':time.time(),'intervalDays':1.0,'reviewCount':0,'successes':0,'failures':0,'difficulty':.5,'schedulerVersion':'flashcard-rating-v1/review-scheduler-v1'}
                        if schedule:value['revision']=schedule['revision']
                        self.repo.put(conn,owner,'schedule',value,parent=identifier,new=schedule is None)
                    self.repo.put(conn,owner,'cards',card)
            deck['updatedAt']=time.time();self.repo.put(conn,owner,'decks',deck)
            result={'deckId':identifier,'revision':deck['revision']+1,'status':deck['status']}
            return self.repo.receipt(conn,owner,identifier,body,result)
