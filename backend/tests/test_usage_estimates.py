from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.material_routes import material_owner
from backend.app.storage import Store
from backend.app.usage_routes import build_usage_router


def _client(store, owner="alice"):
    app = FastAPI()
    app.include_router(build_usage_router(lambda: store))
    app.dependency_overrides[material_owner] = lambda: owner
    return TestClient(app)


def _model_estimate():
    return {
        "taskType": "text",
        "operations": [{
            "component": "model",
            "minimum": {"inputTokens": 1000, "outputTokens": 0},
            "maximum": {"inputTokens": 1000, "outputTokens": 100},
        }],
    }


def test_task_estimate_returns_bounded_range_and_non_admission_options(tmp_path):
    store = Store(tmp_path / "usage-estimate.db")
    try:
        client = _client(store)
        response = client.post("/v1/usage/estimate/task", json=_model_estimate())
        assert response.status_code == 200, response.text
        body = response.json()
        assert response.headers["cache-control"] == "private, no-store"
        assert body["supported"] is True
        assert body["estimateBasis"] == "caller_supplied_quantity_bounds_and_internal_reference_credit_rates"
        assert body["range"] == {
            "minimumMicrocredits": 500_000,
            "maximumMicrocredits": 700_000,
            "minimumPercentOfAllowance": 0.5,
            "maximumPercentOfAllowance": 0.7,
            "denominator": "full_window_allowance",
        }
        assert [option["id"] for option in body["capOptions"]] == [
            "estimate_low", "estimate_high", "full_allowance",
        ]
        assert body["providerCost"] == {
            "status": "uncertain",
            "estimatedUsdRange": None,
            "reason": "No pinned provider tariff and provider receipt are available for this estimate.",
        }
        assert body["admissionPerformed"] is False
        assert body["spendGuaranteed"] is False
        assert body["expiresAt"] - body["createdAt"] == 600
        # Estimate calculation must not start a usage period/account or hold.
        with store.engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM usage_accounts")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM usage_reservations")).scalar_one() == 0
    finally:
        store.close()


def test_task_estimate_reference_is_owner_scoped_and_retrievable_until_expiry(tmp_path):
    store = Store(tmp_path / "usage-estimate-owner.db")
    try:
        alice = _client(store)
        created = alice.post("/v1/usage/estimate/task", json=_model_estimate()).json()
        reference = created["estimateReference"]
        assert len(reference) > 32
        assert alice.get(f"/v1/usage/estimate/task/{reference}").json() == created
        assert _client(store, "bob").get(f"/v1/usage/estimate/task/{reference}").status_code == 404

        # Only the hash is persisted; the bearer-like opaque reference is not.
        with store.engine.connect() as conn:
            stored_hash, stored_payload = conn.execute(
                text("SELECT reference_hash,payload FROM usage_estimate_refs")
            ).one()
        assert reference not in stored_hash
        assert reference not in stored_payload
    finally:
        store.close()


def test_expired_task_estimate_reference_is_deleted_and_not_retrievable(tmp_path):
    store = Store(tmp_path / "usage-estimate-expiry.db")
    try:
        client = _client(store)
        created = client.post("/v1/usage/estimate/task", json=_model_estimate()).json()
        reference = created["estimateReference"]
        with store.engine.begin() as conn:
            conn.execute(text("UPDATE usage_estimate_refs SET created_at=0,expires_at=0.5"))
        response = client.get(f"/v1/usage/estimate/task/{reference}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "usage_estimate_not_found"
        with store.engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM usage_estimate_refs")).scalar_one() == 0
    finally:
        store.close()


def test_task_estimate_fails_closed_for_unpriced_components_and_preserves_legacy_endpoint(tmp_path):
    store = Store(tmp_path / "usage-estimate-compat.db")
    try:
        client = _client(store)
        unsupported = client.post("/v1/usage/estimate/task", json={
            "taskType": "research",
            "operations": [{
                "component": "search",
                "minimum": {"requests": 1},
                "maximum": {"requests": 3},
            }],
        })
        assert unsupported.status_code == 200
        assert unsupported.json()["supported"] is False
        assert unsupported.json()["reasonCode"] == "component_rate_unavailable"
        assert unsupported.json()["unsupportedComponents"] == ["search"]
        assert "estimateReference" not in unsupported.json()

        legacy = client.post("/v1/usage/estimate", json={
            "component": "model", "inputTokens": 1000, "outputTokens": 100,
        })
        assert legacy.status_code == 200, legacy.text
        assert set(legacy.json()) == {
            "maximumCreditsMicro", "percentage", "rateVersion", "expiresAt", "supported", "availability",
        }
    finally:
        store.close()


def test_task_estimate_rejects_inverted_credit_range_and_extra_fields(tmp_path):
    store = Store(tmp_path / "usage-estimate-validation.db")
    try:
        client = _client(store)
        inverted = client.post("/v1/usage/estimate/task", json={
            "taskType": "text",
            "operations": [{
                "component": "model",
                "minimum": {"inputTokens": 100, "cachedTokens": 0},
                "maximum": {"inputTokens": 100, "cachedTokens": 100},
            }],
        })
        assert inverted.status_code == 422
        extra = _model_estimate()
        extra["prompt"] = "not persisted"
        assert client.post("/v1/usage/estimate/task", json=extra).status_code == 422
    finally:
        store.close()
