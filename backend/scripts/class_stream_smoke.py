"""One real, metered relay session with local synthetic speech (under 30s)."""
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import wave
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.class_streaming import build_class_streaming_router
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.in_class_models import ClassCreate
from backend.app.in_class_service import InClassService
from backend.app.storage import Store


def main():
    logging.getLogger('alembic').setLevel(logging.ERROR)
    source=Path('work/class-synthetic-smoke.wav')
    with wave.open(str(source),'rb') as audio:
        if audio.getnframes()/audio.getframerate()>30:raise SystemExit('Synthetic fixture exceeds 30s.')
    key=dotenv_values('backend/.env').get('ASSEMBLYAI_API_KEY') or os.getenv('ASSEMBLYAI_API_KEY')
    if not key:raise SystemExit('AssemblyAI key unavailable.')
    os.environ.update(ASSEMBLYAI_API_KEY=key,OPENLEARN_CLASS_STREAMING_ENABLED='true',OPENLEARN_CLASS_VERIFICATION_ENABLED='false',OPENLEARN_CLASS_STREAMING_MODEL='universal-3-6-pro',OPENLEARN_CLASS_STREAM_SECRET=uuid4().hex+uuid4().hex,OPENLEARN_USAGE_MODE='enforce',OPENLEARN_USAGE_PAID_ROUTES_ENABLED='true',OPENLEARN_PROVIDER_RATE_VERSION='assemblyai-official-2026-10-13',OPENLEARN_ASSEMBLYAI_STREAMING_USD_PER_MINUTE='.0075',OPENROUTER_MODEL='openrouter/free',AI_TUTOR_ENV='development')
    root=Path('work')/('class-stream-smoke-'+uuid4().hex);root.mkdir(parents=True)
    os.environ['AI_TUTOR_NOTE_VAULT_DIR']=str(root/'notes');os.environ['AI_TUTOR_RECORDINGS_DIR']=str(root/'audio')
    ffmpeg='C:/Users/harsh/miniforge3/Library/bin/ffmpeg.exe'
    raw=subprocess.run([ffmpeg,'-v','error','-i',str(source),'-f','s16le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True,timeout=20).stdout+b'\0'*48000
    store=Store(root/'ledger.sqlite')
    try:
        body=ClassCreate(recording={'id':'rec_'+uuid4().hex,'title':'Synthetic acceptance','startedAtMs':1},deviceId='synthetic',captureCapability='c'*64)
        item=InClassService(store).create('synthetic-acceptance',body)['session']
        app=FastAPI();app.add_middleware(IdentityMiddleware,store_provider=lambda:store);app.include_router(build_class_streaming_router(lambda:store))
        path='/v1/class-sessions/'+item['id'];started=time.monotonic();errors=0;captions=0
        with TestClient(app) as client:
            response=client.post(path+'/transcription-sessions',headers={'X-Dev-Learner-Id':'synthetic-acceptance','X-Capture-Capability':'c'*64,'Idempotency-Key':uuid4().hex},json={'anchorMs':0})
            if response.status_code!=200:raise RuntimeError('Relay session authorization failed: '+str(response.status_code))
            with client.websocket_connect(path+'/audio-stream') as socket:
                socket.send_json({'ticket':response.json()['ticket']})
                if socket.receive_json()['type']!='ready':raise RuntimeError('Provider relay did not connect.')
                for offset in range(0,len(raw),3200):
                    frame=raw[offset:offset+3200]
                    socket.send_bytes(frame+b'\0'*(3200-len(frame)));time.sleep(.1)
                socket.send_json({'type':'stop'})
                for _ in range(100):
                    event=socket.receive_json()
                    if event['type']=='caption':captions+=1
                    if event['type']=='error':errors+=1;break
                    if event['type']=='rotate':break
        with store.engine.connect() as conn:
            final=conn.execute(text('SELECT COUNT(*) FROM class_live_transcript_segments WHERE class_id=:class'),{'class':item['id']}).scalar_one()
            cost=conn.execute(text("SELECT COALESCE(SUM(cost_nano),0) FROM usage_events WHERE owner_id='synthetic-acceptance'")).scalar_one()
        report={'fixture':'synthetic speech; not native or lecture accuracy acceptance','model':'universal-3-6-pro','captionEvents':captions,'savedFinalCaptions':final,'errors':errors,'elapsedSeconds':round(time.monotonic()-started,2),'estimatedCostUsd':cost/1e9}
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
        if errors or not final:raise RuntimeError('No final caption persisted; inspect private local test data.')
    finally:store.close()


if __name__=='__main__':main()
