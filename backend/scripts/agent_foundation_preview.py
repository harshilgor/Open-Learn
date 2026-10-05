"""Offline browser acceptance fixture. Uses an isolated DB and zero paid calls."""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8006)
    parser.add_argument('--data',default='work/agent-preview')
    args=parser.parse_args();directory=Path(args.data).resolve();directory.mkdir(parents=True,exist_ok=True)
    os.environ.update(DATABASE_URL='sqlite+pysqlite:///'+str(directory/'preview.sqlite').replace('\\','/'),
        AI_TUTOR_ENV='development',AI_TUTOR_PROVIDER='deterministic_baseline',AI_TUTOR_DEV_IDENTITY='true',
        OPENLEARN_AGENT_ADMISSION_ENABLED='true',OPENLEARN_WORKER_MODE='embedded',
        OPENLEARN_BROWSER_ASSISTANT_ENABLED='false',FORMA_WEB_ORIGIN='http://localhost:5173',
        OPENLEARN_ASSISTANT_OBJECTS_DIR=str(directory/'objects'))
    from backend.app import main as api
    from backend.app.models import TopicScope,utc_now
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    from backend.app.agent_execution.worker import AgentWorker
    from backend.app.agent_execution.research import ResearchService
    from backend.app.web_evidence.config import WebEvidenceConfig
    from backend.app.web_evidence.models import ProviderSearchHit,ProviderOpenResult,SourceClassification
    from backend.app.web_evidence.provider import FakeWebEvidenceProvider
    from backend.app.web_evidence.service import WebEvidenceService
    scope=TopicScope(id='agent-preview-scope',topic='Lab analysis',resolved_meaning='Lab analysis',objective='Inspect agent execution',depth='introductory',created_at=utc_now())
    api.store.save_scope(scope);graph=GraphGenerator().generate(scope);api.store.save_graph(graph)
    api.store.save_session(LearningSession(id='agent-preview-session',learner_id='local',graph_id=graph.id,created_at=utc_now(),updated_at=utc_now()))
    provider=FakeWebEvidenceProvider(hits=[ProviderSearchHit(provider_result_ref='fixture',title='Offline study-methods fixture',url='https://example.org/offline-fixture',domain='example.org',excerpt='Fixture: retrieval practice improved recall.',classification=SourceClassification.primary)],
        open_results={'fixture':ProviderOpenResult(provider_result_ref='fixture',title='Offline study-methods fixture',url='https://example.org/offline-fixture',domain='example.org',excerpt='Offline fixture only: repeated retrieval improved delayed recall compared with rereading.')})
    evidence=WebEvidenceService(api.store,WebEvidenceConfig(enabled=True,provider_name='fake',exa_api_key='test-only'),provider=provider)
    class PreviewWorker(AgentWorker):
        def __init__(self,store,provider_getter=lambda:None):
            super().__init__(store,provider_getter,research_factory=lambda db:ResearchService(db,evidence_service=evidence))
    from backend.app.agent_execution import worker
    worker.AgentWorker=PreviewWorker
    print(f'Offline fixture API on port {args.port}; use /s/agent-preview-session in the web app. Research is synthetic test evidence.')
    import uvicorn
    uvicorn.run(api.app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
