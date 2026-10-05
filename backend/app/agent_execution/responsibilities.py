"""Bounded ongoing work atop existing task/outbox and notification owners."""
import json
import time
import os
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from sqlalchemy import text
from fastapi import HTTPException
from ..identity import assert_owner_active,fail
from ..workflow_store import encoded,uid
from ..browser_assistant.policy import require_course
from .repository import Repository,TERMINAL,digest
from .coordinator import Coordinator
from .contracts import Command
from .config import admission_enabled


class ResponsibilitySpec(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sessionId:str=Field(max_length=160)
    courseId:str=Field(max_length=160)
    goal:str=Field(min_length=1,max_length=400)
    timezone:str='America/Los_Angeles'
    weekday:int=Field(default=0,ge=0,le=6)
    hour:int=Field(default=9,ge=0,le=23)
    minute:int=Field(default=0,ge=0,le=59)
    schedule:Literal['weekly','once','events']='weekly'
    wakeAt:float|None=None
    lectureEvents:bool=True
    startsAt:float=0
    endsAt:float|None=None
    maxRunsPerWeek:int=Field(default=3,ge=1,le=10)
    quietStart:int=Field(default=22,ge=0,le=23)
    quietEnd:int=Field(default=8,ge=0,le=23)
    expoPush:bool=False
    @model_validator(mode='after')
    def valid(self):
        try:ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose an IANA timezone.')
        if self.schedule=='once' and self.wakeAt is None:raise ValueError('One-shot wakeup requires wakeAt.')
        if self.endsAt is not None and self.endsAt<=self.startsAt:raise ValueError('End must follow start.')
        return self


def occurrences(spec,after,count=3):
    if spec.schedule=='events':return []
    if spec.schedule=='once':return [spec.wakeAt] if spec.wakeAt>after and spec.wakeAt>=spec.startsAt and (spec.endsAt is None or spec.wakeAt<spec.endsAt) else []
    zone=ZoneInfo(spec.timezone)
    day=datetime.fromtimestamp(max(after,spec.startsAt),zone).date()
    result=[]
    for offset in range(370):
        target=day+timedelta(days=offset)
        if target.weekday()!=spec.weekday:continue
        local=datetime(target.year,target.month,target.day,spec.hour,spec.minute)
        # Fold zero chooses one occurrence in autumn. Walk forward through a
        # nonexistent spring time to the first valid local minute.
        for shift in range(181):
            candidate=(local+timedelta(minutes=shift)).replace(tzinfo=zone,fold=0)
            stamp=candidate.timestamp()
            if datetime.fromtimestamp(stamp,zone).replace(tzinfo=None)==candidate.replace(tzinfo=None):break
        if stamp>after and stamp>=spec.startsAt and (spec.endsAt is None or stamp<spec.endsAt):result.append(stamp)
        if len(result)>=count:break
    return result


class Responsibilities:
    def __init__(self,store):self.store=store;self.repo=Repository(store)
    def row(self,conn,owner,identifier):
        assert_owner_active(conn,owner)
        suffix=' FOR UPDATE' if conn.dialect.name=='postgresql' else ''
        row=conn.execute(text('SELECT * FROM agent_responsibilities WHERE id=:id AND owner_id=:owner'+suffix),{'id':identifier,'owner':owner}).mappings().first()
        if not row:fail('not_found','Responsibility unavailable.',404)
        return {**dict(row),'spec':json.loads(row['payload'])}
    def public(self,row):
        spec=ResponsibilitySpec.model_validate(row['spec'])
        return {'id':row['id'],'revision':row['revision'],'status':row['status'],'nextDue':row['next_due'],'spec':row['spec'],'nextOccurrences':occurrences(spec,time.time())}
    def listing(self,owner):
        with self.repo.transaction() as conn:
            assert_owner_active(conn,owner)
            ids=conn.execute(text('SELECT id FROM agent_responsibilities WHERE owner_id=:owner ORDER BY id'),{'owner':owner}).scalars().all()
            return [self.public(self.row(conn,owner,i)) for i in ids]
    def create(self,owner,spec,key):
        if not key or len(key)>200:fail('invalid_input','Provide an Idempotency-Key.',422)
        identifier='responsibility_'+digest([owner,key])[:32]
        with self.repo.transaction() as conn:
            self.repo.session(conn,owner,spec.sessionId);require_course(conn,owner,spec.courseId)
            if not admission_enabled():fail('capability_unavailable','Responsibility admission is disabled.',503)
            session=conn.execute(text('SELECT course_id FROM learning_sessions WHERE id=:id AND learner_id=:owner'),{'id':spec.sessionId,'owner':owner}).scalar_one()
            if session!=spec.courseId:fail('scope_denied','Choose a conversation in this course.',409)
            existing=conn.execute(text('SELECT payload FROM agent_responsibilities WHERE id=:id'),{'id':identifier}).scalar_one_or_none()
            if existing:
                if json.loads(existing)!=spec.model_dump():fail('idempotency_conflict','Request key has different content.',409)
                return self.public(self.row(conn,owner,identifier))
            dates=occurrences(spec,time.time())
            conn.execute(text("INSERT INTO agent_responsibilities(id,owner_id,session_id,course_id,revision,status,next_due,payload) VALUES(:id,:owner,:session,:course,1,'active',:due,:payload)"),{'id':identifier,'owner':owner,'session':spec.sessionId,'course':spec.courseId,'due':dates[0] if dates else None,'payload':encoded(spec.model_dump())})
            conn.execute(text('UPDATE agent_responsibilities SET event_after=:now WHERE id=:id'),{'id':identifier,'now':time.time()})
            from ..buddy_service import BuddyService
            BuddyService(self.store).responsibility(conn,owner,identifier,'ongoing',spec.courseId)
            return self.public(self.row(conn,owner,identifier))
    def control(self,owner,identifier,revision,action,spec=None):
        with self.repo.transaction() as conn:
            row=self.row(conn,owner,identifier)
            if row['revision']!=revision:fail('revision_conflict','Refresh before changing this responsibility.',409)
            if row['status']=='cancelled':fail('invalid_state','Cancelled responsibility cannot restart.',409)
            current=ResponsibilitySpec.model_validate(row['spec'])
            if spec and (spec.courseId!=current.courseId or spec.sessionId!=current.sessionId):fail('scope_denied','Create a new responsibility to change course scope.',409)
            current=spec or current
            status={'pause':'paused','disable':'disabled','stop_all':'cancelled','resume':'active','edit':row['status']}[action]
            # Disable deliberately leaves the current task alone. Pause and edit
            # fence active work through the existing durable command contract.
            if action in {'pause','stop_all','edit'}:
                ids=conn.execute(text("SELECT run_id FROM agent_responsibility_occurrences WHERE responsibility_id=:id AND owner_id=:owner AND run_id IS NOT NULL"),{'id':identifier,'owner':owner}).scalars().all()
                for run_id in ids:
                    run=self.repo.run(conn,owner,run_id)
                    if run['status'] not in TERMINAL:
                        Coordinator(self.store).apply_command(conn,owner,run_id,Command(commandId=uid('responsibility_command'),action='cancel' if action in {'stop_all','edit'} else 'pause',expectedRevision=run['revision']))
            dates=occurrences(current,time.time())
            conn.execute(text('UPDATE agent_responsibilities SET revision=revision+1,status=:status,next_due=:due,payload=:payload WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':owner,'status':status,'due':dates[0] if dates else None,'payload':encoded(current.model_dump())})
            conn.execute(text('UPDATE agent_responsibilities SET event_after=:now WHERE id=:id'),{'id':identifier,'now':time.time()})
            if action=='resume':
                ids=conn.execute(text('SELECT run_id FROM agent_responsibility_occurrences WHERE responsibility_id=:id AND owner_id=:owner AND run_id IS NOT NULL'),{'id':identifier,'owner':owner}).scalars().all()
                for run_id in ids:
                    run=self.repo.run(conn,owner,run_id)
                    if run['status']=='paused':Coordinator(self.store).apply_command(conn,owner,run_id,Command(commandId=uid('responsibility_command'),action='resume',expectedRevision=run['revision']))
            return self.public(self.row(conn,owner,identifier))
    def trigger(self,conn,row,event,now,causation=None):
        spec=ResponsibilitySpec.model_validate(row['spec'])
        if row['status']!='active' or causation==row['id'] or now<spec.startsAt or spec.endsAt is not None and now>=spec.endsAt or not admission_enabled():return
        self.repo.session(conn,row['owner_id'],spec.sessionId);require_course(conn,row['owner_id'],spec.courseId)
        identifier='occurrence_'+digest([row['id'],row['revision'],event])[:32]
        if conn.execute(text('SELECT 1 FROM agent_responsibility_occurrences WHERE id=:id'),{'id':identifier}).first():return
        live=conn.execute(text("SELECT 1 FROM agent_responsibility_occurrences o JOIN assistant_runs r ON r.id=o.run_id AND r.owner_id=o.owner_id WHERE o.responsibility_id=:id AND r.status NOT IN ('completed','completed_partial','failed','cancelled')"),{'id':row['id']}).first()
        budget=conn.execute(text("SELECT count(*) FROM agent_responsibility_occurrences WHERE responsibility_id=:id AND created_at>=:start AND run_id IS NOT NULL"),{'id':row['id'],'start':int(now//604800)*604800}).scalar_one()
        status='overlap_skipped' if live else 'budget_exhausted' if budget>=spec.maxRunsPerWeek else 'started'
        if status=='started' and conn.execute(text("SELECT count(*) FROM assistant_runs WHERE owner_id=:owner AND runtime_owner='agent_v2' AND status IN ('queued','running')"),{'owner':row['owner_id']}).scalar_one()>=2:status='capacity_skipped'
        run=None
        if status=='started':
            from .research_contracts import ResearchSpec
            run=Coordinator(self.store).create(conn,row['owner_id'],spec.sessionId,spec.goal,identifier,None,{},kind='research',research_spec=ResearchSpec(query=spec.goal,source_policy='attached_only',max_sources=3,open_sources=0).model_dump(by_alias=True))
            run=self.repo.update(conn,run,responsibilityId=row['id'],responsibilityRevision=row['revision'])
            notes=conn.execute(text('SELECT payload FROM agent_operational_notes WHERE owner_id=:owner AND responsibility_id=:id ORDER BY id LIMIT 10'),{'owner':row['owner_id'],'id':row['id']}).scalars().all()
            if notes:run=self.repo.update(conn,run,operationalNotes=[json.loads(note)['text'] for note in notes])
            self.repo.schedule(conn,run)
        conn.execute(text('INSERT INTO agent_responsibility_occurrences(id,owner_id,responsibility_id,revision,run_id,status,created_at,payload) VALUES(:id,:owner,:responsibility,:revision,:run,:status,:now,:payload)'),{'id':identifier,'owner':row['owner_id'],'responsibility':row['id'],'revision':row['revision'],'run':run['id'] if run else None,'status':status,'now':now,'payload':encoded({'event':event})})
    def tick(self,limit=20,now=None):
        now=time.time() if now is None else now
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT id,owner_id FROM agent_responsibilities WHERE status='active' ORDER BY last_checked,id LIMIT :limit"),{'limit':limit}).mappings().all()
        for item in rows:
            try:self.check(item,now)
            except HTTPException as exc:
                if exc.status_code not in {403,404}:raise
                # Revoked/deleted scope must not stop unrelated owners' work.
                with self.store.engine.begin() as conn:
                    conn.execute(text("UPDATE agent_responsibilities SET status='unavailable',next_due=NULL WHERE id=:id AND owner_id=:owner"),dict(item))
        self.notify(now)
    def check(self,item,now):
            with self.repo.transaction() as conn:
                row=self.row(conn,item['owner_id'],item['id']);spec=ResponsibilitySpec.model_validate(row['spec'])
                if row['status']!='active':return
                conn.execute(text('UPDATE agent_responsibilities SET last_checked=:now WHERE id=:id'),{'id':row['id'],'now':now})
                if spec.endsAt is not None and now>=spec.endsAt:
                    conn.execute(text("UPDATE agent_responsibilities SET status='completed',next_due=NULL WHERE id=:id"),{'id':row['id']});return
                if row['next_due'] is not None and row['next_due']<=now:
                    self.trigger(conn,row,'scheduled:'+str(row['next_due']),now)
                    dates=occurrences(spec,now)
                    conn.execute(text('UPDATE agent_responsibilities SET next_due=:due WHERE id=:id'),{'id':row['id'],'due':dates[0] if dates else None})
                if spec.lectureEvents:
                    lectures=conn.execute(text("SELECT id,generation_version FROM lecture_recordings WHERE learner_id=:owner AND course_id=:course AND status='completed' AND updated_at>=:start ORDER BY updated_at DESC LIMIT 20"),{'owner':row['owner_id'],'course':spec.courseId,'start':max(spec.startsAt,row['event_after'])}).mappings().all()
                    for lecture in lectures:self.trigger(conn,row,'lecture:'+lecture['id']+':'+str(lecture['generation_version']),now)
    def notify(self,now):
        with self.repo.transaction() as conn:
            rows=conn.execute(text("SELECT o.*,r.status AS run_status,r.payload AS run_payload FROM agent_responsibility_occurrences o JOIN assistant_runs r ON r.id=o.run_id AND r.owner_id=o.owner_id WHERE r.status IN ('completed','completed_partial','failed','waiting') LIMIT 100")).mappings().all()
            for row in rows:
                run=json.loads(row['run_payload']);state=row['run_status']
                request=(run.get('pendingRequests') or [{}])[0].get('requestId','')
                key='responsibility_notice_'+digest([row['id'],state,request])[:32]
                payload={'title':'Your ongoing work needs attention' if state in {'waiting','failed'} else 'Your ongoing work has a result','body':'Open the conversation to review it.','url':'/s/'+run['sessionId']+'?task='+row['run_id'],'taskId':row['run_id'],'responsibilityId':row['responsibility_id']}
                conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES(:id,:owner,:ref,'inbox','available',:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING"),{'id':key,'owner':row['owner_id'],'ref':key,'payload':encoded(payload),'now':now})
                responsibility=self.row(conn,row['owner_id'],row['responsibility_id'])
                spec=ResponsibilitySpec.model_validate(responsibility['spec'])
                if spec.expoPush:
                    payload.update(timezone=spec.timezone,quietStart=spec.quietStart,quietEnd=spec.quietEnd)
                    conn.execute(text("INSERT INTO notification_deliveries(id,owner_id,reminder_id,channel,status,payload,created_at) VALUES(:id,:owner,:ref,'expo','pending',:payload,:now) ON CONFLICT(owner_id,reminder_id,channel) DO NOTHING"),{'id':key+'_expo','owner':row['owner_id'],'ref':key,'payload':encoded(payload),'now':now})
        self.deliver(now)

    def deliver(self,now,sender=None):
        if sender is None and os.getenv('OPENLEARN_EXPO_PUSH_ENABLED')!='true':return
        if sender is None:
            import httpx
            def sender(token,payload):
                response=httpx.post('https://exp.host/--/api/v2/push/send',json={'to':token,'title':'Open Learn update','body':'Open Open Learn to review your ongoing work.','data':{'url':payload['url'],'taskId':payload['taskId']}},timeout=10,trust_env=False)
                response.raise_for_status();return response.json().get('data',{})
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT * FROM notification_deliveries WHERE channel='expo' AND status='pending' LIMIT 20")).mappings().all()
        for row in rows:
            payload=json.loads(row['payload']);hour=datetime.fromtimestamp(now,ZoneInfo(payload['timezone'])).hour
            start,end=payload['quietStart'],payload['quietEnd']
            quiet=start!=end and (start<=hour<end if start<end else hour>=start or hour<end)
            if quiet:continue
            with self.repo.transaction() as conn:
                assert_owner_active(conn,row['owner_id'])
                if now-row['created_at']>86400:
                    conn.execute(text("UPDATE notification_deliveries SET status='expired' WHERE id=:id"),{'id':row['id']});continue
                targets=conn.execute(text("SELECT id,payload FROM notification_subscriptions WHERE owner_id=:owner AND active=true"),{'owner':row['owner_id']}).mappings().all()
                targets=[t for t in targets if json.loads(t['payload']).get('kind')=='expo']
                if not targets:continue
                changed=conn.execute(text("UPDATE notification_deliveries SET status='outcome_unknown' WHERE id=:id AND status='pending'"),{'id':row['id']}).rowcount
                if not changed:continue
            status='ticket_accepted';tickets=[]
            for target in targets:
                try:
                    result=sender(json.loads(target['payload'])['token'],payload)
                    if result.get('status')!='ok':status='failed'
                    if result.get('id'):tickets.append({'id':result['id'],'subscriptionId':target['id']})
                    if result.get('details',{}).get('error')=='DeviceNotRegistered':
                        with self.repo.transaction() as conn:conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE id=:id AND owner_id=:owner'),{'id':target['id'],'owner':row['owner_id']})
                except Exception:status='outcome_unknown'
            with self.repo.transaction() as conn:conn.execute(text('UPDATE notification_deliveries SET status=:status,payload=:payload WHERE id=:id AND owner_id=:owner'),{'status':status,'id':row['id'],'owner':row['owner_id'],'payload':encoded({**payload,'tickets':tickets})})
        if os.getenv('OPENLEARN_EXPO_PUSH_ENABLED')=='true':self.receipts(now)

    def receipts(self,now,reader=None):
        if reader is None:
            import httpx
            def reader(ids):
                response=httpx.post('https://exp.host/--/api/v2/push/getReceipts',json={'ids':ids},timeout=10,trust_env=False)
                response.raise_for_status();return response.json().get('data',{})
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT * FROM notification_deliveries WHERE channel='expo' AND status='ticket_accepted' LIMIT 20")).mappings().all()
        for row in rows:
            payload=json.loads(row['payload']);tickets=payload.get('tickets',[])
            if not tickets:continue
            try:results=reader([ticket['id'] for ticket in tickets])
            except Exception:continue
            with self.repo.transaction() as conn:
                assert_owner_active(conn,row['owner_id'])
                failed=False;pending=False
                for ticket in tickets:
                    receipt=results.get(ticket['id'])
                    if not receipt:pending=True;continue
                    if receipt.get('status')!='ok':failed=True
                    if receipt.get('details',{}).get('error')=='DeviceNotRegistered':
                        conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE id=:id AND owner_id=:owner'),{'id':ticket['subscriptionId'],'owner':row['owner_id']})
                status='failed' if failed else 'ticket_accepted' if pending else 'provider_handoff_confirmed'
                if status=='ticket_accepted' and now-row['created_at']>86400:status='receipt_expired'
                conn.execute(text('UPDATE notification_deliveries SET status=:status WHERE id=:id AND owner_id=:owner'),{'status':status,'id':row['id'],'owner':row['owner_id']})
    def notes(self,owner,identifier):
        with self.repo.transaction() as conn:
            self.row(conn,owner,identifier)
            return [{'id':r['id'],'revision':r['revision'],**json.loads(r['payload'])} for r in conn.execute(text('SELECT * FROM agent_operational_notes WHERE owner_id=:owner AND responsibility_id=:id'),{'owner':owner,'id':identifier}).mappings()]
    def note(self,owner,identifier,content,note_id=None,revision=None):
        with self.repo.transaction() as conn:
            self.row(conn,owner,identifier)
            if note_id:
                changed=conn.execute(text('UPDATE agent_operational_notes SET revision=revision+1,payload=:payload WHERE id=:note AND owner_id=:owner AND responsibility_id=:id AND revision=:revision'),{'note':note_id,'owner':owner,'id':identifier,'revision':revision,'payload':encoded({'text':content})})
                if changed.rowcount!=1:fail('revision_conflict','Note changed or is unavailable.',409)
            else:
                conn.execute(text('INSERT INTO agent_operational_notes(id,owner_id,responsibility_id,revision,payload) VALUES(:note,:owner,:id,1,:payload)'),{'note':uid('operational_note'),'owner':owner,'id':identifier,'payload':encoded({'text':content})})
        return self.notes(owner,identifier)

    def delete_note(self,owner,identifier,note_id,revision):
        with self.repo.transaction() as conn:
            self.row(conn,owner,identifier)
            changed=conn.execute(text('DELETE FROM agent_operational_notes WHERE id=:note AND owner_id=:owner AND responsibility_id=:id AND revision=:revision'),{'note':note_id,'owner':owner,'id':identifier,'revision':revision})
            if changed.rowcount!=1:fail('revision_conflict','Note changed or unavailable.',409)
        return {'status':'deleted'}
