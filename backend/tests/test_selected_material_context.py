"""No tmp_path fixture: Windows inherited Temp ACLs can block the wider suite."""
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.identity_middleware import IdentityMiddleware
from backend.app.graph_generator import GraphGenerator
from backend.app.material_routes import build_material_router
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.storage import Store


def test_selected_owned_passage_is_the_entire_manifest(monkeypatch):
    root = Path.cwd() / "backend" / "data" / f"selected-context-{uuid4().hex}"
    root.mkdir(parents=True)
    monkeypatch.setenv("AI_TUTOR_MATERIAL_DIR", str(root / "objects"))
    monkeypatch.setenv("AI_TUTOR_ENV", "development")
    monkeypatch.setenv("AI_TUTOR_DEV_IDENTITY", "true")
    store = Store(root / "test.db")
    try:
        scope = TopicScope(id="scope-selected", topic="Calculus", resolved_meaning="Calculus", objective="Learn", depth="introductory", created_at=utc_now())
        graph = GraphGenerator().generate(scope); store.save_scope(scope); store.save_graph(graph)
        store.save_session(LearningSession(id="session-selected", graph_id=graph.id, created_at=utc_now(), updated_at=utc_now()))
        app = FastAPI(); app.add_middleware(IdentityMiddleware, store_provider=lambda: store); app.include_router(build_material_router(lambda: store))
        with TestClient(app) as client:
            chosen = client.post("/v1/materials/text", json={"title": "Chosen", "text": "A derivative measures a local rate of change."}).json()
            other = client.post("/v1/materials/text", json={"title": "Other", "text": "An integral accumulates quantities."}).json()
            for item in (chosen, other):
                assert client.post("/v1/sessions/session-selected/materials", json={"materialVersionId": item["versionId"]}).status_code == 200
            chosen_span = client.get(f"/v1/material-versions/{chosen['versionId']}/blocks").json()["blocks"][0]["id"]
            result = client.post("/v1/sessions/session-selected/material-answer", json={"message": "rates", "selectedSpanIds": [chosen_span]}).json()
            manifest = client.get(f"/v1/context-manifests/{result['contextId']}").json()
            assert manifest["retrievalMode"] == "explicit_selection"
            assert manifest["selectedSpanIds"] == [chosen_span]
            assert [source["spanId"] for source in manifest["sources"]] == [chosen_span]
            assert "text" not in manifest["sources"][0]
            assert client.post("/v1/sessions/session-selected/material-answer", headers={"X-Dev-Learner-Id": "other"}, json={"message": "rates", "selectedSpanIds": [chosen_span]}).status_code == 404
    finally:
        store.close()
        for item in sorted(root.rglob("*"), reverse=True):
            if item.is_file(): item.unlink()
            elif item.is_dir(): item.rmdir()
        root.rmdir()
