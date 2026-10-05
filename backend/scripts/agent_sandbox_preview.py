"""Explicit offline CLI acceptance: emulated remote adapter, real API/UI/store.

No production fixture route, credentials, arbitrary execution or paid calls.
"""
import argparse
import json
import os
from pathlib import Path


class OfflineSandbox:
    runtime='offline_sandbox_fixture'
    runtime_version='offline-fixture-v1'
    is_test_adapter=True
    def __init__(self):self.resources={};self.counter=0
    def create(self,key,policy):
        self.counter+=1;identifier='offline-'+str(self.counter)
        self.resources[identifier]={'key':key,'files':{}}
        return identifier
    def reconcile(self,key):return next((id for id,row in self.resources.items() if row['key']==key),None)
    def stage(self,id,files):self.resources[id]['files'].update(files)
    def execute(self,id,timeout):
        from backend.app.agent_execution.tools import analyze
        row=self.resources[id];result=analyze(json.loads(row['files']['/workspace/uploads/task.json']))
        for output in result['outputs']:row['files']['/workspace/outputs/'+output['name']]=output['content']
        row['files']['/workspace/outputs/report.json']=json.dumps({'summary':result['summary'],'completion':result['completion']},sort_keys=True).encode()
    def download(self,id,path,maximum):return self.resources[id]['files'][path]
    def release(self,id):self.resources.pop(id,None)


class OfflineTeacher:
    provider_name='offline-teaching-fixture'
    def complete_json(self,prompt,max_tokens=4000):
        if prompt.startswith('You author'):
            data,_=json.JSONDecoder().raw_decode(prompt[prompt.index('\n{')+1:]);context=data['context']
            return {'concept_id':context['conceptIds'][0],'kind':'single','stem':'If the same distance is covered in half the time, how does the speed change?',
                'reasoning_target':'Predict the inverse relationship between time and speed at fixed distance.','family':'lab_speed_transfer',
                'options':[{'id':'a','label':'Halves'},{'id':'b','label':'Doubles'}],'correct_ids':['b'],
                'solution':'A fixed numerator divided by half the denominator gives twice the original quotient.',
                'criteria':[{'id':'speed','description':'Predicts speed from the relationship of distance to time','weight':1}],
                'hints':['Keep the distance fixed and compare the two elapsed times.'],'source_ids':[context['sources'][0]['spanId']]}
        if prompt.startswith('Independently'):return {'unambiguous':True,'concept_test':True,'novel':True,'supported':True,'correct_ids':['b'],'solution':'At fixed distance, half the time yields twice the speed.'}
        return {'blocks':[{'kind':'explanation','heading':'Offline teaching fixture: speed','body':'For trial 1, speed = 10 centimeters / 2 seconds = 5 cm/s. Trial 2 gives 20 / 4 = 5 cm/s. Trial 3 was explicitly excluded. This wording is synthetic acceptance data.'}]}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8007);parser.add_argument('--data',default='work/agent-sandbox-preview');args=parser.parse_args()
    directory=Path(args.data).resolve();directory.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite+pysqlite:///'+str(directory/'preview.sqlite').replace('\\','/'),
        AI_TUTOR_ENV='development',AI_TUTOR_PROVIDER='deterministic_baseline',AI_TUTOR_DEV_IDENTITY='true',
        OPENLEARN_AGENT_ADMISSION_ENABLED='true',OPENLEARN_WORKER_MODE='embedded',
        OPENLEARN_BROWSER_ASSISTANT_ENABLED='false',FORMA_WEB_ORIGIN='http://localhost:5173',
        OPENLEARN_ASSISTANT_OBJECTS_DIR=str(directory/'objects'),AI_TUTOR_MATERIAL_DIR=str(directory/'materials'),AI_TUTOR_NOTE_VAULT_DIR=str(directory/'notes'))
    from backend.app.agent_execution import sandbox_config,worker
    from backend.app.agent_execution.sandbox import SandboxService
    from backend.app.agent_execution.sandbox_config import SandboxPolicy
    sandbox_config.readiness=lambda:{'state':'available','reasonCode':'offline_fixture','runtime':'offline_sandbox_fixture'}
    adapter=OfflineSandbox();policy=SandboxPolicy(enabled=True,snapshot='offline-fixture-v1')
    OriginalWorker=worker.AgentWorker
    class PreviewWorker(OriginalWorker):
        def __init__(self,store,provider_getter=lambda:None):super().__init__(store,provider_getter,sandbox_factory=lambda db:SandboxService(db,adapter,policy))
    worker.AgentWorker=PreviewWorker
    from backend.app import main as api
    api.lesson_provider=OfflineTeacher()
    from backend.app.models import TopicScope,utc_now
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    scope=TopicScope(id='sandbox-preview-scope',topic='Motion and speed',resolved_meaning='Motion and speed',objective='Inspect verified sandbox analysis and teaching',depth='introductory',created_at=utc_now())
    api.store.save_scope(scope);graph=GraphGenerator().generate(scope);api.store.save_graph(graph)
    from backend.app.identity import grant_resource
    with api.store.transaction() as conn:
        grant_resource(conn,'topic_scopes',scope.id,'local')
        grant_resource(conn,'graph_versions',graph.id,'local')
    api.store.save_session(LearningSession(id='sandbox-preview-session',learner_id='local',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    import uvicorn
    print('Offline sandbox + teaching fixture only. Open /s/sandbox-preview-session; no live Daytona calls.')
    uvicorn.run(api.app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
