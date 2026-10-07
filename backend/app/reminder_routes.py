"""Reminder tools shared by chat and the notification center."""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import text
from .material_routes import material_owner
from .identity import fail
from .reminder_service import ReminderService, ReminderCreate


class ChatCommand(BaseModel):
    message: str = Field(min_length=1,max_length=4000)
    timezone: str = Field(default='America/Los_Angeles',max_length=100)
    sessionId: str | None = None
    buddyId: str | None = None
    courseId: str | None = None


class Snooze(BaseModel):
    minutes: int = Field(ge=1,le=10080)

class RoutineControl(BaseModel):
    expectedRevision: int
    action: str = Field(pattern='^(pause|resume|delete|edit)$')
    reminder: ReminderCreate | None = None


class Preferences(BaseModel):
    timezone: str = 'America/Los_Angeles'
    quietStart: int = Field(default=22,ge=0,le=23)
    quietEnd: int = Field(default=8,ge=0,le=23)
    channels: list[str] = Field(default_factory=lambda:['inbox'],max_length=5)
    emailOptIn: bool = False


def build_reminder_router(get_store,provider_getter=lambda:None):
    router=APIRouter()
    def service(store=Depends(get_store)):return ReminderService(store)

    @router.post('/v1/reminders')
    def create(body:ReminderCreate,owner=Depends(material_owner),svc=Depends(service),key:str=Header(alias='Idempotency-Key')):
        return svc.create(owner,body,key)

    @router.get('/v1/reminders')
    def listing(status:str|None=None,owner=Depends(material_owner),svc=Depends(service)):
        return svc.listing(owner,status)

    @router.post('/v1/reminders/{identifier}/cancel')
    def cancel(identifier:str,owner=Depends(material_owner),svc=Depends(service)):return svc.cancel(owner,identifier)

    @router.get('/v1/reminders/{identifier}')
    def detail(identifier:str,owner=Depends(material_owner),svc=Depends(service)):
        svc.preferences(owner)
        with svc.store.engine.connect() as conn:
            row=conn.execute(text('SELECT * FROM reminders WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().first()
            if not row:fail('not_found','Reminder unavailable.',404)
            deliveries=conn.execute(text('SELECT channel,status FROM notification_deliveries WHERE reminder_id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner}).mappings().all()
            actions=conn.execute(text('SELECT step_id,skill_id,status,error FROM reminder_action_runs WHERE fire_id=:id AND owner_id=:owner ORDER BY step_id'),{'id':identifier,'owner':owner}).mappings().all()
        return {**svc.public(row),'deliveries':[dict(r) for r in deliveries],'actionRuns':[dict(r) for r in actions]}

    @router.post('/v1/reminders/{identifier}/snooze')
    def snooze(identifier:str,body:Snooze,owner=Depends(material_owner),svc=Depends(service),key:str=Header(alias='Idempotency-Key')):return svc.snooze(owner,identifier,body.minutes,key)

    @router.get('/v1/reminder-preferences')
    def preferences(owner=Depends(material_owner),svc=Depends(service)):return svc.preferences(owner)

    @router.patch('/v1/reminder-routines/{identifier}')
    def routine_control(identifier:str,body:RoutineControl,owner=Depends(material_owner),svc=Depends(service)):
        return svc.control_routine(owner,identifier,body.expectedRevision,body.action,body.reminder)

    @router.get('/v1/reminder-messages')
    def messages(sessionId:str,owner=Depends(material_owner),svc=Depends(service)):
        from .material_service import MaterialService
        from .workflow_store import WorkflowStore
        MaterialService(svc.store).session(owner,sessionId)
        return {'messages':[r for r in WorkflowStore(svc.store).listing(owner,'reminder_message') if r.get('sessionId')==sessionId]}

    @router.put('/v1/reminder-preferences')
    def save_preferences(body:Preferences,owner=Depends(material_owner),svc=Depends(service)):
        try:ZoneInfo(body.timezone)
        except (ValueError,KeyError):fail('invalid_timezone','Choose a valid IANA timezone.',422)
        if any(c not in {'inbox','push','desktop','expo','email'} for c in body.channels):fail('invalid_input','Unknown notification channel.',422)
        if body.emailOptIn and os.getenv('OPENLEARN_REMINDER_EMAIL_ENABLED')!='true':fail('capability_unavailable','Email notifications are unavailable.',503)
        svc.preferences(owner)
        with svc.store.transaction() as conn:
            conn.execute(text('INSERT INTO reminder_preferences(owner_id,payload) VALUES(:owner,:payload) ON CONFLICT(owner_id) DO UPDATE SET payload=excluded.payload'),{'owner':owner,'payload':body.model_dump_json()})
        return body

    @router.post('/v1/reminder-chat-command')
    def chat(body:ChatCommand,owner=Depends(material_owner),svc=Depends(service),key:str=Header(alias='Idempotency-Key')):
        return execute_chat_command(body, owner, svc, key, provider_getter)

    @router.post('/internal/reminders/tick')
    def tick(secret:str=Header(default='',alias='X-OpenLearn-Cron-Secret'),svc=Depends(service)):
        configured=os.getenv('OPENLEARN_CRON_SECRET','')
        if not configured or not hmac.compare_digest(configured,secret):fail('permission_denied','Invalid cron credentials.',403)
        with svc.store.engine.connect() as conn:
            last=conn.execute(text("SELECT last_tick FROM reminder_runtime WHERE id='scheduler'")).scalar_one_or_none()
        if last and time.time()-last<2:return {'status':'recently_ticked'}
        from .browser_assistant.reminders import tick_reminders
        tick_reminders(svc.store)
        return svc.tick()

    @router.get('/internal/reminders/status')
    def runtime_status(secret:str=Header(default='',alias='X-OpenLearn-Cron-Secret'),svc=Depends(service)):
        configured=os.getenv('OPENLEARN_CRON_SECRET','')
        if not configured or not hmac.compare_digest(configured,secret):fail('permission_denied','Invalid cron credentials.',403)
        with svc.store.engine.connect() as conn:
            row=conn.execute(text("SELECT * FROM reminder_runtime WHERE id='scheduler'")).mappings().first()
            states=dict(conn.execute(text('SELECT status,count(*) FROM reminders GROUP BY status')).all())
            overdue=conn.execute(text("SELECT count(*) FROM reminders WHERE status='pending' AND due_at<:now"),{'now':time.time()-120}).scalar_one()
        lag=time.time()-row['last_tick'] if row else None
        terminal=states.get('delivered',0)+states.get('failed',0)
        failures=states.get('failed',0)/terminal if terminal else 0
        return {'lastSuccessfulTick':row['last_tick'] if row else None,'tickLagSeconds':lag,'overdue':overdue,'failureRate':failures,'counts':states,'lastTick':json.loads(row['payload']) if row else None,'attentionRequired':lag is None or lag>120 or overdue>0 or failures>.05}
    return router


def execute_chat_command(body, owner, svc, key, provider_getter=lambda: None):
    try:ZoneInfo(body.timezone)
    except (ValueError,KeyError):fail('invalid_timezone','Choose a valid IANA timezone.',422)
    message=body.message.strip().rstrip('.!?')
    if not re.match(r'^(?:remind me|quiz me (?:every|weekdays)|every\b|schedule\b|show my reminders|list (?:my )?reminders|cancel .*reminder|snooze)',message,re.I):return {'handled':False}
    if os.getenv('OPENLEARN_CHAT_REMINDERS')!='true':return {'handled':True,'message':'Chat reminders are not enabled on this server yet.'}
    if re.match(r'^(show|list)',message,re.I):
        items=svc.listing(owner,'pending')['reminders']
        return {'handled':True,'message':'\n'.join(f"{r['title']} — {datetime.fromtimestamp(r['dueAt'],ZoneInfo(body.timezone)).strftime('%a %b %d, %I:%M %p %Z')}" for r in items) or 'You have no upcoming reminders.'}
    if re.match(r'^(cancel|snooze)',message,re.I):
        items=svc.listing(owner)['reminders']
        name=re.sub(r'^(cancel|snooze)\s+(the\s+)?','',message,flags=re.I)
        name=re.sub(r'\s*(reminder)?\s*(for |by )?(\d+\s*(minutes?|hours?))?$','',name,flags=re.I).strip()
        matches=[r for r in items if name.lower() in r['title'].lower() and r['status'] in {'pending','delivered'}]
        if len(matches)!=1:return {'handled':True,'message':'Choose a specific reminder in Reminders so I can identify it safely.'}
        if message.lower().startswith('cancel'):svc.cancel(owner,matches[0]['id']);reply='Cancelled that reminder.'
        else:
            duration=re.search(r'(\d+)\s*(minutes?|hours?)',message,re.I)
            if not duration:return {'handled':True,'message':'Specify how long to snooze, such as snooze the Sam reminder for 1 hour.'}
            svc.snooze(owner,matches[0]['id'],int(duration[1])*(60 if duration[2].lower().startswith('hour') else 1),key);reply='Snoozed that reminder.'
        return {'handled':True,'message':reply}
    pref=svc.preferences(owner)
    args={'timezone':body.timezone,'sessionId':body.sessionId,'buddyId':body.buddyId,'courseId':body.courseId,'channels':pref['channels'],'quietStart':pref['quietStart'],'quietEnd':pref['quietEnd']}
    recurring=re.fullmatch(r'(?:remind me|quiz me)\s+(every day|every weekday|weekdays|every (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s+(?:to|about|on)\s+(.+))?',message,re.I)
    if recurring:
        recurrence,hour,minute,suffix,content=recurring.groups();hour=int(hour);minute=int(minute or 0)
        if suffix:
            if not 1<=hour<=12:fail('invalid_time','Use hours 1–12 with AM or PM.',422)
            hour=hour%12+(12 if suffix.lower()=='pm' else 0)
        days='1-5' if 'weekday' in recurrence.lower() else str(['sunday','monday','tuesday','wednesday','thursday','friday','saturday'].index(recurrence.lower().split()[-1])) if recurrence.lower().split()[-1] in ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'] else '*'
        args.update(schedule={'type':'cron','cron':f'{minute} {hour} * * {days}'},message=content or 'Your scheduled quiz is ready.')
        if message.lower().startswith('quiz me'):
            args['actions']=[{'type':'condition','skillId':'condition.has_session','args':{'sessionId':body.sessionId}},{'type':'skill','skillId':'quiz.create_ready','args':{'sessionId':body.sessionId,'count':10,'requestedTopic':content}},{'type':'skill','skillId':'quiz.prepare_first_item'},{'type':'notify','title':'Quiz ready','bodyTemplate':'Your {{count}}-question quiz on {{title}} is ready.'}]
    else:
        match=re.fullmatch(r'remind me (.+?) (?:to|about) (.+)',message,re.I)
        reverse=re.fullmatch(r'remind me (?:to|about) (.+?) (tomorrow at .+|today at .+|in \d+ (?:minutes?|hours?|days?))',message,re.I)
        if reverse:args.update(when=reverse[2],message=reverse[1])
        elif match:args.update(when=match[1],message=match[2])
        else:
            from .reminder_intent import compile_reminder
            try:compiled=compile_reminder(message,args,provider_getter())
            except Exception:compiled=None
            if not compiled:return {'handled':True,'message':'Tell me what and when, for example: remind me tomorrow at 3pm to call Sam.'}
            if compiled.get('clarification'):return {'handled':True,'message':compiled['clarification']}
            args.update(compiled)
    result=svc.create(owner,ReminderCreate.model_validate(args),key)
    exact=datetime.fromtimestamp(result['dueAt'],ZoneInfo(body.timezone)).strftime('%A, %B %d at %I:%M %p %Z')
    plan=', '.join(a.get('skillId') or a['type'] for a in args.get('actions',[]))
    return {'handled':True,'reminder':result,'message':f"Scheduled: {result['title']}. {'Activities: '+plan+'. ' if plan else ''}Next reminder: {exact}. Channels: {', '.join(args['channels'])}."}

