"""Owned schedules, atomic fire claims, and notification delivery."""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from sqlalchemy import text
from .identity import assert_owner_active, fail
from .workflow_store import WorkflowStore, uid, encoded
from .reminder_schedule import parse_when, next_fire, local_instant
from .reminder_actions import ActionSpec, build_registry, ReminderActionRunner


class ReminderCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    when: str | None = Field(default=None,max_length=200)
    message: str = Field(min_length=1,max_length=2000)
    timezone: str = Field(default='America/Los_Angeles',max_length=100)
    schedule: dict | None = None
    channels: list[Literal['inbox','desktop','push','expo','email']] = Field(default_factory=lambda:['inbox'],min_length=1,max_length=5)
    actions: list[ActionSpec] = Field(default_factory=list,max_length=5)
    condition: dict | None = None
    prompt: str | None = Field(default=None,max_length=1000)
    sessionId: str | None = None
    courseId: str | None = None
    buddyId: str | None = None
    maxFires: int = Field(default=1000,ge=1,le=10000)
    expiresAt: float | None = None
    quietStart: int = Field(default=22,ge=0,le=23)
    quietEnd: int = Field(default=8,ge=0,le=23)
    catchupMinutes: int = Field(default=120,ge=1,le=1440)

    @model_validator(mode='after')
    def timing(self):
        try:ZoneInfo(self.timezone)
        except (ValueError,KeyError):raise ValueError('Choose a valid IANA timezone.')
        if bool(self.when)==bool(self.schedule):raise ValueError('Choose a one-time date or a recurring schedule.')
        if self.schedule and self.schedule.get('type') not in {'cron','rrule'}:raise ValueError('Use cron or rrule.')
        if self.schedule and self.schedule['type']=='cron' and len(str(self.schedule.get('cron','')).split())!=5:raise ValueError('Use a five-field cron expression.')
        if self.schedule and self.schedule['type']=='rrule' and not self.schedule.get('startsAt'):raise ValueError('RRULE schedules require startsAt with a UTC offset.')
        if self.prompt and not self.actions:
            self.actions=[ActionSpec(type='skill',skillId='digest.learning',args={'prompt':self.prompt}),ActionSpec(type='notify')]
        if self.condition:
            name=self.condition.get('type')
            names={'cards_due':'condition.cards_due','no_study_session_since':'condition.no_study_session_since'}
            if name not in names:raise ValueError('Unsupported reminder condition.')
            gate=ActionSpec(type='condition',skillId=names[name],args={k:v for k,v in self.condition.items() if k!='type'})
            if not self.actions or self.actions[0]!=gate:self.actions=[gate,*self.actions]
        if len(self.actions)>5:raise ValueError('Use at most five reminder actions, including conditions.')
        return self


