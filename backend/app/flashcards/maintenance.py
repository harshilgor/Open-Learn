"""Preference-controlled inbox reminders and bounded assessment draft preparation."""
import json,time,logging
from datetime import datetime,timezone,date
from zoneinfo import ZoneInfo
from sqlalchemy import text
from fastapi import HTTPException
from .repository import Repository,digest
from .review import ReviewService
from .contracts import FlashcardRequest
from ..agent_execution.contracts import Message
from ..agent_execution.coordinator import Coordinator
from ..agent_execution.config import admission_enabled
from ..workflow_store import encoded
log=logging.getLogger(__name__)
class FlashcardMaintenance:
    def __init__(self,store):self.store=store;self.repo=Repository(store)
    def tick(self):
        with self.store.engine.connect() as conn:owners=conn.execute(text('SELECT DISTINCT owner_id FROM flashcard_preferences')).scalars().all()
        for owner in owners[:100]:
            try:self.owner_tick(owner)
            except Exception:log.exception('Flashcard maintenance needs retry')
    def owner_tick(self,owner):
        with self.repo.transaction(owner) as conn:prefs=self.repo.rows(conn,owner,'preferences')[0]
        zone=ZoneInfo(prefs.get('timezone','UTC'));day=datetime.now(zone).date().isoformat()
        if prefs.get('reminders'):
            summary=ReviewService(self.store).summary(owner)
            if summary['dueCount']:
                key='fc_notice_'+digest([owner,day])[:32]
                payload={'title':'Flashcards ready for recall','body':f"{summary['dueCount']} cards due. Review when you have time.",'url':'/?flashcards=library','kind':'flashcard_due'}
                with self.repo.transaction(owner) as conn:
                    conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES(:id,:owner,:id,'inbox','available',:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING"),{'id':key,'owner':owner,'payload':encoded(payload),'now':time.time()})
        if not prefs.get('proactiveDrafts') or not admission_enabled():return
        with self.store.engine.connect() as conn:
            assessments=[json.loads(p) for p in conn.execute(text("SELECT payload FROM academic_entities WHERE owner_id=:owner"),{'owner':owner}).scalars()]
        for assessment in assessments:
            if assessment.get('kind')!='assessment':continue
            facts=assessment.get('facts',{});due=facts.get('due',{}).get('value') or facts.get('date',{}).get('value')
            if not due or facts.get('completed',{}).get('value') or facts.get('cancelled',{}).get('value'):continue
            raw=due.get('value') if isinstance(due,dict) else due
            try:
                when=datetime.fromisoformat(raw.replace('Z','+00:00'))
                if when.tzinfo:remaining=(when.astimezone(zone).date()-datetime.now(zone).date()).days
                else:remaining=(when.date()-datetime.now(zone).date()).days
            except (ValueError,AttributeError):continue
            if not 0<=remaining<=3:continue
            course=assessment.get('courseId')
            with self.store.engine.connect() as conn:
                session=conn.execute(text('SELECT id FROM learning_sessions WHERE learner_id=:owner AND course_id=:course ORDER BY updated_at DESC LIMIT 1'),{'owner':owner,'course':course}).scalar_one_or_none()
                notes=conn.execute(text('SELECT id,revision FROM workspace_notes WHERE learner_id=:owner AND course_id=:course ORDER BY updated_at DESC LIMIT 10'),{'owner':owner,'course':course}).all()
            if not session or not notes:continue
            key='fc_prep_'+digest([owner,assessment['id'],assessment.get('revision')])[:32]
            spec=FlashcardRequest(sessionId=session,courseId=course,origin='conversation',sourceRefs=[{'kind':'note','id':n[0],'revision':n[1]} for n in notes],objective='Prepare a draft for '+str(facts.get('title',{}).get('value','the upcoming assessment'))[:500],clientCommandId=key)
            # Once admitted, source snapshots stay authoritative even if notes later change.
            with self.store.engine.connect() as conn:
                if conn.execute(text('SELECT 1 FROM agent_messages WHERE owner_id=:owner AND client_message_id=:key'),{'owner':owner,'key':key}).first():continue
            try:Coordinator(self.store).admit(owner,Message(clientMessageId=key,sessionId=session,text=spec.objective,capability='flashcards',flashcardSpec=spec),key)
            except HTTPException as exc:
                if exc.status_code not in {409,422,429}:raise
            break
