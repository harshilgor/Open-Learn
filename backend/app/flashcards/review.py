"""Version-pinned recall; one atomic schedule outcome, never automatic mastery."""
import time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from ..identity import fail
from ..workflow_store import uid
from ..review.scheduler import MemorySnapshot,schedule_after_outcome
from .repository import Repository
class ReviewService:
    def __init__(self,store):self.repo=Repository(store)
    def public(self,conn,owner,session):
        result={k:v for k,v in session.items() if k not in {'selection','response'}}
        result['total']=len(session['selection']);result['current']=None
        if session['status']=='active' and session['cursor']<len(session['selection']):
            pick=session['selection'][session['cursor']];version=self.repo.get(conn,owner,'versions',pick['versionId'])
            prompt=version['prompt']
            if version['type']=='cloze':
                import re
                prompt=re.sub(r'\{\{c1::[^{}]+\}\}','[…] ',prompt)
            result['current']={'cardId':pick['cardId'],'deckId':pick['deckId'],'versionId':pick['versionId'],'attemptId':pick['attemptId'],'type':version['type'],'prompt':prompt,'revealed':session['revealed']}
            if session['revealed']:result['current'].update(answer=version['answer'],explanation=version['explanation'],sourceIds=version['sourceIds'],response=session.get('response',''))
        return result
    def get(self,owner,identifier):
        with self.repo.transaction(owner) as conn:return self.public(conn,owner,self.repo.get(conn,owner,'sessions',identifier))
    def create(self,owner,body):
        try:ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:fail('invalid_timezone','Choose a valid review timezone.',422)
        with self.repo.transaction(owner) as conn:
            cached=self.repo.replay(conn,owner,'review-create',body)
            if cached is not None:return self.public(conn,owner,self.repo.get(conn,owner,'sessions',cached['sessionId']))
            picks=[]
            for deck in self.repo.rows(conn,owner,'decks'):
                if deck['status']!='published' or body.deck_id and deck['id']!=body.deck_id or body.course_id and deck.get('courseId')!=body.course_id:continue
                deck=self.repo.get(conn,owner,'decks',deck['id'],True)
                schedules={s['id']:s for s in self.repo.rows(conn,owner,'schedule',deck['id'])}
                for card in self.repo.rows(conn,owner,'cards',deck['id']):
                    state=schedules.get(card['id'])
                    if card['state']!='active' or card.get('stale') or not card.get('publishedVersionId') or not state or not body.practice and state['dueAt']>time.time():continue
                    picks.append({'cardId':card['id'],'deckId':deck['id'],'versionId':card['publishedVersionId'],'scheduleRevision':state['revision'],'attemptId':uid('fca'),'dueAt':state['dueAt']})
            if not picks:fail('nothing_due','No published cards available for this review.',409)
            picks.sort(key=lambda p:(p['dueAt'],p['cardId']))
            session={'id':uid('fcr'),'selection':picks[:body.limit],'cursor':0,'status':'active','revealed':False,'response':'','practice':body.practice,'timezone':body.timezone,'createdAt':time.time()}
            session=self.repo.put(conn,owner,'sessions',session,parent=body.deck_id,new=True)
            self.repo.receipt(conn,owner,'review-create',body,{'sessionId':session['id']})
            return self.public(conn,owner,session)
    def command(self,owner,identifier,body):
        with self.repo.transaction(owner) as conn:
            cached=self.repo.replay(conn,owner,identifier,body)
            if cached is not None:return cached
            session=self.repo.get(conn,owner,'sessions',identifier,True)
            if session['revision']!=body.expected_revision or session['status']!='active':fail('revision_conflict','Review advanced elsewhere. Reload your session.',409)
            pick=session['selection'][session['cursor']]
            if pick['attemptId']!=body.attempt_id:fail('revision_conflict','This attempt is no longer current.',409)
            deck=self.repo.get(conn,owner,'decks',pick['deckId'],True)
            card=self.repo.get(conn,owner,'cards',pick['cardId'],True)
            if deck['status']!='published' or card['state']!='active':fail('invalid_state','This card is no longer reviewable.',409)
            if body.action=='reveal':session['revealed']=True;session['response']=body.response
            else:
                if body.action=='rate' and (not session['revealed'] or not body.rating):fail('answer_not_revealed','Reveal the answer before rating recall.',409)
                state=self.repo.get(conn,owner,'schedule',pick['cardId'],True)
                if body.action=='rate' and (state['revision']!=pick['scheduleRevision'] or card.get('stale')):fail('schedule_conflict','This card was reviewed or corrected elsewhere. Skip it or start a new session.',409)
                if body.action=='rate' and not session['practice']:
                    outcome,confidence={'again':('incorrect','somewhat'),'hard':('partial','somewhat'),'good':('correct','confident'),'easy':('correct','very')}[body.rating]
                    decision=schedule_after_outcome(outcome=outcome,confidence=confidence,condition='independent',memory=MemorySnapshot(review_count=state['reviewCount'],last_interval_days=state['intervalDays'],consecutive_successes=state['successes'],consecutive_failures=state['failures'],difficulty_estimate=state['difficulty']))
                    state.update(dueAt=decision.due_at.timestamp(),intervalDays=decision.interval_days,successes=decision.consecutive_successes,failures=decision.consecutive_failures,difficulty=decision.difficulty_estimate,reviewCount=state['reviewCount']+1,lastReviewedAt=time.time(),schedulerVersion='flashcard-rating-v1/'+decision.scheduler_version,reviewDay=datetime.now(ZoneInfo(session['timezone'])).date().isoformat())
                    self.repo.put(conn,owner,'schedule',state)
                attempt={'id':pick['attemptId'],'sessionId':identifier,'deckId':pick['deckId'],'cardId':pick['cardId'],'versionId':pick['versionId'],'revealed':session['revealed'],'response':session.get('response',''),'rating':body.rating if body.action=='rate' else None,'skipped':body.action=='skip','practice':session['practice'],'evidenceQualified':False,'createdAt':time.time(),'commandId':body.command_id}
                self.repo.put(conn,owner,'attempts',attempt,parent=pick['deckId'],new=True)
                session['cursor']+=1;session['revealed']=False;session['response']=''
                if session['cursor']==len(session['selection']):session['status']='completed';session['completedAt']=time.time()
            session=self.repo.put(conn,owner,'sessions',session)
            return self.repo.receipt(conn,owner,identifier,body,self.public(conn,owner,session))
    def summary(self,owner):
        with self.repo.transaction(owner) as conn:
            courses={};due=0
            for deck in self.repo.rows(conn,owner,'decks'):
                if deck['status']!='published':continue
                schedules={s['id']:s for s in self.repo.rows(conn,owner,'schedule',deck['id'])}
                count=sum(c['state']=='active' and not c.get('stale') and bool(c.get('publishedVersionId')) and schedules.get(c['id'],{}).get('dueAt',float('inf'))<=time.time() for c in self.repo.rows(conn,owner,'cards',deck['id']))
                due+=count;key=deck.get('courseId') or 'uncategorized';courses[key]=courses.get(key,0)+count
            sessions=self.repo.rows(conn,owner,'sessions')
            return {'dueCount':due,'courses':courses,'sessions':[{'id':s['id'],'status':s['status'],'cursor':s['cursor'],'total':len(s['selection']),'createdAt':s['createdAt']} for s in sessions[-30:]]}