class ReminderService:
    def __init__(self,store):self.store=store
    def preferences(self,owner):
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            payload=conn.execute(text('SELECT payload FROM reminder_preferences WHERE owner_id=:owner'),{'owner':owner}).scalar_one_or_none()
        return json.loads(payload) if payload else {'timezone':'America/Los_Angeles','quietStart':22,'quietEnd':8,'channels':['inbox'],'emailOptIn':False}

    def listing(self,owner,status=None):
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            rows=conn.execute(text('SELECT * FROM reminders WHERE owner_id=:owner AND (:status IS NULL OR status=:status) ORDER BY due_at DESC LIMIT 200'),{'owner':owner,'status':status}).mappings().all()
            policies=conn.execute(text("SELECT * FROM reminder_policies WHERE owner_id=:owner AND kind='routine'"),{'owner':owner}).mappings().all()
        return {'reminders':[self.public(row) for row in rows],'routines':[{'id':r['id'],'revision':r['revision'],'active':r['active'],**json.loads(r['payload'])} for r in policies]}

    @staticmethod
    def public(row):
        payload=json.loads(row['payload'])
        return {'id':row['id'],'kind':row['kind'],'status':row['status'],'dueAt':row['due_at'],'policyId':row['policy_id'],'lastError':row['last_error'],**payload}

    def create_once(self,owner,command,key):return self.create(owner,command,key)
    def create_routine(self,owner,command,key):return self.create(owner,command,key)
    def create(self,owner,command,key):
        if os.getenv('OPENLEARN_CHAT_REMINDERS')!='true':fail('capability_unavailable','Chat reminders are not enabled on this server.',503)
        if not key or len(key)>160:fail('invalid_input','Provide an Idempotency-Key.',422)
        try:build_registry(self.store).validate(command.actions)
        except ValueError:fail('invalid_action','Check the scheduled action arguments.',422)
        if any(a.type=='buddy_message' for a in command.actions) and not command.sessionId:fail('session_required','Choose a conversation for the Buddy message.',422)
        if 'email' in command.channels and not self.preferences(owner).get('emailOptIn'):fail('email_not_enabled','Enable email notifications first.',422)
        data=command.model_dump(); digest=hashlib.sha256(encoded(data).encode()).hexdigest()
        identifier='reminder_'+hashlib.sha256(f'{owner}:{key}'.encode()).hexdigest()[:32]
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            previous=conn.execute(text('SELECT * FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if previous:
                if json.loads(previous['payload']).get('requestHash')!=digest:fail('idempotency_conflict','That request key has different content.',409)
                return self.public(previous)
        now=time.time()
        try:
            due=next_fire(command.schedule,command.timezone,now) if command.schedule else parse_when(command.when,command.timezone,now)
            if due is None or due<=now:raise ValueError('Choose a future reminder time.')
            if command.schedule:
                previous=due
                for _ in range(50):
                    second=next_fire(command.schedule,command.timezone,previous)
                    if second is None:break
                    if second-previous<300:raise ValueError('Recurring reminders must be at least five minutes apart.')
                    previous=second
        except (ValueError,KeyError,TypeError) as exc:fail('invalid_time',str(exc),422)
        data=command.model_dump(); digest=hashlib.sha256(encoded(data).encode()).hexdigest()
        identifier='reminder_'+hashlib.sha256(f'{owner}:{key}'.encode()).hexdigest()[:32]
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            # Serialize per-user cap checks without a process-local lock.
            from .buddy_service import BuddyService
            buddy_service=BuddyService(self.store);buddy_service.ensure(conn,owner)
            conn.execute(text('UPDATE buddy_profiles SET payload=payload WHERE owner_id=:owner'),{'owner':owner})
            existing=conn.execute(text('SELECT * FROM reminders WHERE owner_id=:owner AND id=:id'),{'owner':owner,'id':identifier}).mappings().first()
            if existing:
                if json.loads(existing['payload']).get('requestHash')!=digest:fail('idempotency_conflict','That request key has different content.',409)
                return self.public(existing)
            if command.sessionId:
                if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'),{'id':command.sessionId,'owner':owner}).first():fail('not_found','Conversation unavailable.',404)
            if command.courseId:
                from .browser_assistant.policy import require_course
                require_course(conn,owner,command.courseId)
            if command.buddyId:buddy_service.profile(conn,owner,command.buddyId)
            for action in command.actions:
                if action.args.get('sessionId'):
                    if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'),{'id':action.args['sessionId'],'owner':owner}).first():fail('not_found','Action conversation unavailable.',404)
                if action.args.get('courseId'):
                    from .browser_assistant.policy import require_course
                    require_course(conn,owner,action.args['courseId'])
            kind='routine' if command.schedule else 'chat'
            count=conn.execute(text("SELECT count(*) FROM reminder_policies WHERE owner_id=:owner AND kind='routine' AND active=true"),{'owner':owner}).scalar_one() if command.schedule else conn.execute(text("SELECT count(*) FROM reminders WHERE owner_id=:owner AND kind=:kind AND status IN ('pending','delivering')"),{'owner':owner,'kind':kind}).scalar_one()
            if count >= (20 if command.schedule else 50):fail('reminder_limit','You have reached the active reminder limit.',409)
            policy=None
            if command.schedule:
                policy='policy_'+identifier
                data.update(fireCount=0,requestHash=digest)
                conn.execute(text("INSERT INTO reminder_policies(id,owner_id,revision,active,kind,payload) VALUES(:id,:owner,1,true,'routine',:payload)"),{'id':policy,'owner':owner,'payload':encoded(data)})
                due=self.shift_quiet(due,data)
            payload={**data,'title':command.message[:200],'body':command.message,'url':'/chat?view=reminders','requestHash':digest}
            self.insert_fire(conn,owner,identifier,kind,due,payload,policy,1 if policy else None)
            buddy_service.responsibility(conn,owner,identifier,'reminder',command.courseId)
            if command.buddyId:conn.execute(text('UPDATE buddy_responsibilities SET buddy_id=:buddy WHERE id=:id AND owner_id=:owner'),{'buddy':command.buddyId,'id':identifier,'owner':owner})
        return {'id':identifier,'kind':kind,'status':'pending','dueAt':due,'policyId':policy,**payload}

    def insert_fire(self,conn,owner,identifier,kind,due,payload,policy=None,revision=None):
        conn.execute(text("INSERT INTO reminders(id,owner_id,kind,policy_id,policy_revision,due_at,status,dedup_key,payload) VALUES(:id,:owner,:kind,:policy,:revision,:due,'pending',:key,:payload) ON CONFLICT(owner_id,dedup_key) DO NOTHING"),{'id':identifier,'owner':owner,'kind':kind,'policy':policy,'revision':revision,'due':due,'key':hashlib.sha256(identifier.encode()).hexdigest(),'payload':encoded(payload)})

    @staticmethod
    def shift_quiet(due,data):
        local=datetime.fromtimestamp(due,ZoneInfo(data['timezone']));start,end=data['quietStart'],data['quietEnd']
        if start!=end and (start<=local.hour<end if start<end else local.hour>=start or local.hour<end):
            wall=local.replace(tzinfo=None,hour=end,minute=0,second=0,microsecond=0)
            if wall<=local.replace(tzinfo=None):wall+=timedelta(days=1)
            return local_instant(wall,data['timezone'])
        return due

    def cancel(self,owner,identifier):
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text('SELECT * FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if not row:fail('not_found','Reminder unavailable.',404)
            if row['kind']=='routine':
                conn.execute(text('UPDATE reminder_policies SET active=false,revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':row['policy_id'],'owner':owner})
                conn.execute(text("UPDATE reminders SET status='cancelled' WHERE policy_id=:id AND owner_id=:owner AND status IN ('pending','delivering')"),{'id':row['policy_id'],'owner':owner})
            else:conn.execute(text("UPDATE reminders SET status='cancelled' WHERE id=:id AND owner_id=:owner AND status IN ('pending','delivering')"),{'id':identifier,'owner':owner})
        return {'status':'cancelled'}

    def snooze(self,owner,identifier,minutes,key):
        if not 1<=minutes<=10080:fail('invalid_input','Snooze between one minute and one week.',422)
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text('SELECT * FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if not row:fail('not_found','Reminder unavailable.',404)
            payload=json.loads(row['payload']);payload.update(actions=[],schedule=None,when=None)
            identifier='snooze_'+hashlib.sha256(f'{owner}:{identifier}:{key}'.encode()).hexdigest()[:32]
            existing=conn.execute(text('SELECT payload FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).scalar_one_or_none()
            if existing:
                if json.loads(existing).get('snoozeMinutes')!=minutes:fail('idempotency_conflict','That snooze request has different content.',409)
                return {'id':identifier,'status':'pending'}
            payload['snoozeMinutes']=minutes
            self.insert_fire(conn,owner,identifier,'chat',time.time()+minutes*60,payload)
            conn.execute(text("UPDATE reminders SET status='cancelled' WHERE id=:id AND owner_id=:owner AND kind<>'routine' AND status='pending'"),{'id':row['id'],'owner':owner})
        return {'id':identifier,'status':'pending'}

    def control_routine(self,owner,identifier,revision,action,command=None):
        if action=='edit':
            if not command or not command.schedule:fail('invalid_input','Provide an updated recurring reminder.',422)
            build_registry(self.store).validate(command.actions)
            first=next_fire(command.schedule,command.timezone,time.time())
            if first is None:fail('invalid_time','This routine has no future occurrences.',422)
            second=next_fire(command.schedule,command.timezone,first)
            if second and second-first<300:fail('invalid_time','Recurring reminders must be at least five minutes apart.',422)
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text("SELECT * FROM reminder_policies WHERE id=:id AND owner_id=:owner AND kind='routine'"),{'id':identifier,'owner':owner}).mappings().first()
            if not row:fail('not_found','Routine unavailable.',404)
            if row['revision']!=revision:fail('revision_conflict','Refresh this routine before changing it.',409)
            data=json.loads(row['payload']);active=action=='resume' or action=='edit' and row['active']
            if command:
                if command.courseId!=data.get('courseId') or command.sessionId!=data.get('sessionId'):fail('scope_denied','Create a new routine to change its conversation or course.',409)
                data={**command.model_dump(),'fireCount':data.get('fireCount',0)}
            conn.execute(text('UPDATE reminder_policies SET active=:active,revision=revision+1,payload=:payload WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner,'active':active,'payload':encoded(data)})
            conn.execute(text("UPDATE reminders SET status='cancelled' WHERE policy_id=:id AND owner_id=:owner AND status IN ('pending','delivering')"),{'id':identifier,'owner':owner})
            if active:
                due=next_fire(data['schedule'],data['timezone'],time.time())
                if due is None:fail('schedule_complete','This routine has no future occurrences.',409)
                due=self.shift_quiet(due,data)
                payload={**data,'title':data['message'][:200],'body':data['message'],'url':'/chat?view=reminders'}
                self.insert_fire(conn,owner,uid('fire'),'routine',due,payload,identifier,revision+1)
        return {'id':identifier,'active':active,'revision':revision+1}

    def tick(self,now=None,limit=100):
        started=time.monotonic()
        now=time.time() if now is None else now;counts={'claimed':0,'expired':0}
        with self.store.transaction() as conn:
            suffix=' FOR UPDATE SKIP LOCKED' if conn.dialect.name=='postgresql' else ''
            rows=conn.execute(text("SELECT * FROM reminders WHERE kind<>'academic' AND status='pending' AND due_at<=:now ORDER BY due_at LIMIT :limit"+suffix),{'now':now,'limit':limit}).mappings().all()
            for row in rows:
                assert_owner_active(conn,row['owner_id'])
                payload=json.loads(row['payload']);policy=None
                if row['policy_id']:
                    policy=conn.execute(text('SELECT * FROM reminder_policies WHERE id=:id AND owner_id=:owner'),{'id':row['policy_id'],'owner':row['owner_id']}).mappings().first()
                    if not policy or not policy['active'] or policy['revision']!=row['policy_revision']:
                        conn.execute(text("UPDATE reminders SET status='cancelled' WHERE id=:id"),{'id':row['id']});continue
                expired=now>row['due_at']+payload['catchupMinutes']*60 or payload.get('expiresAt') and now>payload['expiresAt']
                status='expired' if expired else 'delivering'
                claimed=conn.execute(text("UPDATE reminders SET status=:status,attempt_count=attempt_count+1 WHERE id=:id AND status='pending'"),{'status':status,'id':row['id']}).rowcount
                if not claimed:continue
                counts['expired' if expired else 'claimed']+=1
                if not expired:WorkflowStore(self.store).enqueue(row['owner_id'],row['id'],'reminder_actions',{},'reminder-actions:'+row['id'],connection=conn)
                if policy:
                    data=json.loads(policy['payload']);data['fireCount']=data.get('fireCount',0)+1
                    due=next_fire(data['schedule'],data['timezone'],max(now,row['due_at']))
                    if due is not None:due=self.shift_quiet(due,data)
                    active=due is not None and data['fireCount']<data['maxFires'] and (not data.get('expiresAt') or due<data['expiresAt'])
                    conn.execute(text('UPDATE reminder_policies SET active=:active,payload=:payload WHERE id=:id'),{'id':policy['id'],'active':active,'payload':encoded(data)})
                    if active:
                        identifier='fire_'+hashlib.sha256(f"{policy['id']}:{policy['revision']}:{due}".encode()).hexdigest()[:32]
                        self.insert_fire(conn,row['owner_id'],identifier,'routine',due,payload,policy['id'],policy['revision'])
            counts['durationMs']=round((time.monotonic()-started)*1000)
            conn.execute(text("INSERT INTO reminder_runtime(id,last_tick,payload) VALUES('scheduler',:now,:payload) ON CONFLICT(id) DO UPDATE SET last_tick=excluded.last_tick,payload=excluded.payload"),{'now':now,'payload':encoded(counts)})
        self.reconcile()
        return counts

    def reconcile(self):
        # Durable completion bridge also catches completions during worker restarts.
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT a.fire_id,a.job_id,a.owner_id,r.status,r.payload FROM reminder_action_runs a JOIN assistant_runs r ON r.id=a.job_id AND r.owner_id=a.owner_id WHERE a.status='waiting' LIMIT 100")).mappings().all()
        runner=ReminderActionRunner(self.store)
        for row in rows:runner.resume(row['fire_id'],row['job_id'],row['status'],json.loads(row['payload']))
        with self.store.engine.connect() as conn:
            failed=conn.execute(text("SELECT r.* FROM reminders r JOIN learning_jobs j ON j.target_id=r.id AND j.owner_id=r.owner_id WHERE r.status='delivering' AND j.kind='reminder_actions' AND j.status='failed' LIMIT 100")).mappings().all()
        for row in failed:
            Notifier(self.store).deliver(row,{**json.loads(row['payload']),'body':'Your scheduled activity needs attention. Open Open Learn to review it.'},ActionSpec(type='notify'))
            with self.store.transaction() as conn:
                conn.execute(text("UPDATE reminders SET status='failed',last_error='worker_failed' WHERE id=:id AND status='delivering'"),{'id':row['id']})


class Notifier:
    def __init__(self,store):self.store=store
    def deliver(self,row,context,action):
        def render(value):
            return re.sub(r'\{\{(\w+)\}\}',lambda m:str(context.get(m[1],'')),value)
        payload={'id':row['id'],'title':render(action.title or context.get('title','Reminder'))[:200],'body':render(action.bodyTemplate or context.get('body','Your activity is ready.'))[:2000],'url':render(action.urlTemplate or context.get('deepLink') or context.get('url','/chat?view=reminders'))}
        if not payload['url'].startswith('/') or payload['url'].startswith('//'):payload['url']='/chat?view=reminders'
        channels=set(action.channels or context.get('channels',['inbox']))|{'inbox'}
        payload.update(channels=sorted(channels),catchupMinutes=context.get('catchupMinutes',120))
        with self.store.transaction() as conn:
            assert_owner_active(conn,row['owner_id'])
            state=conn.execute(text('SELECT status FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':row['owner_id']}).scalar_one()
            if state!='delivering':return {}
            from .buddy_service import BuddyService
            BuddyService(self.store).responsibility(conn,row['owner_id'],row['id'],'reminder',context.get('courseId'))
            if action.type=='buddy_message':
                session=context.get('sessionId')
                if not session or not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'),{'id':session,'owner':row['owner_id']}).first():fail('not_found','Buddy conversation unavailable.',404)
                identifier='buddy_notice_'+row['id']
                if not conn.execute(text('SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':row['owner_id']}).first():
                    WorkflowStore(self.store).put(conn,row['owner_id'],'reminder_message',{**payload,'id':identifier,'sessionId':session,'createdAt':time.time()},session)
            for channel in channels:
                identifier='notice_'+hashlib.sha256(f"{row['id']}:{channel}".encode()).hexdigest()[:32]
                conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES(:id,:owner,:reminder,:channel,:status,:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING"),{'id':identifier,'owner':row['owner_id'],'reminder':row['id'],'channel':channel,'status':'available' if channel=='inbox' else 'pending','payload':encoded(payload),'now':time.time()})
                if channel in {'push','expo','email'}:WorkflowStore(self.store).enqueue(row['owner_id'],identifier,'general_reminder_dispatch',{},'dispatch:'+identifier,connection=conn,max_attempts=3)
        return {'notificationUrl':payload['url']}
