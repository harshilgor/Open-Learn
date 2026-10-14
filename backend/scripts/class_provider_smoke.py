"""One metered synthetic-audio provider check; never retries a paid submission."""
import argparse
import json
import os
from pathlib import Path
import time
import wave
from uuid import uuid4
from dotenv import dotenv_values
from sqlalchemy import text
from backend.app.assemblyai_transcription import AssemblyAITranscriptionAdapter
from backend.app.storage import Store
from backend.app.usage.context import usage_scope


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio',type=Path)
    args=parser.parse_args()
    with wave.open(str(args.audio),'rb') as source:
        duration=int(source.getnframes()/source.getframerate()*1000)
    if not 0<duration<=30000:raise SystemExit('Use synthetic PCM WAV audio under 30 seconds.')
    config=dotenv_values(Path('backend/.env'))
    key=config.get('ASSEMBLYAI_API_KEY') or os.getenv('ASSEMBLYAI_API_KEY')
    if not key:raise SystemExit('AssemblyAI key unavailable.')
    # Isolated process/test ledger; never changes application feature flags.
    os.environ.update(OPENLEARN_USAGE_MODE='enforce',OPENLEARN_USAGE_PAID_ROUTES_ENABLED='true',OPENLEARN_PROVIDER_RATE_VERSION='assemblyai-official-2026-10-13',OPENLEARN_ASSEMBLYAI_STT_USD_PER_MINUTE='.0035',OPENROUTER_MODEL='openrouter/free')
    root=Path('work')/('class-provider-smoke-'+uuid4().hex);root.mkdir(parents=True)
    store=Store(root/'ledger.sqlite');provider=AssemblyAITranscriptionAdapter(key=key,model='universal-3-5-pro')
    identifier=None;started=time.monotonic()
    try:
        url=provider.upload(args.audio.read_bytes())
        with usage_scope(store,'synthetic-acceptance','class-provider-smoke'):
            identifier=provider.submit(url,duration)
        # Persist receipt before polling; private file stays outside source control.
        (root/'receipt.json').write_text(json.dumps({'requestId':identifier,'durationMs':duration}),encoding='utf-8')
        result=None
        while time.monotonic()-started<180:
            result=provider.get(identifier,duration)
            if result.status=='completed':break
            time.sleep(2)
        if result is None or result.status!='completed':raise RuntimeError('Provider poll deadline reached; request receipt retained.')
        with store.engine.connect() as conn:
            cost=conn.execute(text("SELECT COALESCE(SUM(cost_nano),0) FROM usage_events WHERE owner_id='synthetic-acceptance'")).scalar_one()
        report={'fixture':'synthetic speech; not a lecture accuracy evaluation','status':result.status,'model':result.model,'durationMs':duration,'wordCount':len(result.words),'elapsedSeconds':round(time.monotonic()-started,2),'estimatedCostUsd':cost/1e9,'transcript':result.text}
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        # Public output contains aggregate measurements only.
        print(json.dumps({key:value for key,value in report.items() if key!='transcript'}))
        provider.delete(identifier)
        print('Provider transcript deleted; private report and metered receipt retained locally.')
    finally:
        store.close()


if __name__=='__main__':main()
