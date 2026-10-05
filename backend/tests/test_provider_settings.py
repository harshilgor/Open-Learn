"""Server-side provider key management for browser clients."""

from fastapi.testclient import TestClient

try:
    import backend.app.provider_key_routes as provider_keys
    from backend.app.main import app
except ModuleNotFoundError:
    import app.provider_key_routes as provider_keys
    from app.main import app


client = TestClient(app)


def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS", "true")
    target = tmp_path / ".env"
    monkeypatch.setattr(provider_keys, "env_path", lambda: target)
    for var in ("AI_TUTOR_PROVIDER", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return target


def test_status_reports_shape_without_values(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    payload = client.get("/v1/provider-settings").json()
    assert payload == {
        "provider": "deterministic_baseline",
        "openRouterConfigured": False,
        "openAiConfigured": False,
        "restartRequired": False,
    }


def test_save_key_writes_env_and_never_returns_value(monkeypatch, tmp_path):
    target = _isolated_env(monkeypatch, tmp_path)
    target.write_text("# comment\nAI_TUTOR_ENV=development\n", encoding="utf-8")
    response = client.put("/v1/provider-settings", json={"provider": "openrouter", "apiKey": "sk-or-v1-testkey123"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "openrouter"
    assert payload["openRouterConfigured"] is True
    assert payload["openAiConfigured"] is False
    assert payload["restartRequired"] is False
    assert "sk-or-v1-testkey123" not in response.text
    content = target.read_text(encoding="utf-8")
    assert "# comment" in content
    assert "AI_TUTOR_ENV=development" in content
    assert "OPENROUTER_API_KEY=sk-or-v1-testkey123" in content
    assert "AI_TUTOR_PROVIDER=openrouter" in content


def test_save_key_rejects_invalid_input(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path)
    assert client.put("/v1/provider-settings", json={"provider": "openrouter", "apiKey": "short"}).status_code == 422
    assert client.put("/v1/provider-settings", json={"provider": "anthropic", "apiKey": "sk-ant-valid-key-123"}).status_code == 422
    assert client.put("/v1/provider-settings", json={"provider": "openai", "apiKey": "has spaces in it here"}).status_code == 422


def test_delete_key_falls_back_to_baseline(monkeypatch, tmp_path):
    target = _isolated_env(monkeypatch, tmp_path)
    client.put("/v1/provider-settings", json={"provider": "openai", "apiKey": "sk-test-openai-key-123"})
    response = client.delete("/v1/provider-settings/openai")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["openAiConfigured"] is False
    assert payload["provider"] == "deterministic_baseline"
    content = target.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in content


def test_managed_service_hides_keys_and_blocks_customer_mutations(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.delenv('OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS',raising=False)
    fake=type('Provider',(),{'api_key':'private-test-key','provider_name':'openrouter/test'})()
    app=FastAPI();app.include_router(provider_keys.build_provider_key_router(provider_getter=lambda:fake))
    app.dependency_overrides[provider_keys.material_owner]=lambda:'alice'
    managed=TestClient(app)
    response=managed.get('/v1/provider-settings')
    assert response.json()['managed'] and response.json()['available']
    assert 'private-test-key' not in response.text
    assert managed.put('/v1/provider-settings',json={'provider':'openrouter','apiKey':'sk-or-v1-customer'}).status_code==403
    assert managed.delete('/v1/provider-settings/openrouter').status_code==403
    assert managed.post('/v1/provider-settings/test').status_code==403


def test_production_never_allows_local_key_management(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.setenv('AI_TUTOR_ENV','production');monkeypatch.setenv('OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS','true')
    app=FastAPI();app.include_router(provider_keys.build_provider_key_router());app.dependency_overrides[provider_keys.material_owner]=lambda:'alice'
    assert TestClient(app).put('/v1/provider-settings',json={'provider':'openrouter','apiKey':'sk-or-v1-customer'}).status_code==403
