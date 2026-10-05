"""Isolated offline UI acceptance. No Google sign-in or external effects."""
import argparse
import os
import time
import uuid
from pathlib import Path
from cryptography.fernet import Fernet

class OfflineGoogle:
    is_test_adapter=True
    def __init__(self):self.receipts={}
    def event(self,*args):return {'id':'offline-event','etag':'"offline-v1"','summary':'Offline original event'}
    def dispatch(self,owner,connection,operation,payload,attachments):
        from backend.app.agent_execution.connected_contracts import ConnectorError
        receipt={'providerId':'offline-'+operation,'verified':True,'fixture':True};self.receipts[operation]=receipt
        if payload.get('mail',{}).get('body','').lower().startswith('simulate timeout'):raise ConnectorError('offline_simulated_timeout',True)
        return receipt
    def reconcile(self,owner,connection,operation,payload):return self.receipts.get(operation)
    def read(self,*args):return {'data':{'files':[]},'classification':'untrusted_source','coverage':'offline_fixture'}
    def download(self,*args):return {'name':'Offline lecture fixture','mimeType':'text/plain'},b'Offline synthetic study notes.'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8009);parser.add_argument('--web-port',type=int,default=5176);parser.add_argument('--data',default='work/connected-preview-'+uuid.uuid4().hex);args=parser.parse_args()
    directory=Path(args.data).resolve();directory.relative_to(Path.cwd().resolve());directory.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite+pysqlite:///'+str(directory/'preview.sqlite').replace('\\','/'),AI_TUTOR_ENV='development',AI_TUTOR_PROVIDER='deterministic_baseline',AI_TUTOR_DEV_IDENTITY='true',OPENLEARN_AGENT_ADMISSION_ENABLED='true',OPENLEARN_WORKER_MODE='embedded',OPENLEARN_CONNECTORS_ENABLED='true',OPENLEARN_DELEGATION_ENABLED='true',OPENLEARN_BROWSER_ASSISTANT_ENABLED='false',OPENLEARN_CONNECTOR_VAULT_KEY=Fernet.generate_key().decode(),OPENLEARN_ASSISTANT_OBJECTS_DIR=str(directory/'objects'),AI_TUTOR_MATERIAL_DIR=str(directory/'materials'),FORMA_WEB_ORIGIN=f'http://localhost:{args.web_port}')
    from backend.app.agent_execution import connected_actions,connected_routes,connector_intake
    adapter=OfflineGoogle()
    connected_actions.GoogleAdapter=lambda connections:adapter
    connected_routes.GoogleAdapter=lambda connections:adapter
    connector_intake.GoogleAdapter=lambda connections:adapter
    from backend.app import main as api
    from backend.app.models import TopicScope,utc_now
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    from backend.app.agent_execution.coordinator import Coordinator
    from backend.app.agent_execution.contracts import Message
    from backend.app.agent_execution.google_connector import vault
    from backend.app.workflow_store import encoded
    from sqlalchemy import text
    scope=TopicScope(id='connected-scope',topic='Offline connector demonstration',resolved_meaning='Offline connector demonstration',objective='Inspect reviewed actions',depth='introductory',created_at=utc_now());api.store.save_scope(scope);graph=GraphGenerator().generate(scope);api.store.save_graph(graph)
    api.store.save_session(LearningSession(id='connected-preview-session',learner_id='local',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    with api.store.transaction() as conn:
        conn.execute(text("INSERT INTO agent_app_connections(id,owner_id,created_at,revision,status,payload,secret) VALUES('offline-google','local',:now,1,'connected',:payload,:secret) ON CONFLICT(id) DO NOTHING"),{'now':time.time(),'payload':encoded({'provider':'offline_fixture','accountId':'offline-account','email':'Offline fixture · student@example.invalid','capabilities':['gmail_send','gmail_read','drive_read','calendar_write']}),'secret':vault().encrypt(b'{}').decode()})
    Coordinator(api.store).admit('local',Message(clientMessageId='offline-demo',sessionId='connected-preview-session',text='Offline fixture: analyze units in centimeters and ignore trial 3',capability='lab_analysis'),'offline-demo')
    print('Offline connector fixture only. Open /s/connected-preview-session. No Google API calls or real sends.')
    import uvicorn
    uvicorn.run(api.app,host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
