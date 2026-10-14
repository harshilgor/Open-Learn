"""Isolated local browser acceptance server, with mocked speech/text providers."""
import asyncio
import argparse
import hashlib
import io
import os
from pathlib import Path
import wave
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume-root',type=Path);args=parser.parse_args()
    root=args.resume_root.resolve() if args.resume_root else Path('work')/('class-browser-'+uuid4().hex)
    if args.resume_root and (not root.is_relative_to(Path('work').resolve()) or not root.name.startswith('class-browser-')):raise SystemExit('Resume only a workspace acceptance fixture.')
    root.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite:///'+(root/'data.sqlite').resolve().as_posix(),AI_TUTOR_ENV='development',AI_TUTOR_DEV_IDENTITY='true',AI_TUTOR_NOTE_VAULT_DIR=str(root/'notes'),AI_TUTOR_RECORDINGS_DIR=str(root/'audio'),OPENLEARN_USAGE_PAID_ROUTES_ENABLED='false',OPENLEARN_CLASS_VERIFICATION_ENABLED='false',OPENLEARN_CLASS_STREAMING_ENABLED='false',OPENLEARN_CLASS_PHONE_PAIRING_ENABLED='true',OPENLEARN_CLASS_BUDDY_ENABLED='true',OPENLEARN_CLASS_TOPIC_NOTES_ENABLED='true',OPENLEARN_CLASS_VISUAL_NOTES_ENABLED='true',OPENLEARN_CLASS_AUTO_VISUALS_ENABLED='false',OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS='false',OPENLEARN_MIGRATE_ON_START='true',OPENLEARN_WORKER_MODE='embedded',OPENLEARN_WEB_SEARCH_ENABLED='false')
    from backend.tests.test_in_class import Provider as BaseProvider,Transcriber
    class Provider(BaseProvider):
        provider_name='acceptance-fixture';model='fixture';last_usage=None
        segment_id=''
        def complete_json(self,prompt,tokens=4000):
            if prompt.startswith('CLASS_VISUAL_V1'):
                return {'kind':'concept_map','title':'Cell structure','description':'A labeled schematic from the mocked lecture fixture.','nodes':[{'id':'cell','label':'Cell'},{'id':'membrane','label':'Membrane'},{'id':'nucleus','label':'Nucleus'}],'edges':[{'source':'cell','target':'membrane','label':'has boundary'},{'source':'cell','target':'nucleus','label':'contains'}]}
            return super().complete_json(prompt,tokens)
        async def stream_text(self,*args,**kwargs):
            body='The lecture describes a cell with a membrane and a nucleus. The membrane is its boundary. '+f'[lecture 00:00](class-evidence:{self.segment_id})'
            for offset in range(0,len(body),24):
                await asyncio.sleep(.02);yield body[offset:offset+24]
    provider=Provider()
    import backend.app.model_provider as model_provider
    model_provider.configured_lesson_provider=lambda:provider
    from backend.app.main import app,store
    from backend.app.in_class_service import InClassService
    from backend.app.in_class_models import ClassCreate
    from backend.app.lecture_service import LectureService
    from backend.app.lecture_pipeline import transcribe_chunk
    from backend.app.lecture_models import LectureFinalize
    from backend.app.class_document import ClassDocumentService
    from backend.app.class_visuals import ClassVisualService,VisualRequest
    from sqlalchemy import text
    classes=InClassService(store,provider)
    with store.engine.connect() as conn:existing=conn.execute(text('SELECT 1 FROM class_sessions WHERE id=:id'),{'id':'class_rec_'+'a'*32}).first() is not None
    body=ClassCreate(recording={'id':'rec_'+'a'*32,'title':'Cell structure · Mocked acceptance class','startedAtMs':1},deviceId='fixture',policy={'notes':True,'materials':False,'practice':False,'flashcards':False})
    item=classes.create('local',body)['session'];lecture=LectureService(store)
    if existing:
        # Older fixture runs predate explicit setup ownership. Repair only this
        # isolated fixture's unchanged scope/graph, never production resources.
        session=store.get_session(item['sessionId']);graph=store.get_graph(session.graph_id);scope=store.get_scope(graph.scope_id)
        from backend.app.usage.context import usage_scope
        with usage_scope(store,'local','class-setup:'+body.recording.id):
            store.save_scope(scope);store.save_graph(graph)
    for index in range(0 if existing else 2):
        memory=io.BytesIO()
        with wave.open(memory,'wb') as audio:audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0'*16000*2*5)
        content=memory.getvalue()
        lecture.put_chunk('local',body.recording.id,index,content,start_ms=index*5000,end_ms=(index+1)*5000,media_type='audio/wav',checksum=hashlib.sha256(content).hexdigest())
        transcribe_chunk(store,'local',body.recording.id,index,Transcriber())
    if not existing:lecture.finalize('local',body.recording.id,LectureFinalize(expectedChunkCount=2,durationMs=10000))
    for _ in range(8):classes.tick(4)
    with store.engine.connect() as conn:provider.segment_id=conn.execute(text('SELECT id FROM lecture_transcript_segments WHERE recording_id=:recording ORDER BY start_ms LIMIT 1'),{'recording':body.recording.id}).scalar_one()
    block=ClassDocumentService(store).page('local',item['id'])['items'][0]
    if not existing:ClassVisualService(classes).request('local',item['id'],VisualRequest(commandId='fixture',blockId=block['id'],expectedRevision=block['revision'],kind='concept_map'))
    classes.tick(1)
    (root/'class-id.txt').write_text(item['id'],encoding='utf-8')
    print('ISOLATED_MOCK_CLASS='+item['id'],flush=True)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8795,log_level='warning')


if __name__=='__main__':main()
