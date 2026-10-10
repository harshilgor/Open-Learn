"""Companion identity is account scoped; learning resources remain shared."""
import json
import re
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import text
from pydantic import Field
from typing import Literal
from .session_models import ApiModel
from .identity import fail

class BuddyInput(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    avatar: Literal['spark', 'owl', 'cat', 'leaf', 'planet'] = 'spark'
    color: Literal['sage', 'blue', 'violet', 'rose', 'amber'] = 'sage'
    style: Literal['calm', 'encouraging', 'playful', 'direct'] = 'encouraging'
    concise: bool = True
    examples: bool = True
    proactive: bool = False

class BuddyUpdate(BuddyInput):
    expected_revision: int = Field(ge=1)

class BuddyService:
    def __init__(self, store): self.store = store

    def default_id(self, owner): return 'buddy_'+uuid5(NAMESPACE_URL, 'openlearn:'+owner).hex

    def ensure(self, conn, owner):
        identifier = self.default_id(owner)
        # Deterministic identity and conflict-safe insert support concurrent first visits.
        payload = BuddyInput(name='Buddy').model_dump(by_alias=True)
        conn.execute(text('INSERT INTO buddy_profiles(id,owner_id,name,payload,revision,archived) VALUES(:id,:owner,:name,:payload,1,false) ON CONFLICT(id) DO NOTHING'), {'id': identifier, 'owner': owner, 'name': 'Buddy', 'payload': json.dumps(payload)})
        conn.execute(text('INSERT INTO buddy_accounts(id,owner_id,default_buddy_id) VALUES(:owner,:owner,:id) ON CONFLICT(id) DO NOTHING'), {'owner':owner,'id':identifier})
        suffix=' FOR UPDATE' if conn.dialect.name=='postgresql' else ''
        default = conn.execute(text('SELECT default_buddy_id FROM buddy_accounts WHERE owner_id=:owner'+suffix), {'owner':owner}).scalar_one()
        return default

    def profile(self, conn, owner, identifier, active=False):
        row = conn.execute(text('SELECT * FROM buddy_profiles WHERE id=:id AND owner_id=:owner'), {'id':identifier,'owner':owner}).mappings().first()
        if not row or (active and row['archived']): fail('buddy_unavailable', 'This Buddy is unavailable.', 404)
        try:preferences=BuddyInput.model_validate(json.loads(row['payload'])).model_dump(by_alias=True)
        except ValueError:fail('invalid_profile','This Buddy has invalid saved preferences. Restore a valid profile.',422)
        return {**preferences, 'id':row['id'], 'revision':row['revision'], 'archived':bool(row['archived'])}

    def snapshot(self, owner):
        with self.store.transaction() as conn:
            default = self.ensure(conn, owner)
            conn.execute(text('INSERT INTO buddy_chats(id,owner_id,buddy_id) SELECT id,learner_id,:buddy FROM learning_sessions WHERE learner_id=:owner ON CONFLICT(id) DO NOTHING'), {'buddy':self.default_id(owner),'owner':owner})
            conn.execute(text('INSERT INTO buddy_classes(id,owner_id,buddy_id) SELECT id,learner_id,:buddy FROM lecture_recordings WHERE learner_id=:owner ON CONFLICT(id) DO NOTHING'),{'buddy':self.default_id(owner),'owner':owner})
            profiles = [self.profile(conn,owner,row[0]) for row in conn.execute(text('SELECT id FROM buddy_profiles WHERE owner_id=:owner ORDER BY archived,name,id'), {'owner':owner})]
            return {'profiles':profiles,'defaultBuddyId':default,
                    'courses':dict(conn.execute(text('SELECT id,buddy_id FROM buddy_courses WHERE owner_id=:owner'), {'owner':owner}).tuples().all()),
                    'chats':dict(conn.execute(text('SELECT id,buddy_id FROM buddy_chats WHERE owner_id=:owner'), {'owner':owner}).tuples().all()),
                    'modes':dict(conn.execute(text('SELECT id,presentation FROM buddy_chats WHERE owner_id=:owner'), {'owner':owner}).tuples().all()),
                    'responsibilities':dict(conn.execute(text('SELECT buddy_id,count(*) FROM buddy_responsibilities WHERE owner_id=:owner GROUP BY buddy_id'),{'owner':owner}).tuples().all()),
                    'lastChats':dict(conn.execute(text('SELECT n.id,n.last_chat_id FROM buddy_navigation n JOIN buddy_chats c ON c.id=n.last_chat_id AND c.owner_id=n.owner_id AND c.buddy_id=n.id WHERE n.owner_id=:owner'),{'owner':owner}).tuples().all()),
                    'unread':dict(conn.execute(text("SELECT b.buddy_id,count(*) FROM notification_deliveries n JOIN buddy_responsibilities b ON b.id=n.reminder_id AND b.owner_id=n.owner_id WHERE n.owner_id=:owner AND n.channel='inbox' AND n.status='available' GROUP BY b.buddy_id"),{'owner':owner}).tuples().all()),
                    'classes':[dict(row) for row in conn.execute(text('SELECT c.id AS "classId",r.id,r.title,r.status,r.course_id AS "courseId",r.note_id AS "noteId",r.started_at AS "startedAt",b.buddy_id AS "buddyId" FROM lecture_recordings r LEFT JOIN class_sessions c ON c.recording_id=r.id AND c.owner_id=r.learner_id LEFT JOIN buddy_classes b ON b.id=r.id AND b.owner_id=r.learner_id WHERE r.learner_id=:owner ORDER BY r.started_at DESC LIMIT 100'), {'owner':owner}).mappings()]}

    def create(self, owner, body, key=None):
        if not body.name.strip(): fail('invalid_name','Enter a Buddy name.',422)
        with self.store.transaction() as conn:
            self.ensure(conn,owner)
            identifier='buddy_'+(uuid5(NAMESPACE_URL,owner+':buddy-create:'+key).hex if key else uuid4().hex)
            data=body.model_dump(by_alias=True);data['name']=body.name.strip()
            previous=conn.execute(text('SELECT payload FROM buddy_profiles WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).scalar_one_or_none()
            if previous:
                if json.loads(previous)!=data:fail('idempotency_conflict','This request key already created a different Buddy.',409)
                return self.profile(conn,owner,identifier)
            conn.execute(text('INSERT INTO buddy_profiles(id,owner_id,name,payload,revision,archived) VALUES(:id,:owner,:name,:payload,1,false)'), {'id':identifier,'owner':owner,'name':data['name'],'payload':json.dumps(data)})
            return self.profile(conn,owner,identifier)

    def update(self, owner, identifier, body):
        if not body.name.strip(): fail('invalid_name','Enter a Buddy name.',422)
        with self.store.transaction() as conn:
            self.profile(conn,owner,identifier,True)
            data=body.model_dump(by_alias=True,exclude={'expected_revision'});data['name']=body.name.strip()
            result=conn.execute(text('UPDATE buddy_profiles SET name=:name,payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner AND revision=:revision AND archived=false'), {'id':identifier,'owner':owner,'name':data['name'],'payload':json.dumps(data),'revision':body.expected_revision})
            if result.rowcount!=1: fail('revision_conflict','This Buddy changed. Reload before saving.',409)
            return self.profile(conn,owner,identifier)

    def resolve(self, conn, owner, course=None, explicit=None):
        default=self.ensure(conn,owner)
        if course:
            if not conn.execute(text('SELECT 1 FROM courses WHERE id=:id AND owner_id=:owner'), {'id':course,'owner':owner}).first(): fail('course_not_found','Course unavailable.',404)
        assigned=conn.execute(text('SELECT buddy_id FROM buddy_courses WHERE id=:id AND owner_id=:owner'), {'id':course,'owner':owner}).scalar_one_or_none() if course else None
        return self.profile(conn,owner,explicit or assigned or default,True)['id']

    def bind(self, owner, session, explicit=None):
        with self.store.transaction() as conn:
            row=conn.execute(text('SELECT course_id FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id':session,'owner':owner}).first()
            if not row: fail('session_not_found','Conversation unavailable.',404)
            # Existing attribution is immutable. Reads must not overwrite history.
            existing=conn.execute(text('SELECT buddy_id FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner}).scalar_one_or_none()
            if existing: return existing
            buddy=self.resolve(conn,owner,row[0],explicit)
            conn.execute(text('INSERT INTO buddy_chats(id,owner_id,buddy_id) VALUES(:id,:owner,:buddy) ON CONFLICT(id) DO NOTHING'), {'id':session,'owner':owner,'buddy':buddy})
            return buddy

    def assign(self, owner, course, buddy):
        with self.store.transaction() as conn:
            self.resolve(conn,owner,course,buddy)
            if buddy is None:
                conn.execute(text('DELETE FROM buddy_courses WHERE id=:id AND owner_id=:owner'), {'id':course,'owner':owner})
            else:
                conn.execute(text('INSERT INTO buddy_courses(id,owner_id,buddy_id,revision) VALUES(:id,:owner,:buddy,1) ON CONFLICT(id) DO UPDATE SET buddy_id=:buddy,revision=buddy_courses.revision+1 WHERE buddy_courses.owner_id=:owner'), {'id':course,'owner':owner,'buddy':buddy})
        return self.snapshot(owner)

    def make_default(self, owner, buddy):
        with self.store.transaction() as conn:
            self.ensure(conn,owner);self.profile(conn,owner,buddy,True)
            conn.execute(text('UPDATE buddy_accounts SET default_buddy_id=:buddy WHERE owner_id=:owner'), {'buddy':buddy,'owner':owner})
        return self.snapshot(owner)

    def archive(self, owner, buddy, replacement, revision):
        with self.store.transaction() as conn:
            self.ensure(conn,owner);self.profile(conn,owner,buddy,True)
            if buddy==replacement: fail('invalid_replacement','Choose another Buddy.',422)
            self.profile(conn,owner,replacement,True)
            result=conn.execute(text('UPDATE buddy_profiles SET archived=true,revision=revision+1 WHERE id=:id AND owner_id=:owner AND revision=:revision AND archived=false'), {'id':buddy,'owner':owner,'revision':revision})
            if result.rowcount!=1: fail('revision_conflict','Buddy changed. Reload before archiving.',409)
            conn.execute(text('UPDATE buddy_courses SET buddy_id=:replacement,revision=revision+1 WHERE owner_id=:owner AND buddy_id=:id'), {'replacement':replacement,'owner':owner,'id':buddy})
            conn.execute(text('UPDATE buddy_accounts SET default_buddy_id=:replacement WHERE owner_id=:owner AND default_buddy_id=:id'), {'replacement':replacement,'owner':owner,'id':buddy})
            conn.execute(text('UPDATE buddy_responsibilities SET buddy_id=:replacement WHERE owner_id=:owner AND buddy_id=:id'), {'replacement':replacement,'owner':owner,'id':buddy})
        return self.snapshot(owner)

    def learn_preferences(self, owner, session, message):
        """Remember explicit communication requests, scoped to this owner/Buddy.

        Never store free-form instructions, quoted passages, or inferred traits.
        """
        rules = {
            'concise': [(r'(?:keep (?:your |the )?(?:answers|responses|explanations) short|be concise)', True),
                        (r'(?:give (?:me )?detailed explanations|explain in detail)', False)],
            'examples': [(r'(?:use (?:more )?examples|include examples)', True),
                         (r'(?:stop using examples|no examples|skip examples)', False)],
            'style': [(r'(?:be more direct|use a direct tone)', 'direct'),
                      (r'(?:be more encouraging|use an encouraging tone)', 'encouraging'),
                      (r'(?:use a calm tone)', 'calm'), (r'(?:be more playful|use a playful tone)', 'playful')],
        }
        # Only standalone user requests qualify; surrounding source text is ignored.
        request = (message or '').strip().lower().rstrip('.!')
        updates = {key: value for key, patterns in rules.items() for pattern, value in patterns
                   if re.fullmatch(r'(?:please )?' + pattern + r'(?: from now on)?', request)}
        if not updates: return
        with self.store.transaction() as conn:
            identifier = conn.execute(text('SELECT buddy_id FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner}).scalar_one_or_none()
            if not identifier: return
            profile = self.profile(conn, owner, identifier, True)
            payload = BuddyInput.model_validate({**profile, **updates}).model_dump(by_alias=True)
            conn.execute(text('UPDATE buddy_profiles SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner AND revision=:revision AND archived=false'), {'payload':json.dumps(payload),'id':identifier,'owner':owner,'revision':profile['revision']})

    def instructions(self, owner, session, message=None):
        if message: self.learn_preferences(owner, session, message)
        with self.store.engine.connect() as conn:
            identifier=conn.execute(text('SELECT buddy_id FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner}).scalar_one_or_none()
            if not identifier:return ''
            profile=self.profile(conn,owner,identifier)
            presentation=conn.execute(text('SELECT presentation FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner}).scalar_one()
        # Only validated finite preference values enter model instructions; names stay presentation data.
        return '\nCommunication preferences only (retain all teaching, evidence, and permission rules): adapt to the learner’s current request and demonstrated understanding; ask a brief clarifying question when uncertain. Do not infer personal traits. Current requests override saved defaults. Use a '+profile['style']+' tone. '+('Prefer concise explanations. ' if profile['concise'] else 'Allow developed explanations. ')+('Use relevant examples. ' if profile['examples'] else 'Avoid examples unless requested. ')+('For ordinary answers, converse naturally and prioritize useful next steps; provide detail when requested.' if presentation=='conversation' else 'For Ask, provide developed, structured responses when useful.' if presentation=='ask' else '')

    def presentation(self, owner, session):
        """Return the saved, owner-scoped presentation for response routing."""
        with self.store.engine.connect() as conn:
            value=conn.execute(text('SELECT presentation FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner}).scalar_one_or_none()
        return value if value in {'conversation','ask','learn','quiz'} else 'ask'

    def mode(self, owner, session, mode):
        with self.store.transaction() as conn:
            if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id':session,'owner':owner}).first():fail('session_not_found','Conversation unavailable.',404)
            self.ensure(conn,owner)
            result=conn.execute(text('UPDATE buddy_chats SET presentation=:mode WHERE id=:id AND owner_id=:owner'), {'id':session,'owner':owner,'mode':mode})
            if result.rowcount!=1:fail('session_not_found','Conversation attribution unavailable.',404)
        return {'mode':mode}

    def remember_chat(self,owner,buddy,session):
        with self.store.transaction() as conn:
            self.profile(conn,owner,buddy)
            if not conn.execute(text('SELECT 1 FROM buddy_chats c JOIN learning_sessions s ON s.id=c.id AND s.learner_id=c.owner_id WHERE c.id=:session AND c.owner_id=:owner AND c.buddy_id=:buddy'),{'session':session,'owner':owner,'buddy':buddy}).first():fail('session_not_found','Conversation unavailable for this Buddy.',404)
            conn.execute(text('INSERT INTO buddy_navigation(id,owner_id,last_chat_id) VALUES(:buddy,:owner,:session) ON CONFLICT(id) DO UPDATE SET last_chat_id=:session WHERE buddy_navigation.owner_id=:owner'),{'buddy':buddy,'owner':owner,'session':session})
        return {'lastChatId':session}

    def responsibility(self,conn,owner,identifier,kind,course=None):
        if conn.execute(text('SELECT 1 FROM buddy_responsibilities WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).first():return
        if course and not conn.execute(text('SELECT 1 FROM courses WHERE id=:id AND owner_id=:owner'),{'id':course,'owner':owner}).first():course=None
        buddy=self.resolve(conn,owner,course)
        conn.execute(text('INSERT INTO buddy_responsibilities(id,owner_id,buddy_id,course_id,kind) VALUES(:id,:owner,:buddy,:course,:kind) ON CONFLICT(id) DO NOTHING'),{'id':identifier,'owner':owner,'buddy':buddy,'course':course,'kind':kind})

    def reminders(self,owner):
        with self.store.transaction() as conn:
            self.ensure(conn,owner)
            rows=conn.execute(text('SELECT r.*,e.course_id FROM reminders r LEFT JOIN academic_entities e ON e.id=r.entity_id AND e.owner_id=r.owner_id WHERE r.owner_id=:owner ORDER BY r.due_at'),{'owner':owner}).mappings().all()
            result=[]
            for row in rows:
                self.responsibility(conn,owner,row['id'],'reminder',row['course_id'])
                buddy=conn.execute(text('SELECT buddy_id FROM buddy_responsibilities WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':owner}).scalar_one()
                payload=json.loads(row['payload'])
                result.append({'id':row['id'],'kind':row['kind'],'dueAt':row['due_at'],'status':row['status'],'title':payload.get('title','Academic event'),'body':payload.get('body'),'url':(payload.get('artifacts') or {}).get('deepLink') or payload.get('url'),'courseId':row['course_id'] or payload.get('courseId'),'buddyId':buddy,'entityId':row['entity_id'],'lastError':row['last_error']})
            return {'reminders':result}

    def today(self,owner):
        from datetime import datetime,timezone,date
        now=datetime.now(timezone.utc)
        with self.store.engine.connect() as conn:
            rows=conn.execute(text('SELECT e.id,e.course_id,e.payload FROM academic_entities e JOIN courses c ON c.id=e.course_id AND c.owner_id=e.owner_id WHERE e.owner_id=:owner AND c.archived_at IS NULL'),{'owner':owner}).mappings().all()
        events=[]
        for row in rows:
            entity=json.loads(row['payload']);facts=entity.get('facts',{})
            if facts.get('cancelled',{}).get('value') or facts.get('completed',{}).get('value'):continue
            fact=next((facts.get(key) for key in ('start','due','date') if facts.get(key)),None)
            if not fact or fact.get('conflict'):continue
            value=fact.get('value') or {}
            try:
                if value.get('kind')=='instant':
                    instant=datetime.fromisoformat(value['value'].replace('Z','+00:00'))
                    if not instant.tzinfo or instant<now:continue
                    sort=instant.timestamp()
                elif value.get('kind')=='date_only':
                    day=date.fromisoformat(value['value'])
                    if day<now.date():continue
                    sort=datetime.combine(day,datetime.min.time(),timezone.utc).timestamp()
                else:continue
            except (ValueError,KeyError,TypeError):continue
            events.append({'id':row['id'],'courseId':row['course_id'],'title':str(facts.get('title',{}).get('value') or 'Academic event'),'kind':entity.get('kind'),'when':value,'sort':sort})
        return {'events':[{key:value for key,value in event.items() if key!='sort'} for event in sorted(events,key=lambda e:e['sort'])[:3]]}

    def read_reminders(self,owner,identifiers):
        with self.store.transaction() as conn:
            for identifier in identifiers:
                conn.execute(text("UPDATE notification_deliveries SET status='read' WHERE owner_id=:owner AND reminder_id=:id AND channel='inbox' AND status='available'"),{'owner':owner,'id':identifier})
        return {'status':'read'}
