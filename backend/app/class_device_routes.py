from typing import Literal
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from .class_devices import ClassDeviceService
from .in_class_models import ClassPolicy
from .material_routes import material_owner


class DraftInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    commandId: str = Field(min_length=1, max_length=160)
    deviceId: str = Field(min_length=1, max_length=160)
    startedAtMs: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    courseId: str | None = Field(default=None, max_length=160)
    buddyId: str | None = Field(default=None, max_length=160)
    materialVersionIds: list[str] = Field(default_factory=list, max_length=100)
    policy: ClassPolicy = Field(default_factory=ClassPolicy)


class PairInput(BaseModel):
    commandId: str = Field(min_length=1, max_length=160)
    deviceId: str = Field(min_length=1, max_length=160)


class ClaimInput(PairInput):
    code: str = Field(min_length=12, max_length=80)
    consent: bool
    captureCapability: str = Field(min_length=32, max_length=128)


class HeartbeatInput(BaseModel):
    state: Literal['paired', 'recording', 'paused', 'stopped', 'interrupted']
    audioEndMs: int = Field(ge=0, le=86400000)
    sealedChunkCount: int = Field(ge=0, le=10000)
    backlog: int = Field(default=0, ge=0, le=10000)
    batteryPercent: int | None = Field(default=None, ge=0, le=100)
    endClass: bool = False


class CaptureCommandInput(BaseModel):
    commandId: str = Field(min_length=1, max_length=160)
    runId: str = Field(min_length=1, max_length=160)
    expectedRevision: int = Field(ge=1)
    action: Literal['pause', 'resume', 'stop', 'handoff']


class AckInput(BaseModel):
    accepted: bool
    state: Literal['paired', 'recording', 'paused', 'stopped', 'interrupted']
    audioEndMs: int = Field(default=0, ge=0, le=86400000)
    sealedChunkCount: int = Field(default=0, ge=0, le=10000)


def build_class_device_router(get_store):
    router = APIRouter(prefix='/v1', tags=['class-devices'])
    def service():
        return ClassDeviceService(get_store())
    @router.post('/class-sessions/drafts')
    def draft(body: DraftInput, owner=Depends(material_owner)):
        return service().draft(owner, body)
    @router.post('/class-sessions/{class_id}/pairings')
    def pairing(class_id: str, body: PairInput, owner=Depends(material_owner)):
        return service().pairing(owner, class_id, body)
    @router.post('/class-pairings/claim')
    def claim(body: ClaimInput, request: Request, owner=Depends(material_owner)):
        return service().claim(owner, body, request.client.host if request.client else 'unknown')
    @router.get('/class-sessions/{class_id}/capture-status')
    def status(class_id: str, owner=Depends(material_owner)):
        return service().status(owner, class_id)
    @router.post('/class-sessions/{class_id}/capture-runs/{run_id}/heartbeat')
    def heartbeat(class_id: str, run_id: str, body: HeartbeatInput, owner=Depends(material_owner), capability: str=Header(alias='X-Capture-Capability', min_length=32, max_length=128)):
        return service().heartbeat(owner, class_id, run_id, body, capability)
    @router.post('/class-sessions/{class_id}/capture-commands')
    def command(class_id: str, body: CaptureCommandInput, owner=Depends(material_owner)):
        return service().command(owner, class_id, body)
    @router.post('/class-sessions/{class_id}/capture-commands/{command_id}/ack')
    def ack(class_id: str, command_id: str, body: AckInput, owner=Depends(material_owner), capability: str=Header(alias='X-Capture-Capability', min_length=32, max_length=128)):
        return service().ack(owner, class_id, command_id, body, capability)
    @router.delete('/class-sessions/{class_id}/pairings/{pairing_id}')
    def revoke(class_id: str, pairing_id: str, owner=Depends(material_owner)):
        from sqlalchemy import text
        svc=service()
        with svc.store.transaction() as conn:
            svc.classes.row(conn, owner, class_id)
            conn.execute(text("UPDATE class_pairings SET state='revoked' WHERE id=:id AND class_id=:class AND owner_id=:owner AND state='pending'"), {'id':pairing_id,'class':class_id,'owner':owner})
        return {'status':'revoked'}
    return router
