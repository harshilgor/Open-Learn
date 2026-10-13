from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from ..material_routes import material_owner
from .service import CalendarService
from .contracts import EventInput, EventEdit, EventAction, Preferences, Permission, Proposal, Decision, Availability
from ..identity import current_principal, fail
from .chat import CalendarCommand, execute_calendar_chat
from sqlalchemy import text

class GoogleSelection(BaseModel):
    connectionId: str
    providerCalendarId: str


def build_calendar_router(get_store, provider_getter=lambda: None):
    router = APIRouter(prefix='/v1/calendar', tags=['calendar'])
    def service(store=Depends(get_store)): return CalendarService(store)
    def human(owner=Depends(material_owner)):
        if current_principal().kind not in {'web','local','desktop'}: fail('human_consent_required', 'Use your account to change permissions.', 403)
        return owner

    @router.post('/chat')
    def chat(body: CalendarCommand, key: str = Header(alias='Idempotency-Key'), owner=Depends(human), svc=Depends(service)):
        return execute_calendar_chat(svc.store, owner, body, key, provider_getter())

    @router.get('/proposals')
    def proposals(sessionId: str, owner=Depends(human), svc=Depends(service)):
        with svc.transaction(owner) as conn:
            if not conn.execute(text('SELECT 1 FROM learning_sessions WHERE id=:id AND learner_id=:owner'), {'id': sessionId, 'owner': owner}).first(): fail('not_found', 'Conversation unavailable.', 404)
            rows = [p for p in svc.list_rows(conn, owner, 'proposals') if p.get('sessionId') == sessionId and p['status'] not in {'cancelled','superseded'}]
            return {'items': sorted(rows, key=lambda p:p['createdAt'], reverse=True)[:10]}

    @router.post('/proposals/{identifier}/read-retry')
    def retry_read(identifier: str, owner=Depends(human), svc=Depends(service)):
        with svc.transaction(owner) as conn:
            record = svc.read(conn, owner, 'proposals', identifier)
            if record.get('kind') != 'read_consent' or record['expiresAt'] <= __import__('time').time(): fail('read_request_expired', 'Ask Buddy again to check your calendar.', 409)
            if record['status'] == 'completed': return record['receipt']
        receipt = execute_calendar_chat(svc.store, owner, CalendarCommand.model_validate(record['command']), identifier + ':retry', provider_getter())
        if not receipt.get('calendarRequestId'):
            with svc.transaction(owner) as conn:
                fresh = svc.read(conn, owner, 'proposals', identifier)
                if fresh['status'] != 'completed': svc.write(conn, owner, 'proposals', {**fresh, 'status':'completed', 'receipt':receipt}, fresh['revision'])
        return receipt

    @router.get('/calendars')
    def calendars(owner=Depends(material_owner), svc=Depends(service)): return svc.calendars(owner)

    @router.get('/google/{connection}/calendars')
    def google_calendars(connection: str, owner=Depends(material_owner), svc=Depends(service)):
        from .google import GoogleCalendar
        from ..agent_execution.connected_routes import safe
        return safe(lambda: GoogleCalendar(svc.store).discover(owner, connection))

    @router.post('/google/calendars')
    def select_google(body: GoogleSelection, owner=Depends(material_owner), svc=Depends(service)):
        from .google import GoogleCalendar
        from ..agent_execution.connected_routes import safe
        return safe(lambda: GoogleCalendar(svc.store).select(owner, body.connectionId, body.providerCalendarId))

    @router.post('/calendars/{calendar}/sync')
    def sync_google(calendar: str, owner=Depends(material_owner), svc=Depends(service)):
        from .google import GoogleCalendar
        from ..agent_execution.connected_routes import safe
        return safe(lambda: GoogleCalendar(svc.store).sync(owner, calendar))

    @router.get('/occurrences')
    def occurrences(start: str = Query(alias='from'), end: str = Query(alias='to'), timezone: str = 'UTC', calendarIds: str | None = None, courseIds: str | None = None, cursor: int = Query(default=0, ge=0), owner=Depends(material_owner), svc=Depends(service)):
        return svc.occurrences(owner, start, end, timezone, calendarIds.split(',') if calendarIds else None, courseIds.split(',') if courseIds else None, cursor=cursor)

    @router.get('/preferences')
    def preferences(owner=Depends(material_owner), svc=Depends(service)): return svc.get_preferences(owner)

    @router.put('/preferences')
    def save_preferences(body: Preferences, owner=Depends(material_owner), svc=Depends(service)): return svc.save_preferences(owner, body)

    @router.get('/permissions/{calendar}')
    def permission(calendar: str, owner=Depends(material_owner), svc=Depends(service)):
        with svc.transaction(owner) as conn: return svc.permission(conn, owner, calendar)

    @router.put('/permissions/{calendar}')
    def save_permission(calendar: str, body: Permission, owner=Depends(human), svc=Depends(service)): return svc.set_permission(owner, calendar, body)

    @router.post('/events')
    def create(body: EventInput, key: str = Header(alias='Idempotency-Key'), owner=Depends(material_owner), svc=Depends(service)): return svc.create(owner, body, key)

    @router.get('/events/{identifier}')
    def event(identifier: str, owner=Depends(material_owner), svc=Depends(service)): return svc.event(owner, identifier)

    @router.patch('/events/{identifier}')
    def edit(identifier: str, body: EventEdit, key: str = Header(alias='Idempotency-Key'), owner=Depends(material_owner), svc=Depends(service)): return svc.edit(owner, identifier, body, key)

    @router.post('/events/{identifier}/cancel')
    def cancel(identifier: str, body: EventAction, key: str = Header(alias='Idempotency-Key'), owner=Depends(material_owner), svc=Depends(service)): return svc.cancel(owner, identifier, body, key)

    @router.post('/availability')
    def available(body: Availability, owner=Depends(material_owner), svc=Depends(service)): return svc.availability(owner, body)

    @router.post('/proposals')
    def propose(body: Proposal, key: str = Header(alias='Idempotency-Key'), owner=Depends(material_owner), svc=Depends(service)): return svc.propose(owner, body, key)

    @router.post('/proposals/{identifier}/decision')
    def decide(identifier: str, body: Decision, key: str = Header(alias='Idempotency-Key'), owner=Depends(human), svc=Depends(service)): return svc.decide(owner, identifier, body, key)

    @router.get('/operations/{identifier}')
    def operation(identifier: str, owner=Depends(material_owner), svc=Depends(service)): return svc.get_operation(owner, identifier)

    @router.post('/operations/{identifier}/reconcile')
    def reconcile(identifier: str, owner=Depends(human), svc=Depends(service)):
        from .google_writes import GoogleWrites
        operation = svc.get_operation(owner, identifier)
        if operation['status'] != 'outcome_unknown': fail('invalid_state', 'Only uncertain operations need reconciliation.', 409)
        return GoogleWrites(svc.store).execute(owner, identifier)

    @router.post('/operations/{identifier}/undo')
    def undo(identifier: str, key: str = Header(alias='Idempotency-Key'), owner=Depends(material_owner), svc=Depends(service)): return svc.undo(owner, identifier, key)

    return router
