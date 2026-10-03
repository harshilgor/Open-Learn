"""Paired browser ingestion. Canvas credentials stay in the student's browser."""
import hashlib
import json
import secrets
import time
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .academic_planning import AcademicPlanningService, AcademicError
from .material_routes import material_owner
from .identity import issue_device_grant, current_principal
from sqlalchemy import text

SKILLS = {'assignments', 'modules', 'syllabus', 'announcements', 'calendar', 'courses'}

def origin(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise AcademicError('invalid_canvas_origin', 'Approve an HTTPS institution origin only.')
    return f'https://{parsed.netloc.lower()}'

class PairCommand(BaseModel):
    origin: str
    deviceId: str = Field(min_length=1, max_length=160)
    courses: dict[str, str] = Field(min_length=1, max_length=50)

class SyncCommand(BaseModel):
    grant: str = Field(min_length=20, max_length=200)
    deviceId: str
    origin: str
    courseId: str
    externalCourseId: str
    skill: str
    items: list[dict] = Field(max_length=200)
    complete: bool = False
    checkpoint: str | None = None
    status: str = 'completed'

class CanvasReader:
    def __init__(self, store): self.svc = AcademicPlanningService(store)

    def pair(self, owner, command):
        approved = origin(command['origin'])
        token = secrets.token_urlsafe(32)
        with self.svc.store.transaction() as conn:
            for course in command['courses'].values(): self.svc.course(conn, owner, course)
            device = issue_device_grant(conn,owner,'Canvas at '+approved,kind='canvas')
            item = {'id': secrets.token_hex(16), 'origin': approved, 'deviceId': device['id'], 'courses': command['courses'], 'grantHash': hashlib.sha256(token.encode()).hexdigest(), 'expiresAt': device['expiresAt'], 'status': 'paired', 'lastSuccessfulSync': None}
            self.svc.put(conn, 'canvas_connections', owner, item)
        return {**self.public(item), 'grant': token, 'authToken':device['token']}

    @staticmethod
    def public(item): return {k: v for k, v in item.items() if k != 'grantHash'}

    def sync(self, owner, connection_id, command):
        principal=current_principal()
        if principal.kind=='canvas' and principal.device_id!=command['deviceId']:
            raise AcademicError('canvas_device_mismatch','This grant belongs to another paired browser.',403)
        with self.svc.store.engine.connect() as conn:
            item = next((i for i in self.svc.rows(conn, 'canvas_connections', owner) if i['id'] == connection_id), None)
        if not item or item['status'] != 'paired' or item['expiresAt'] <= time.time() or not secrets.compare_digest(item['grantHash'], hashlib.sha256(command['grant'].encode()).hexdigest()):
            raise AcademicError('canvas_pairing_expired', 'Reconnect this browser.', 403)
        if origin(command['origin']) != item['origin'] or command['deviceId'] != item['deviceId'] or item['courses'].get(command['externalCourseId']) != command['courseId']:
            raise AcademicError('canvas_scope_mismatch', 'The browser or course is outside this pairing.', 403)
        if command['skill'] not in SKILLS: raise AcademicError('canvas_skill_blocked', 'Unsupported browser read.', 403)
        imported = []
        for raw in command['items']:
            canvas_student = raw.get('canvasStudentId')
            if not canvas_student: raise AcademicError('canvas_student_unconfirmed','Confirm the authenticated student context before importing.',409)
            if item.get('canvasStudentId') and item['canvasStudentId']!=str(canvas_student):
                raise AcademicError('canvas_account_changed','Canvas account changed. Pair this browser again.',409)
            item['canvasStudentId']=str(canvas_student)
            if not raw.get('updated_at') and not raw.get('revision'):
                raw = dict(raw, revision='content:'+hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest())
            locator = raw.get('locator', '')
            parsed = urlparse(locator)
            if f'{parsed.scheme}://{parsed.netloc}' != item['origin'] or not parsed.path.startswith('/courses/'+command['externalCourseId']):
                raise AcademicError('canvas_locator_blocked', 'Source is outside the approved course.', 403)
            if command['skill'] == 'assignments':
                fields = {'title': str(raw.get('name', 'Assignment'))[:500], 'instructions': str(raw.get('description', ''))[:20000], 'due': {'kind': 'instant', 'value': raw['due_at']} if raw.get('due_at') else {'kind': 'unknown'}}
                imported.append(self.svc.ingest(owner, command['courseId'], {'kind': 'assignment', 'externalId': str(raw['id']), 'origin': 'canvas', 'fields': fields, 'source': {'locator': locator, 'revision': str(raw.get('updated_at') or raw.get('revision') or 'unknown'), 'studentSpecific': True, 'connectionId': connection_id}, 'idempotencyKey': f'{connection_id}:{raw["id"]}:{raw.get("updated_at", raw.get("revision", "unknown"))}'}))
            elif command['skill'] in {'modules','syllabus','announcements','calendar'}:
                # These are material/expectation observations. No title heuristic
                # is allowed to fabricate an exam or demonstrated capability.
                title = str(raw.get('name') or raw.get('title') or command['skill'])[:500]
                content = str(raw.get('syllabus_body') or raw.get('message') or raw.get('description') or '')[:20000]
                external = f'{command["skill"]}:{raw.get("id", command["externalCourseId"])}'
                imported.append(self.svc.ingest(owner,command['courseId'],{'kind':'coverage','externalId':external,'origin':'canvas','fields':{'title':title,'instructions':content,'covered':{'certainty':'expected_not_demonstrated','items':raw.get('items',[])[:100]}},'source':{'locator':locator,'revision':str(raw.get('updated_at') or raw.get('revision') or 'unknown'),'connectionId':connection_id},'idempotencyKey':f'{connection_id}:{external}:{raw.get("updated_at", raw.get("revision", "unknown"))}'}))
        with self.svc.store.transaction() as conn:
            run = {'id': secrets.token_hex(16), 'courseId': command['courseId'], 'connectionId': connection_id, 'skill': command['skill'], 'complete': command['complete'], 'status': command['status'], 'checkpoint': command.get('checkpoint'), 'count': len(command['items']), 'items': command['items'], 'createdAt': time.time(), 'deletionsInferred': False}
            self.svc.put(conn, 'canvas_sync_runs', owner, run)
            if command['complete'] and command['status'] == 'completed': item['lastSuccessfulSync'] = time.time()
            item['lastRun'] = run['id']; item['lastStatus'] = command['status']; item['checkpoint'] = command.get('checkpoint')
            self.svc.put(conn, 'canvas_connections', owner, item)
        return {'run': run, 'imported': len(imported)}

    def disconnect(self, owner, connection_id):
        with self.svc.store.transaction() as conn:
            item = next((i for i in self.svc.rows(conn, 'canvas_connections', owner) if i['id'] == connection_id), None)
            if not item: raise AcademicError('connection_not_found', 'Connection unavailable.', 404)
            principal=current_principal()
            if principal.kind=='canvas' and principal.device_id!=item['deviceId']:
                raise AcademicError('canvas_device_mismatch','Only this paired browser can revoke its connection.',403)
            item.update(status='disconnected', grantHash='', expiresAt=0)
            conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE id=:id AND owner_id=:owner'),{'now':time.time(),'id':item['deviceId'],'owner':owner})
            return self.public(self.svc.put(conn, 'canvas_connections', owner, item))

def build_canvas_router(store_provider):
    router = APIRouter(prefix='/v1/canvas', tags=['canvas-local-reader'])
    def service(db=Depends(store_provider)): return CanvasReader(db)
    def call(fn):
        try: return fn()
        except AcademicError as exc: raise HTTPException(exc.status, detail={'code': exc.code, 'message': str(exc)}) from exc
    @router.post('/pair')
    def pair(command: PairCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.pair(owner, command.model_dump()))
    @router.get('/connections')
    def listing(owner=Depends(material_owner), svc=Depends(service)):
        with svc.svc.store.engine.connect() as conn: return [svc.public(i) for i in svc.svc.rows(conn, 'canvas_connections', owner)]
    @router.post('/connections/{connection_id}/sync')
    def sync(connection_id: str, command: SyncCommand, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.sync(owner, connection_id, command.model_dump()))
    @router.delete('/connections/{connection_id}')
    def disconnect(connection_id: str, owner=Depends(material_owner), svc=Depends(service)): return call(lambda: svc.disconnect(owner, connection_id))
    return router
