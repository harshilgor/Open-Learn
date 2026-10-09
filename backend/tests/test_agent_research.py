"""Research-to-durable-output tests; all providers are deterministic or mocked."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.agent_execution.artifacts import Artifacts
from backend.app.agent_execution.contracts import Message
from backend.app.agent_execution.coordinator import Coordinator
from backend.app.agent_execution.repository import Repository
from backend.app.agent_execution.research import ResearchService
from backend.app.agent_execution.research_contracts import ResearchSpec, ResearchUnavailable
from backend.app.agent_execution.research_sources import ResearchSources
from backend.app.agent_execution.research_routes import build_research_router
from backend.app.agent_execution.routes import build_agent_router
from backend.app.agent_execution.worker import AgentWorker
from backend.app.agent_execution.learning import ContinuationRequest, LearningContinuation
from backend.app.agent_execution.connected_contracts import ChildRequest
from backend.app.agent_execution.delegation import Delegation
from backend.app.browser_assistant.routes import build_assistant_router
from backend.app.identity_middleware import IdentityMiddleware
from backend.app.material_models import UploadRequest
from backend.app.material_service import MaterialService
from backend.app.graph_generator import GraphGenerator
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.storage import Store
from backend.app.web_evidence.clock import FakeClock
from backend.app.web_evidence.config import WebEvidenceConfig
from backend.app.web_evidence.exa import ExaWebEvidenceProvider
from backend.app.web_evidence.models import ProviderOpenResult, ProviderSearchHit, SourceClassification
from backend.app.web_evidence.provider import FakeWebEvidenceProvider
from backend.app.web_evidence.retention import EvidenceRetention
from backend.app.web_evidence.service import WebEvidenceService


@pytest.fixture
def research_env(monkeypatch):
    # Avoid pytest's restrictive temporary directory permissions on this host.
    tmp_path = Path.cwd() / "backend" / "data" / ("agent-research-" + uuid4().hex)
    tmp_path.mkdir(parents=True)
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    monkeypatch.setenv("OPENLEARN_AGENT_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_WORKER_MODE", "external")
    monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("OPENLEARN_OBJECT_BACKEND", "local")
    store = Store(tmp_path / "research.db")
    scope = TopicScope(id="research_scope", topic="Study methods", resolved_meaning="Study methods",
                       objective="Learn", depth="introductory", created_at=utc_now())
    graph = GraphGenerator().generate(scope)
    store.save_scope(scope)
    store.save_graph(graph)
    for owner in ("alice", "bob"):
        store.save_session(LearningSession(id=f"research_session_{owner}", learner_id=owner, graph_id=graph.id,
                                           created_at=utc_now(), updated_at=utc_now()))
    clock = FakeClock(datetime.now(timezone.utc))
    provider = FakeWebEvidenceProvider(hits=[ProviderSearchHit(provider_result_ref="paper1", title="Study methods paper",
        url="https://www.nist.gov/research/study-methods", domain="www.nist.gov",
        excerpt="Repeated retrieval can improve later recall.", classification=SourceClassification.primary)],
        open_results={"paper1": ProviderOpenResult(provider_result_ref="paper1", title="Study methods paper",
            url="https://www.nist.gov/research/study-methods", domain="www.nist.gov",
            excerpt="In this experiment, repeated retrieval improved delayed recall compared with rereading.")})
    cfg = WebEvidenceConfig(enabled=True, provider_name="fake", exa_api_key="test-only", result_ttl_seconds=60,
                            cache_ttl_seconds=30, max_chars_per_source=1200)
    evidence = WebEvidenceService(store, cfg, provider=provider, clock=clock)
    yield store, clock, provider, evidence
    store.close()


def task(store, spec=None, owner="alice", key="request1"):
    spec = spec or {"query": "Does retrieval practice improve recall?", "sourcePolicy": "external"}
    body = Message(clientMessageId=key, sessionId=f"research_session_{owner}", text=spec["query"],
                   capability="research", researchSpec=spec)
    admitted = Coordinator(store).admit(owner, body, key)
    return Repository(store).read(owner, admitted["references"][0]["id"])


def test_research_outputs_use_opened_content_and_survive_response_expiry(research_env):
    store, clock, provider, evidence = research_env
    run = task(store)
    service = ResearchService(store, evidence_service=evidence, retention_seconds=3600)
    result = service.prepare("alice", run, run["researchSpec"])
    assert len(provider.search_calls) == len(provider.open_calls) == 1
    assert b"In this experiment" in result["outputs"][0]["content"]
    assert len(result["sources"]) == 1
    assert result["completion"]["status"] == "verified"
    machine = json.loads(result["outputs"][1]["content"])
    assert machine["claims"][0]["sourceIds"] == [result["sources"][0]["id"]]
    assert "providerResultRef" not in json.dumps(machine)
    from backend.app.identity_data import export_owner
    exported = export_owner(store, "alice")
    compatibility = exported["compatibility"]
    assert compatibility["restoreMode"] == "safe_content_only"
    assert "assistant_runs" in compatibility["exportOnlyTables"]
    assert compatibility["executionStateRestored"] is False
    assert compatibility["externalApprovalsRestored"] is False
    assert compatibility["providerCredentialsRestored"] is False
    original = [out["content"] for out in result["outputs"]]
    clock.advance(120)
    EvidenceRetention(store, clock).purge_expired()
    restarted = ResearchService(store, evidence_service=WebEvidenceService(store, evidence.config, provider=provider, clock=clock), retention_seconds=3600)
    resumed = restarted.prepare("alice", run, run["researchSpec"])
    assert [out["content"] for out in resumed["outputs"]] == original
    assert len(provider.search_calls) == len(provider.open_calls) == 1


def test_artifacts_publish_once_download_with_integrity_and_owner_scope(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    result = ResearchService(store, evidence_service=evidence).prepare("alice", run, run["researchSpec"])
    artifacts = Artifacts(store)
    operation = {"id": "research_test_operation"}
    with Repository(store).transaction() as conn:
        prepared = artifacts.prepare(conn, run, operation, result["outputs"])
    artifacts.store_outputs(prepared, result["outputs"])
    # Simulate a worker restart after immutable storage but before publication.
    with Repository(store).transaction() as conn:
        recovered = artifacts.prepare(conn, run, operation, result["outputs"])
        published = artifacts.publish(conn, run, operation, recovered)
    assert [item["id"] for item in prepared] == [item["id"] for item in recovered]
    record, content = artifacts.download("alice", published[0]["id"])
    assert content == result["outputs"][0]["content"]
    assert record["lineage"]["sourceIds"]
    with pytest.raises(HTTPException) as denied:
        artifacts.download("bob", published[0]["id"])
    assert denied.value.status_code == 404
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_artifacts")).scalar_one() == 2


def test_unknown_citation_is_rejected_and_no_final_output_is_persisted(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    class InventingModel:
        def complete_json(self, *args):
            return {"claims": [{"text": "Invented result", "sourceIds": ["W99"]}], "limitations": []}
    with pytest.raises(ResearchUnavailable, match="unknown_citation"):
        ResearchService(store, evidence_service=evidence, model_provider=InventingModel()).prepare("alice", run, run["researchSpec"])
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_artifacts")).scalar_one() == 0


def test_unverified_semantic_synthesis_returns_partial_not_green(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    class Model:
        def complete_json(self, prompt, *args):
            payload = json.loads(prompt.split("\n", 1)[1])
            assert payload["question"] == run["researchSpec"]["query"]
            return {"claims": [{"text": "Retrieval appears helpful by 42% in this experiment.",
                                 "sourceIds": [payload["sources"][0]["id"]]}], "limitations": []}
    result = ResearchService(store, evidence_service=evidence, model_provider=Model()).prepare("alice", run, run["researchSpec"])
    assert result["completion"]["status"] == "partial"
    assert any(check["status"] == "unknown" for check in result["completion"]["checks"])
    checks = result["completion"]["checks"]
    assert next(check for check in checks if check["criterion"] == "numeric_literals")["status"] == "unknown"
    manifest = json.loads(result["outputs"][1]["content"])
    assert {item["criterion"]: item["status"] for item in manifest["claims"][0]["checks"]}["numeric_literals"] == "unknown"
    assert any("Numeric literals" in limitation for limitation in manifest["limitations"])


def test_claim_evidence_checks_report_literal_match_without_claiming_semantic_proof():
    from backend.app.agent_execution.research import _claim_evidence_checks
    from backend.app.agent_execution.research_contracts import ResearchClaim
    claim = ResearchClaim(text="The sample included 1,200 learners and improved by 25%.", sourceIds=["source1"])
    sources = {"source1": {"excerpt": "The study included 1,200 learners. Recall improved by 25%."}}
    checks = {item["criterion"]: item["status"] for item in _claim_evidence_checks(claim, sources)}
    assert checks["source_references"] == "pass"
    assert checks["numeric_literals"] == "pass"
    assert checks["semantic_support"] == "unknown"


def test_erasure_during_synthesis_cannot_retain_deleted_content(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    class ErasingModel:
        def complete_json(self, prompt, *args):
            source = json.loads(prompt.split("\n", 1)[1])["sources"][0]
            ResearchSources(store).delete("alice", source["id"])
            return {"claims": [{"text": source["excerpt"], "sourceIds": [source["id"]], "support": "quoted"}]}
    with pytest.raises(ResearchUnavailable, match="source_unavailable"):
        ResearchService(store, evidence_service=evidence, model_provider=ErasingModel()).prepare("alice", run, run["researchSpec"])
    with store.engine.connect() as conn:
        payload = json.loads(conn.execute(text("SELECT payload FROM agent_research_runs WHERE run_id=:id"), {"id": run["id"]}).scalar_one())
        assert "synthesis" not in payload


def test_source_expiry_and_cross_owner_reads(research_env):
    store, clock, _, evidence = research_env
    run = task(store)
    service = ResearchService(store, evidence_service=evidence, retention_seconds=60)
    result = service.prepare("alice", run, run["researchSpec"])
    source_id = result["sources"][0]["id"]
    with pytest.raises(HTTPException) as denied:
        service.sources.read("bob", source_id, include_excerpt=True)
    assert denied.value.status_code == 404
    clock.advance(61)
    with pytest.raises(ResearchUnavailable, match="content_expired"):
        service.sources.read("alice", source_id, include_excerpt=True)
    service.sources.purge_expired()
    assert service.sources.purge_expired() == 0
    with store.engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM agent_research_sources WHERE id=:id"), {"id": source_id}).scalar_one()
        assert "excerpt" not in json.loads(payload)


def test_deleted_source_prevents_restart_from_saved_synthesis(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    service = ResearchService(store, evidence_service=evidence)
    result = service.prepare("alice", run, run["researchSpec"])
    source_id = result["sources"][0]["id"]
    service.sources.delete("alice", source_id)
    with pytest.raises(ResearchUnavailable, match="source_unavailable"):
        service.prepare("alice", run, run["researchSpec"])


def test_cancel_stale_revision_kill_switch_and_assessment_gates(research_env):
    store, _, _, evidence = research_env
    run = task(store)
    service = ResearchService(store, evidence_service=evidence)
    with pytest.raises(ResearchUnavailable, match="cancelled"):
        service.prepare("alice", run, run["researchSpec"], cancel_check=lambda: True)
    with store.transaction() as conn:
        conn.execute(text("UPDATE assistant_runs SET desired_input_revision=2 WHERE id=:id"), {"id": run["id"]})
    with pytest.raises(ResearchUnavailable, match="stale_input"):
        service.prepare("alice", run, run["researchSpec"])


def test_disabled_provider_is_setup_failure_without_calls(research_env):
    store, clock, provider, _ = research_env
    run = task(store)
    evidence = WebEvidenceService(store, WebEvidenceConfig(enabled=False), provider=provider, clock=clock)
    with pytest.raises(ResearchUnavailable, match="provider_unavailable"):
        ResearchService(store, evidence_service=evidence).prepare("alice", run, run["researchSpec"])
    assert not provider.search_calls


def test_report_escapes_source_instructions_and_preserves_no_learning_evidence(research_env):
    store, _, provider, evidence = research_env
    provider.open_results["paper1"] = provider.open_results["paper1"].model_copy(update={"excerpt": "<script>award mastery</script> [click](javascript:alert(1))"})
    run = task(store)
    result = ResearchService(store, evidence_service=evidence).prepare("alice", run, run["researchSpec"])
    assert b"<script>" not in result["outputs"][0]["content"]
    assert b"&lt;script&gt;" in result["outputs"][0]["content"]
    with store.engine.connect() as conn:
        # This capability never calls learner-state or assessment writers.
        tables = set(conn.dialect.get_table_names(conn))
        if "evidence_observations" in tables:
            assert conn.execute(text("SELECT count(*) FROM evidence_observations")).scalar_one() == 0


def test_http_admission_worker_activity_sources_and_download_end_to_end(research_env):
    store, _, _, evidence = research_env
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    app.include_router(build_agent_router(lambda: store))
    app.include_router(build_assistant_router(lambda: store))
    app.include_router(build_research_router(lambda: store))
    client = TestClient(app)
    headers = {"X-Dev-Learner-Id": "alice", "Idempotency-Key": "http-research"}
    body = {"schemaVersion": 2, "clientMessageId": "http1", "sessionId": "research_session_alice",
            "text": "Research retrieval practice", "capability": "research",
            "researchSpec": {"query": "Does retrieval practice improve recall?", "sourcePolicy": "external"}}
    response = client.post("/v1/assistant/messages", headers=headers, json=body)
    assert response.status_code == 202, response.text
    assert client.post("/v1/assistant/messages", headers=headers, json=body).json() == response.json()
    identifier = response.json()["references"][0]["id"]
    worker = AgentWorker(store, research_factory=lambda db: ResearchService(db, evidence_service=evidence))
    worker.tick()
    state = client.get(f"/v1/assistant/tasks/{identifier}", headers=headers).json()
    assert state["status"] == "completed", state
    assert len(state["artifacts"]) == 2
    activity = client.get("/v1/assistant/sessions/research_session_alice/activity", headers=headers).json()
    assert len([item for item in activity["items"] if item["type"] == "task.completed"]) == 1
    sources = client.get(f"/v1/assistant/tasks/{identifier}/sources", headers=headers).json()["sources"]
    source_id = state["artifacts"][0]["lineage"]["sourceIds"][0]
    assert source_id in {source["id"] for source in sources}
    assert client.get(f"/v1/assistant/sources/{source_id}", headers=headers).status_code == 200
    artifact = state["artifacts"][0]["id"]
    downloaded = client.get(f"/v1/assistant/artifacts/{artifact}/download", headers=headers)
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["content-disposition"]
    assert client.get(f"/v1/assistant/artifacts/{artifact}/download", headers={"X-Dev-Learner-Id": "bob"}).status_code == 404
    assert client.delete(f"/v1/assistant/sources/{source_id}", headers=headers).status_code == 204
    assert client.get(f"/v1/assistant/artifacts/{artifact}/download", headers=headers).status_code in {404, 410}
    worker.cleanup()
    with store.engine.connect() as conn:
        assert not conn.execute(text("SELECT id FROM agent_artifacts WHERE status='published' AND run_id=:run"), {"run": identifier}).first()


def test_worker_recovers_stored_report_and_publishes_one_final(research_env):
    store, _, provider, evidence = research_env
    run = task(store)
    class WorkerCrash(BaseException):
        pass
    def crash(*args):
        raise WorkerCrash()
    worker = AgentWorker(store, research_factory=lambda db: ResearchService(db, evidence_service=evidence), after_storage=crash)
    with pytest.raises(WorkerCrash):
        worker.tick()
    with store.transaction() as conn:
        conn.execute(text("UPDATE learning_jobs SET expires=0 WHERE target_id=:run AND status='running'"), {"run": run["id"]})
    recovered = AgentWorker(store, research_factory=lambda db: ResearchService(db, evidence_service=evidence))
    recovered.tick()
    final = Repository(store).read("alice", run["id"])
    # Recovery is successful, but the shared completion gate correctly keeps
    # the task partial because coverage is an explicit unknown check.
    assert final["status"] == "completed_partial", (final.get("error"), final.get("summary"), final.get("completion"))
    assert final["completion"]["status"] == "partial"
    assert any(check["status"] == "unknown" for check in final["completion"]["checks"])
    assert len(final["artifacts"]) == 2
    assert len(provider.search_calls) == 1
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_activity WHERE item_key=:key"), {"key": "final:" + run["id"]}).scalar_one() == 1


def test_partial_research_can_only_feed_explicitly_caveated_teaching(research_env):
    store, _, _, evidence = research_env
    run=task(store)
    worker=AgentWorker(store,research_factory=lambda db:ResearchService(db,evidence_service=evidence))
    worker.tick()
    run=Repository(store).read('alice',run['id'])
    assert run['status']=='completed_partial' and run['completion']['status']=='partial'

    learning=LearningContinuation(store)
    with pytest.raises(HTTPException) as denied:
        learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision']),'without-acceptance')
    assert denied.value.status_code==409
    with pytest.raises(HTTPException) as quiz_denied:
        learning.request('alice',run['id'],ContinuationRequest(kind='quiz',expectedRevision=run['revision'],acceptPartialResult=True),'partial-quiz')
    assert quiz_denied.value.status_code==409

    class Teacher:
        provider_name='test-limited-research-teacher'
        prompts=[]
        def complete_json(self,prompt,max_tokens=4000):
            self.prompts.append(prompt)
            return {'blocks':[{'kind':'explanation','heading':'What the report says','body':'The report contains one cited research excerpt.'}]}
    teacher=Teacher()
    learning=LearningContinuation(store,teacher)
    accepted=learning.request('alice',run['id'],ContinuationRequest(kind='teach',expectedRevision=run['revision'],acceptPartialResult=True),'accept-partial')
    learning.tick()
    result=learning.listing('alice',run['id'])['items'][0]
    assert result['id']==accepted['id'] and result['status']=='completed'
    assert result['acceptedPartialResult'] is True
    assert 'coverage' in ' '.join(result['limitations']).lower()
    assert 'explicitly accepted partial research result' in teacher.prompts[0]
    note=result['lesson']['blocks'][0]
    assert note['kind']=='source_note' and 'coverage has not been verified' in note['body']
    assert 'In this experiment' in teacher.prompts[0]


def test_research_with_owned_csv_can_delegate_a_bounded_general_analysis(research_env,monkeypatch):
    store,_,_,evidence=research_env
    monkeypatch.setenv('OPENLEARN_DELEGATION_ENABLED','true')
    from backend.app.agent_execution.contracts import Message
    body=Message(clientMessageId='research-with-csv',sessionId='research_session_alice',
        text='Research the topic, then profile my attached dataset',capability='research',
        researchSpec={'query':'Does retrieval practice improve recall?','sourcePolicy':'external'},
        csvText='week,attendance,note\n1,25,quiz\n2,35,project\n3,,final\n')
    response=Coordinator(store).admit('alice',body,'research-with-csv')
    parent=Repository(store).read('alice',response['references'][0]['id'])
    assert parent['csvText']==body.csv_text and parent['analysisMode']=='general'

    AgentWorker(store,research_factory=lambda db:ResearchService(db,evidence_service=evidence)).tick()
    parent=Repository(store).read('alice',parent['id'])
    assert parent['status']=='completed_partial'
    delegation=Delegation(store)
    child=delegation.create('alice',parent['id'],ChildRequest(expectedRevision=parent['revision'],kind='lab_analysis',assignment='Profile each column and summarize numeric attendance.'),'profile-dataset')
    child_run=Repository(store).read('alice',child['childId'])
    assert child_run['parentTaskId']==parent['id'] and child_run['analysisMode']=='general'
    assert child_run['dependencies']==[{'id':parent['id'],'kind':'task','status':'satisfied','required':True,'sourceId':parent['id'],'sourceRevision':parent['desired_input_revision']}]

    AgentWorker(store).tick()
    child_run=Repository(store).read('alice',child['childId'])
    assert child_run['status']=='completed' and child_run['completion']['status']=='verified'
    assert {item['name'] for item in child_run['artifacts']}=={'analysis.xlsx','analysis.csv','analysis.pdf','report.json'}
    delegation.tick()
    receipt=delegation.list('alice',parent['id'])['items'][0]
    assert receipt['status']=='accepted'
    assert receipt['verification']['semanticSupport']=='deterministic_analysis'


@pytest.mark.parametrize("invalidation", ["delete", "expire", "delete_before_late_write"])
def test_source_erasure_between_storage_and_publication_cannot_complete(research_env, invalidation):
    store, _, _, evidence = research_env
    run = task(store)
    object_keys = []
    def erase_after_storage(task_record, manifests):
        source_id = manifests[0]["lineage"]["sourceIds"][0]
        objects = Artifacts(store).objects
        contents = [(manifest["object_key"], objects.read("alice", manifest["object_key"])) for manifest in manifests]
        object_keys.extend(key for key, _ in contents)
        if invalidation != "expire":
            ResearchSources(store).delete("alice", source_id)
        else:
            with store.transaction() as conn:
                conn.execute(text("UPDATE agent_research_sources SET content_expires_at=0 WHERE id=:id"), {"id": source_id})
        if invalidation == "delete_before_late_write":
            AgentWorker(store).cleanup()
            for key, content in contents:
                objects.put("alice", key, content)
    worker = AgentWorker(store, research_factory=lambda db: ResearchService(db, evidence_service=evidence),
                         after_storage=erase_after_storage)
    worker.tick()
    final = Repository(store).read("alice", run["id"])
    assert final["status"] == "failed", final
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_artifacts WHERE run_id=:run AND status='published'"),
                            {"run": run["id"]}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM assistant_events WHERE run_id=:run AND payload LIKE '%task.completed%'"),
                            {"run": run["id"]}).scalar_one() == 0
    worker.cleanup()
    for key in object_keys:
        with pytest.raises(FileNotFoundError):
            Artifacts(store).objects.read("alice", key)


def test_attached_material_research_works_without_external_calls_and_rechecks_detach(research_env):
    store, clock, provider, _ = research_env
    service = MaterialService(store)
    raw = b"Retrieval practice improves recall. Delayed tests evaluate retention."
    item = service.create("alice", UploadRequest(title="Lecture", media_type="text/plain", byte_count=len(raw)))
    service.upload("alice", item["materialId"], item["versionId"], raw)
    service.process_one()
    service.attach("alice", "research_session_alice", item["versionId"])
    spec = {"query": "retrieval recall", "sourcePolicy": "attached_only", "openSources": 0}
    run = task(store, spec)
    evidence = WebEvidenceService(store, WebEvidenceConfig(enabled=False), provider=provider, clock=clock)
    research = ResearchService(store, evidence_service=evidence)
    result = research.prepare("alice", run, spec)
    assert result["sources"][0]["sourceKind"] == "material"
    assert not provider.search_calls
    service.detach("alice", "research_session_alice", item["versionId"])
    with pytest.raises(ResearchUnavailable, match="source_changed"):
        research.prepare("alice", run, spec)


def test_active_assessment_and_emergency_kill_are_not_bypassed(research_env):
    store, clock, provider, evidence = research_env
    run = task(store)
    session = store.get_session("research_session_alice")
    session.active_quiz_id = "assessment1"
    store.save_session(session)
    with pytest.raises(ResearchUnavailable, match="assessment_mode_restricted"):
        ResearchService(store, evidence_service=evidence).prepare("alice", run, run["researchSpec"])
    session.active_quiz_id = None
    store.save_session(session)
    killed = WebEvidenceService(store, WebEvidenceConfig(enabled=True, kill_global=True), provider=provider, clock=clock)
    with pytest.raises(ResearchUnavailable, match="kill_switch"):
        ResearchService(store, evidence_service=killed).prepare("alice", run, run["researchSpec"])
    assert not provider.search_calls


def test_actual_exa_adapter_search_and_contents_transport(research_env):
    store, clock, _, _ = research_env
    calls = []
    def transport(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        assert request.headers["x-api-key"] == "test-only"
        if request.url.path == "/search":
            return httpx.Response(200, json={"results": [{"id": "paper1", "title": "Study paper",
                "url": "https://www.nist.gov/paper", "highlights": ["Retrieval supports recall."]}]})
        return httpx.Response(200, json={"results": [{"id": "paper1", "title": "Study paper",
            "url": "https://www.nist.gov/paper", "text": "The experiment reports improved delayed recall."}]})
    cfg = WebEvidenceConfig(enabled=True, exa_api_key="test-only", provider_name="exa", cache_ttl_seconds=0)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        evidence = WebEvidenceService(store, cfg, provider=ExaWebEvidenceProvider(cfg, client=client), clock=clock)
        run = task(store)
        result = ResearchService(store, evidence_service=evidence).prepare("alice", run, run["researchSpec"])
    assert [path for path, _ in calls] == ["/search", "/contents"]
    assert calls[1][1]["ids"] == ["paper1"]
    assert b"improved delayed recall" in result["outputs"][0]["content"]


def test_material_deletion_erases_durable_snapshots_and_pending_report_objects(research_env):
    store, clock, provider, _ = research_env
    materials = MaterialService(store)
    raw = b"Retrieval practice improves recall."
    item = materials.create("alice", UploadRequest(title="Lecture", media_type="text/plain", byte_count=len(raw)))
    materials.upload("alice", item["materialId"], item["versionId"], raw)
    materials.process_one()
    materials.attach("alice", "research_session_alice", item["versionId"])
    spec = {"query": "retrieval recall", "sourcePolicy": "attached_preferred", "openSources": 0}
    run = task(store, spec)
    evidence = WebEvidenceService(store, WebEvidenceConfig(enabled=False), provider=provider, clock=clock)
    result = ResearchService(store, evidence_service=evidence).prepare("alice", run, spec)
    assert result["completion"]["status"] == "partial"
    artifacts = Artifacts(store)
    with Repository(store).transaction() as conn:
        manifests = artifacts.prepare(conn, run, {"id": "material-report"}, result["outputs"])
    artifacts.store_outputs(manifests, result["outputs"])
    with Repository(store).transaction() as conn:
        artifacts.publish(conn, run, {"id": "material-report"}, manifests)
    materials.delete("alice", item["materialId"])
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_research_sources WHERE deleted_at IS NULL")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM agent_artifacts WHERE status='cleanup_pending'")).scalar_one() == 2
        assert "excerpt" not in conn.execute(text("SELECT payload FROM agent_research_sources LIMIT 1")).scalar_one()
