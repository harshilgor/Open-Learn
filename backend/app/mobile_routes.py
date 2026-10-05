"""Native adjuncts; learning and lectures keep their existing service owners."""
import hashlib,json,os,time
from fastapi import APIRouter,Header,Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from .identity import current_principal,assert_owner_active,fail
from .workflow_store import encoded
from .agent_execution.repository import digest
from .lecture_provider import configured_transcription_provider,TranscriptionFailure

def build_mobile_router(get_store,transcriber_getter=configured_transcription_provider):
    router=APIRouter(prefix='/v1/mobile',tags=['mobile'])
    def owner():
        principal=current_principal()
        if principal.kind not in {'web','local','desktop'}:fail('device_scope_denied','Sign in with your account.',403)
        return principal.owner_id
    @router.post('/push-token/unlink',status_code=204)
    def unlink_token(body:dict):
        learner=owner();token=body.get('token')
        if not isinstance(token,str) or len(token)>200:fail('invalid_input','Invalid push token.',422)
        with get_store().transaction() as conn:
            assert_owner_active(conn,learner)
            conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE owner_id=:owner AND endpoint_hash=:hash'),{'owner':learner,'hash':hashlib.sha256(token.encode()).hexdigest()})
    @router.post('/voice-transcriptions')
    async def voice(request:Request,idempotency_key:str=Header(alias='Idempotency-Key',min_length=1,max_length=160),duration_ms:int=Header(alias='X-Audio-Duration-Ms',ge=1,le=90000)):
        learner=owner();store=get_store()
        if os.getenv('OPENLEARN_MOBILE_VOICE_ENABLED')!='true':fail('capability_unavailable','Short voice transcription is not configured. Typed messages still work.',503)
        limit=int(os.getenv('OPENLEARN_MOBILE_VOICE_DAILY_CALLS','10'))
        if not 1<=limit<=60:fail('capability_unavailable','Configure a bounded daily voice limit.',503)
        mime=request.headers.get('content-type','').split(';')[0]
        if mime not in {'audio/wav','audio/mp4','audio/webm'}:fail('unsupported_audio','Unsupported voice format.',415)
        content=bytearray()
        async for block in request.stream():
            content.extend(block)
            if len(content)>4*1024*1024:fail('audio_too_large','Voice message exceeds 4 MB.',413)
        if not content:fail('empty_audio','No audio was captured.',422)
        request_hash=digest([hashlib.sha256(content).hexdigest(),mime,duration_ms]);identifier='voice_'+digest([learner,idempotency_key])[:40];now=time.time()
        provider=transcriber_getter()
        with store.transaction() as conn:
            assert_owner_active(conn,learner)
            suffix=' FOR UPDATE' if conn.dialect.name=='postgresql' else ''
            conn.execute(text('SELECT id FROM identity_accounts WHERE id=:owner'+suffix),{'owner':learner}).first()
            existing=conn.execute(text('SELECT * FROM mobile_voice_receipts WHERE id=:id AND owner_id=:owner'),{'id':identifier,'owner':learner}).mappings().first()
            if existing:
                if existing['request_hash']!=request_hash:fail('idempotency_conflict','Voice key has different audio.',409)
                if existing['status']=='completed':return json.loads(existing['payload'])
                fail('voice_outcome_unknown','This transcription was already attempted. Review the saved voice before explicitly trying again.',409)
            count=conn.execute(text('SELECT count(*) FROM mobile_voice_receipts WHERE owner_id=:owner AND created_at>=:start'),{'owner':learner,'start':int(now//86400)*86400}).scalar_one()
            if count>=limit:fail('voice_budget_exhausted','Daily voice transcription limit reached.',429)
            conn.execute(text("INSERT INTO mobile_voice_receipts(id,owner_id,revision,status,request_hash,payload,created_at,updated_at) VALUES(:id,:owner,1,'outcome_unknown',:hash,'{}',:now,:now)"),{'id':identifier,'owner':learner,'hash':request_hash,'now':now})
        try:result=await run_in_threadpool(provider.transcribe_chunk,bytes(content),mime,duration_ms)
        except TranscriptionFailure:fail('transcription_unavailable','Could not transcribe. The phone retains your voice for review.',502)
        payload={'id':identifier,'text':' '.join(span.text for span in result.spans)[:16000],'status':'completed'}
        with store.transaction() as conn:
            assert_owner_active(conn,learner)
            conn.execute(text("UPDATE mobile_voice_receipts SET status='completed',revision=revision+1,payload=:payload,updated_at=:now WHERE id=:id AND owner_id=:owner"),{'id':identifier,'owner':learner,'payload':encoded(payload),'now':time.time()})
        return payload
    return router
