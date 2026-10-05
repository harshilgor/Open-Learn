import io
import pytest
from backend.app.identity_middleware import IdentityMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.storage import Store
from backend.app.material_routes import build_material_router
from backend.app.material_service import MaterialService


@pytest.fixture
def material_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    store = Store(tmp_path / "test.db")
    app = FastAPI()
    app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    app.include_router(build_material_router(lambda: store))
    with TestClient(app) as client:
        yield client, store
    store.close()


def test_text_upload_extraction_owner_isolation_and_delete(material_api):
    client, store = material_api
    result = client.post("/v1/materials/text", json={"title": "Algebra", "text": "Linear equations use equality.\n\nA variable represents an unknown quantity."})
    assert result.status_code == 201
    item = result.json()
    detail = client.get(f"/v1/materials/{item['id']}").json()
    assert detail["status"] == "ready"
    blocks = client.get(f"/v1/material-versions/{item['versionId']}/blocks").json()["blocks"]
    assert len(blocks) == 2
    assert blocks[0]["pageIndex"] == 0
    span = blocks[0]["id"]
    assert client.get(f"/v1/source-spans/{span}", headers={"X-Dev-Learner-Id": "other"}).status_code == 404
    assert client.get("/v1/materials", headers={"X-Dev-Learner-Id": "other"}).json() == {"materials": []}
    assert client.delete(f"/v1/materials/{item['id']}").status_code == 200
    assert client.get(f"/v1/source-spans/{span}").status_code == 404
    assert not list(MaterialService(store).root.iterdir())


def test_pdf_without_text_requires_attention(material_api):
    PdfWriter = pytest.importorskip("pypdf").PdfWriter
    client, _ = material_api
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    raw = output.getvalue()
    item = client.post("/v1/materials", json={"title": "Scanned", "mediaType": "application/pdf", "byteCount": len(raw)}).json()
    assert client.put(item["uploadPath"], content=raw).status_code == 200
    detail = client.get(f"/v1/materials/{item['materialId']}").json()
    assert detail["status"] == "needs_attention"
    assert detail["issues"][0]["pageIndex"] == 0


def test_immutable_upload_and_durable_recovery(material_api):
    client, store = material_api
    raw = b"An immutable passage."
    item = client.post("/v1/materials", json={"title": "Reference", "mediaType": "text/plain", "byteCount": len(raw)}).json()
    client.put(item["uploadPath"], content=raw)
    assert client.put(item["uploadPath"], content=b"X" * len(raw)).status_code == 409
    with store.transaction() as c:
        c.execute(text("UPDATE material_jobs SET status='running',expires=0,attempt=1"))
    assert MaterialService(store).process_one()
    assert client.get(f"/v1/materials/{item['materialId']}").json()["status"] == "ready"


def test_hosted_dev_identity_is_rejected(material_api, monkeypatch):
    client, _ = material_api
    monkeypatch.setenv("AI_TUTOR_ENV", "production")
    assert client.get("/v1/materials").status_code == 503


def test_invalid_upload_never_enters_processing(material_api):
    client, _ = material_api
    item = client.post("/v1/materials", json={"title": "Fake PDF", "mediaType": "application/pdf", "byteCount": 4}).json()
    assert client.put(item["uploadPath"], content=b"fake").status_code == 422
    assert client.put(item["uploadPath"], content=b"too long").status_code == 413


@pytest.mark.parametrize("media_type, filename, raw", [
    ("image/png", "diagram.png", b"\x89PNG\r\n\x1a\n" + b"image-bytes"),
    ("image/jpeg", "photo.jpg", b"\xff\xd8\xff" + b"image-bytes"),
])
def test_image_upload_is_ready_for_visual_context(material_api, media_type, filename, raw):
    client, store = material_api
    item = client.post("/v1/materials", json={"title": filename, "mediaType": media_type, "byteCount": len(raw)}).json()
    assert client.put(item["uploadPath"], content=raw).status_code == 200
    detail = client.get(f"/v1/materials/{item['materialId']}").json()
    assert detail["status"] == "ready"
    assert detail["issues"][0]["pageIndex"] == 0
    assert "visual analysis" in detail["issues"][0]["message"]
    assert detail["parser"] == "vision-context-v1"


def test_image_upload_rejects_mismatched_signature(material_api):
    client, _ = material_api
    raw = b"not-a-png"
    item = client.post("/v1/materials", json={"title": "bad.png", "mediaType": "image/png", "byteCount": len(raw)}).json()
    response = client.put(item["uploadPath"], content=raw)
    assert response.status_code == 422
    body = response.json()
    error = body.get("error") or body.get("detail")
    assert error["code"] == "invalid_image"


def test_attached_image_becomes_bounded_provider_context(material_api):
    from backend.app.models import utc_now, TopicScope
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    client, store = material_api
    scope = TopicScope(id="scope_vision", topic="Diagrams", resolved_meaning="Diagrams", objective="Learn", depth="introductory", created_at=utc_now())
    store.save_scope(scope); graph = GraphGenerator().generate(scope); store.save_graph(graph)
    store.save_session(LearningSession(id="session_vision", graph_id=graph.id, created_at=utc_now(), updated_at=utc_now()))
    raw = b"\x89PNG\r\n\x1a\n" + b"diagram-bytes"
    item = client.post("/v1/materials", json={"title": "diagram.png", "mediaType": "image/png", "byteCount": len(raw)}).json()
    assert client.put(item["uploadPath"], content=raw).status_code == 200
    assert client.post("/v1/sessions/session_vision/materials", json={"materialVersionId": item["versionId"]}).status_code == 200
    images = MaterialService(store).image_context("local", "session_vision")
    assert len(images) == 1
    assert images[0].media_type == "image/png" and images[0].data == raw and images[0].title == "diagram.png"


