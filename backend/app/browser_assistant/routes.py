import asyncio
import json
import base64
import json
import os
import time
from fastapi import APIRouter, Header, Request, Query
from fastapi.responses import StreamingResponse, Response, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from .contracts import TaskCreate, TaskCommand, ConnectionCreate, ConnectionPatch, BrowserResult, ReminderPolicyInput, RefreshInput, PushInput, CloudLoginInput
from .connections import Connections
from .service import AssistantService
from .store import AssistantStore, public_run, public_connection
from .intent import compile_intent
from .policy import TERMINAL, timezone, checksum
from ..identity import current_principal, fail, assert_owner_active
from ..workflow_store import uid, encoded
from ..agent_execution.contracts import Command as AgentCommand


def build_assistant_router(store_getter, provider_getter=lambda: None):
    router = APIRouter(prefix='/v1', tags=['browser assistant'])

    def owner():
        principal = current_principal()
        if principal.kind not in {'web','local','desktop'}: fail('device_scope_denied', 'Use your OpenLearn account.', 403)
        return principal.owner_id

    @router.get('/assistant/capabilities')
    def capabilities():
        owner()
        from .executors.cloud import readiness
        return {'enabled': os.getenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'true') == 'true',
                'cloud': readiness(), 'providerConfigured': provider_getter() is not None,
                'vapidPublicKey': os.getenv('OPENLEARN_VAPID_PUBLIC_KEY'),
                'hosted': os.getenv('AI_TUTOR_ENV') in {'production','deployed'}}

    @router.get('/browser-companion/download')
    def companion_download():
        owner()
        from pathlib import Path
        from io import BytesIO
        from zipfile import ZipFile, ZIP_DEFLATED
        root = Path(__file__).resolve().parents[3] / 'canvas-extension'
        if not root.is_dir(): fail('capability_unavailable', 'The companion package is missing from this installation.', 503)
        buffer = BytesIO()
        with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
            for item in root.iterdir():
                if item.is_file() and item.suffix in {'.js','.json','.html','.md'}:
                    archive.write(item, 'openlearn-browser-companion/' + item.name)
        return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition':'attachment; filename="openlearn-browser-companion.zip"','Cache-Control':'no-store'})

    @router.post('/assistant/intent')
    def intent(body: TaskCreate):
        learner = owner()
        if os.getenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'true') != 'true': return {'handled': False}
        connections = AssistantStore(store_getter()).list('site_connections', learner)
        previous = None
        repo = AssistantStore(store_getter())
        if body.previous_task_id:
            previous = repo.read('assistant_runs',learner,body.previous_task_id)
            if not body.session_id or previous.get('sessionId') != body.session_id: fail('not_found','Website task unavailable in this conversation.',404)
            previous = public_run(previous)
        # The browser-task contract owns the semantic decision here. Running
        # the general route contract first would add a second JEV round trip to
        # this same intent request.
        result = compile_intent(body.message, provider_getter(), connections, previous)
        if not result.handled:
            return {'handled': False}
        return result.model_dump(by_alias=True)

    @router.post('/assistant/tasks', status_code=202)
    def create_task(body: TaskCreate, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
        if os.getenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'true') != 'true': fail('capability_unavailable', 'Browser assistance is disabled.', 503)
        return AssistantService(store_getter()).create(owner(), body, idempotency_key)

    @router.get('/assistant/tasks')
    def list_tasks(session_id: str | None = Query(default=None, alias='sessionId'), course_id: str | None = Query(default=None, alias='courseId')):
        learner = owner(); db = store_getter()
        sql = 'SELECT id FROM assistant_runs WHERE owner_id=:owner'
        args = {'owner': learner}
        if session_id: sql += ' AND session_id=:session'; args['session'] = session_id
        with db.engine.connect() as conn:
            ids = conn.execute(text(sql + ' ORDER BY created_at DESC LIMIT 30'), args).scalars().all()
        repo = AssistantStore(db)
        tasks = [public_run(repo.read('assistant_runs', learner, identifier)) for identifier in ids
                 if repo.read('assistant_runs', learner, identifier).get('runtime_owner') != 'agent_v2']
        return {'tasks': [t for t in tasks if not course_id or t.get('courseId') == course_id]}

    @router.get('/assistant/tasks/{identifier}')
    def task(identifier: str):
        learner = owner(); db = store_getter()
        run = AssistantStore(db).read('assistant_runs', learner, identifier)
        if run.get('runtime_owner') == 'agent_v2':
            from ..agent_execution.repository import Repository
            return Repository(db).descriptor(run)
        return public_run(run)

    @router.post('/assistant/tasks/{identifier}/commands')
    def command(identifier: str, body: AgentCommand | TaskCommand):
        from ..agent_execution.contracts import Command
        from pydantic import ValidationError
        learner = owner(); db = store_getter()
        run = AssistantStore(db).read('assistant_runs', learner, identifier)
        try:
            if run.get('runtime_owner') == 'agent_v2':
                from ..agent_execution.coordinator import Coordinator
                return Coordinator(db).command(learner, identifier, Command.model_validate(body.model_dump(by_alias=True)))
            return AssistantService(db).command(learner, identifier, TaskCommand.model_validate(body.model_dump(by_alias=True)))
        except ValidationError: fail('invalid_input', 'Invalid task command.', 422)

    @router.get('/assistant/tasks/{identifier}/events')
    async def events(identifier: str, request: Request, after: int = Query(default=0, ge=0), stream: bool = False,
                     last_event_id: str | None = Header(default=None, alias='Last-Event-ID')):
        learner = owner(); repo = AssistantStore(store_getter())
        repo.read('assistant_runs', learner, identifier)
        if last_event_id:
            try: after = max(after, int(last_event_id))
            except ValueError: fail('invalid_input', 'Invalid event cursor.', 422)
        if not stream: return {'events': repo.events(learner, identifier, after)}
        async def generate():
            sequence = after
            while not await request.is_disconnected():
                for event in repo.events(learner, identifier, sequence):
                    sequence = event['sequence']
                    yield f'id: {sequence}\nevent: assistant\ndata: {json.dumps(event)}\n\n'
                state = repo.read('assistant_runs', learner, identifier)
                if state['status'] in TERMINAL: break
                yield ': keepalive\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @router.get('/assistant/tasks/{identifier}/browser-view')
    def browser_view(identifier: str):
        from .control import BrowserControl
        return Response(content=json.dumps(BrowserControl(store_getter()).view(owner(),identifier)),media_type='application/json',headers={'Cache-Control':'no-store'})

    @router.get('/assistant/tasks/{identifier}/browser-preview')
    def browser_preview(identifier: str):
        from .control import BrowserControl
        return Response(content=json.dumps(BrowserControl(store_getter()).preview(owner(),identifier)),media_type='application/json',headers={'Cache-Control':'no-store'})

    class HandoffAck(BaseModel):
        generation: str

    @router.post('/browser-devices/handoffs/{identifier}/ack')
    def handoff_ack(identifier: str, body: HandoffAck):
        from .control import BrowserControl
        return BrowserControl(store_getter()).acknowledge(current_principal(),identifier,body.generation)

    @router.get('/site-connections')
    def connections(): return {'connections': [public_connection(c) for c in AssistantStore(store_getter()).list('site_connections', owner()) if c['status'] != 'revoked']}

    @router.post('/site-connections', status_code=201)
    def connect(body: ConnectionCreate): return Connections(store_getter()).create(owner(), body)

    @router.patch('/site-connections/{identifier}')
    def update_connection(identifier: str, body: ConnectionPatch): return Connections(store_getter()).patch(owner(), identifier, body)

    @router.delete('/site-connections/{identifier}')
    def disconnect(identifier: str, delete_imports: bool = Query(default=False, alias='deleteImports')):
        return Connections(store_getter()).revoke(owner(), identifier, delete_imports)

    @router.post('/site-connections/{identifier}/pair')
    def pair(identifier: str): return Connections(store_getter()).pair(owner(), identifier)

    @router.post('/site-connections/{identifier}/cloud-login')
    def cloud_login(identifier: str, body: CloudLoginInput):
        result = Connections(store_getter()).cloud_login(owner(), identifier, body.expected_revision)
        return JSONResponse(result, headers={'Cache-Control':'no-store','Pragma':'no-cache'})

    @router.post('/site-connections/{identifier}/cloud-login/finish')
    def cloud_login_finish(identifier: str, body: CloudLoginInput):
        result = Connections(store_getter()).cloud_login(owner(), identifier, body.expected_revision, finish=True)
        return JSONResponse(result, headers={'Cache-Control':'no-store','Pragma':'no-cache'})

    @router.post('/site-connections/{identifier}/refresh', status_code=202)
    def refresh(identifier: str, body: TaskCreate | None = None):
        command = body or TaskCreate(message='Check my courses and save updated deadlines and exam dates')
        command.connection_id = identifier
        return AssistantService(store_getter()).create(owner(), command)

    @router.post('/site-connections/{identifier}/schedule')
    def refresh_schedule(identifier: str, body: RefreshInput):
        learner = owner(); db = store_getter()
        with db.transaction() as conn:
            connection = AssistantStore(db).row(conn, 'site_connections', learner, identifier)
            if connection['status'] == 'revoked': fail('connection_revoked', 'Reconnect this site.', 409)
            schedule_id = 'refresh_' + identifier
            conn.execute(text('''INSERT INTO connection_refresh_schedules(id,owner_id,connection_id,revision,active,next_due,payload)
                VALUES(:id,:owner,:connection,1,:active,:due,:payload) ON CONFLICT(id) DO UPDATE SET active=excluded.active,
                revision=connection_refresh_schedules.revision+1,next_due=excluded.next_due,payload=excluded.payload'''),
                {'id': schedule_id, 'owner': learner, 'connection': identifier, 'active': body.active,
                 'due': time.time()+body.interval_hours*3600, 'payload': body.model_dump_json(by_alias=True)})
        return {'id': schedule_id, 'active': body.active}

    @router.get('/browser-devices/commands')
    def poll(): return AssistantService(store_getter()).poll(current_principal())

    @router.post('/browser-devices/disconnect')
    def disconnect_device():
        principal = current_principal()
        if principal.kind != 'browser': fail('device_scope_denied', 'Use a paired browser device.', 403)
        with store_getter().engine.connect() as conn:
            ids = conn.execute(text('SELECT id FROM site_connections WHERE owner_id=:owner AND device_id=:device'), {'owner': principal.owner_id, 'device': principal.device_id}).scalars().all()
        for identifier in ids: Connections(store_getter()).revoke(principal.owner_id, identifier)
        return {'status':'revoked'}

    @router.post('/browser-devices/commands/{identifier}/result')
    def acknowledge(identifier: str, body: BrowserResult): return AssistantService(store_getter()).acknowledge(current_principal(), identifier, body)

    @router.get('/academic/upcoming')
    def upcoming_events(course_id: str | None = Query(default=None, alias='courseId')):
        from .workers import upcoming
        return {'events': upcoming(store_getter(), owner(), course_id)}

    @router.get('/academic-reminders')
    def reminders():
        items = AssistantStore(store_getter()).list('reminders', owner())
        return {'reminders': [{k:v for k,v in item.items() if k not in {'payload','owner_id'}} for item in items]}

    @router.get('/reminder-policies')
    def policies():
        fields = set(ReminderPolicyInput.model_json_schema(by_alias=True)['properties']) | {'id','revision'}
        return {'policies': [{k:v for k,v in item.items() if k in fields} for item in AssistantStore(store_getter()).list('reminder_policies', owner()) if item.get('kind','academic')=='academic']}

    @router.post('/reminder-policies')
    def policy(body: ReminderPolicyInput):
        from .reminders import create_policy
        return create_policy(store_getter(), owner(), body)

    @router.patch('/reminder-policies/{identifier}')
    def update_policy(identifier: str, body: ReminderPolicyInput):
        from .reminders import create_policy
        return create_policy(store_getter(), owner(), body, identifier)

    @router.get('/notifications')
    def notifications():
        learner = owner(); db = store_getter()
        items = AssistantStore(db).list('notification_deliveries', learner)
        from .reminders import valid_reminder
        result = []
        with db.transaction() as conn:
            for item in items:
                if item['channel'] != 'inbox': continue
                reminder = conn.execute(text('SELECT * FROM reminders WHERE owner_id=:owner AND id=:id'), {'owner':learner,'id':item['reminder_id']}).mappings().first()
                if not reminder or not valid_reminder(conn, reminder): continue
                data = {k:v for k,v in item.items() if k not in {'payload','owner_id'}}
                data['deliverable'] = time.time() <= min(item.get('eventAt',float('inf')), reminder['due_at'] + item.get('catchupMinutes',120)*60)
                result.append(data)
        return {'notifications':result}

    @router.post('/notifications/{identifier}/ack')
    def acknowledge_notification(identifier: str):
        learner = owner(); db = store_getter()
        with db.transaction() as conn:
            item = AssistantStore(db).row(conn, 'notification_deliveries', learner, identifier)
            conn.execute(text("UPDATE notification_deliveries SET status='seen' WHERE id=:id AND owner_id=:owner"), {'id': identifier, 'owner': learner})
        return {'status': 'seen'}

    @router.post('/notification-subscriptions')
    def subscribe(body: PushInput):
        learner = owner(); db = store_getter()
        from ..url_ingestion import validate_public_url
        validate_public_url(body.endpoint)
        if not body.endpoint.startswith('https:') or not set(body.keys) == {'p256dh','auth'} or any(len(v)>300 for v in body.keys.values()):
            fail('invalid_input', 'Invalid browser push subscription.', 422)
        # Restrict push delivery endpoints to actual browser push services; no generic request tool.
        from urllib.parse import urlsplit
        host = urlsplit(body.endpoint).hostname or ''
        if not (host == 'fcm.googleapis.com' or host.endswith('.push.services.mozilla.com') or host.endswith('.notify.windows.com') or host.endswith('.push.apple.com')):
            fail('invalid_input', 'This push service is unsupported.', 422)
        digest = checksum(body.endpoint)
        with db.transaction() as conn:
            conn.execute(text('''INSERT INTO notification_subscriptions(id,owner_id,endpoint_hash,active,payload) VALUES(:id,:owner,:hash,true,:payload)
                ON CONFLICT(owner_id,endpoint_hash) DO UPDATE SET active=true,payload=excluded.payload'''),
                {'id': uid('subscription'), 'owner': learner, 'hash': digest, 'payload': body.model_dump_json()})
        return {'status': 'subscribed'}

    @router.delete('/notification-subscriptions')
    def unsubscribe():
        learner = owner()
        with store_getter().transaction() as conn: conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE owner_id=:owner'), {'owner': learner})
        return {'status':'unsubscribed'}

    return router