def test_retrieval_excludes_answer_keys_and_respects_attachment_and_budget(material_api):
    from backend.app.models import utc_now, TopicScope
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    from backend.app.context_service import retrieve
    client, store = material_api
    scope = TopicScope(id="scope_material", topic="Algebra", resolved_meaning="Algebra", objective="Learn", depth="introductory", created_at=utc_now())
    store.save_scope(scope)
    graph = GraphGenerator().generate(scope)
    store.save_graph(graph)
    from backend.app.identity import grant_resource
    with store.transaction() as connection:
        grant_resource(connection, "topic_scopes", scope.id, "local")
        grant_resource(connection, "graph_versions", graph.id, "local")
    store.save_session(LearningSession(id="session_material", graph_id=graph.id, created_at=utc_now(), updated_at=utc_now()))
    items = []
    for role in ["reference", "answer_key", "sample_paper"]:
        item = client.post("/v1/materials/text", json={"title": role, "role": role, "text": f"Algebra linear equations {role}"}).json()
        items.append(item)
        assert client.post("/v1/sessions/session_material/materials", json={"materialVersionId": item["versionId"]}).status_code == 200
    sources = retrieve(store, "local", "session_material", "linear equations")
    assert len(sources) == 1 and sources[0]["title"] == "reference"
    assert retrieve(store, "local", "session_material", "linear", byte_budget=1) == []
    response = client.post("/v1/sessions/session_material/material-answer", json={"message": "linear equations"}).json()
    assert response["status"] == "source_excerpts_only"
    assert response["blocks"] == []
    manifest = client.get(f"/v1/context-manifests/{response['contextId']}").json()
    assert manifest["sources"][0]["spanId"] == sources[0]["spanId"]
    assert "text" not in manifest["sources"][0]
    assert client.get(f"/v1/context-manifests/{response['contextId']}", headers={"X-Dev-Learner-Id": "other"}).status_code == 404
    from backend.app.model_provider import GeneratedBlock
    class FakeProvider:
        def _complete(self, prompt, budget):
            assert "Algebra linear equations reference" in prompt
            assert "Algebra linear equations answer_key" not in prompt
            assert "learnerEvidence" in prompt
            return [GeneratedBlock("explanation", "Equality", "Both sides remain equal.")]
    provider_app = FastAPI()
    provider_app.add_middleware(IdentityMiddleware, store_provider=lambda: store)
    provider_app.include_router(build_material_router(lambda: store, lambda: FakeProvider()))
    with TestClient(provider_app) as provider_client:
        generated_response = provider_client.post("/v1/sessions/session_material/material-answer", json={"message": "linear equations"})
        assert generated_response.status_code == 200, generated_response.text
        generated = generated_response.json()
        assert generated["status"] == "source_informed_unverified"
        assert generated["blocks"][0]["heading"] == "Equality"
    assert client.post("/v1/sessions/session_material/material-answer", json={"message": "linear"}, headers={"X-Dev-Learner-Id": "other"}).status_code == 404
    client.delete(f"/v1/sessions/session_material/materials/{items[0]['versionId']}")
    assert retrieve(store, "local", "session_material", "linear") == []
    client.delete(f"/v1/materials/{items[0]['id']}")
    assert client.get(f"/v1/context-manifests/{response['contextId']}").status_code == 404


def test_explicit_passage_selection_is_attached_owner_scoped_and_manifest_bounded(material_api):
    from backend.app.models import utc_now, TopicScope
    from backend.app.graph_generator import GraphGenerator
    from backend.app.session_models import LearningSession
    client, store = material_api
    scope = TopicScope(id="scope_explicit", topic="Calculus", resolved_meaning="Calculus", objective="Learn", depth="introductory", created_at=utc_now())
    graph = GraphGenerator().generate(scope); store.save_scope(scope); store.save_graph(graph)
    store.save_session(LearningSession(id="session_explicit", graph_id=graph.id, created_at=utc_now(), updated_at=utc_now()))
    chosen = client.post("/v1/materials/text", json={"title": "Chosen", "text": "A derivative measures a local rate of change."}).json()
    other = client.post("/v1/materials/text", json={"title": "Other", "text": "An integral accumulates quantities."}).json()
    for item in (chosen, other):
        client.post("/v1/sessions/session_explicit/materials", json={"materialVersionId": item["versionId"]})
    chosen_span = client.get(f"/v1/material-versions/{chosen['versionId']}/blocks").json()["blocks"][0]["id"]
    other_span = client.get(f"/v1/material-versions/{other['versionId']}/blocks").json()["blocks"][0]["id"]
    result = client.post("/v1/sessions/session_explicit/material-answer", json={"message": "rates", "selectedSpanIds": [chosen_span]}).json()
    manifest = client.get(f"/v1/context-manifests/{result['contextId']}").json()
    assert manifest["retrievalMode"] == "explicit_selection"
    assert manifest["selectedSpanIds"] == [chosen_span]
    assert [source["spanId"] for source in manifest["sources"]] == [chosen_span]
    assert "text" not in manifest["sources"][0]
    denied = client.post("/v1/sessions/session_explicit/material-answer", headers={"X-Dev-Learner-Id": "other"}, json={"message": "rates", "selectedSpanIds": [other_span]})
    assert denied.status_code == 404
