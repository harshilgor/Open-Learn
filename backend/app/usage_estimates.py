"""Read-only task usage estimates with short-lived, owner-scoped references.

These estimates apply the current internal reference-credit schedule to
caller-supplied quantity bounds. They neither predict provider invoices nor
reserve allowance or guarantee that a later operation will be admitted.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from .material_routes import material_owner

ESTIMATE_REFERENCE_TTL_SECONDS = 600
ESTIMATE_FIELDS = ("inputTokens", "cachedTokens", "outputTokens", "milliseconds", "characters", "requests")
PRICED_COMPONENTS = {"model", "stt", "tts", "voice", "browser"}
SUPPORTED_COMPONENT_FIELDS = {
    "model": {"inputTokens", "cachedTokens", "outputTokens"},
    "stt": {"milliseconds"},
    "tts": {"characters"},
    "voice": {"milliseconds"},
    "browser": {"milliseconds"},
}


class EstimateQuantities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputTokens: int = Field(default=0, ge=0, le=48_000)
    cachedTokens: int = Field(default=0, ge=0, le=48_000)
    outputTokens: int = Field(default=0, ge=0, le=2_000)
    milliseconds: int = Field(default=0, ge=0, le=1_800_000)
    characters: int = Field(default=0, ge=0, le=2_400)
    requests: int = Field(default=0, ge=0, le=20)


class EstimateOperationBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: Literal[
        "model", "stt", "tts", "voice", "browser", "search", "sandbox",
        "tool", "proxy", "embeddings", "classification",
    ]
    minimum: EstimateQuantities
    maximum: EstimateQuantities

    @model_validator(mode="after")
    def validate_bounds(self):
        for label, quantities in (("minimum", self.minimum), ("maximum", self.maximum)):
            values = quantities.model_dump()
            allowed_fields = SUPPORTED_COMPONENT_FIELDS.get(self.component, {"requests"})
            if any(values[field] for field in ESTIMATE_FIELDS if field not in allowed_fields):
                raise ValueError(f"{label} quantities do not match component {self.component}.")
            if quantities.cachedTokens > quantities.inputTokens:
                raise ValueError("Cached model tokens cannot exceed input tokens.")
        if any(getattr(self.minimum, name) > getattr(self.maximum, name) for name in ESTIMATE_FIELDS):
            raise ValueError("Every minimum quantity must be less than or equal to its maximum.")
        if not any(getattr(self.maximum, name) for name in ESTIMATE_FIELDS):
            raise ValueError("At least one maximum quantity must be positive.")
        if self.component in PRICED_COMPONENTS:
            from .usage.pricing import price

            if price(self.component, _credit_quantities(self.minimum)) > price(self.component, _credit_quantities(self.maximum)):
                raise ValueError("The minimum reference-credit estimate cannot exceed the maximum.")
        return self


class TaskEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskType: Literal["text", "voice", "browser", "research", "mixed"]
    operations: list[EstimateOperationBounds] = Field(min_length=1, max_length=20)


def _credit_quantities(value: EstimateQuantities) -> dict[str, int]:
    return {
        "input_tokens": value.inputTokens,
        "cached_tokens": value.cachedTokens,
        "output_tokens": value.outputTokens,
        "milliseconds": value.milliseconds,
        "characters": value.characters,
    }


def _percentage(microcredits: int, grant: int) -> float:
    return round(microcredits * 100 / grant, 1) if grant else 0.0


def _cap_options(minimum: int, maximum: int, grant: int) -> list[dict]:
    candidates = [
        ("estimate_low", max(1, min(minimum, grant)), "A lower cap may stop the task before its estimated upper bound."),
        ("estimate_high", max(1, min(maximum, grant)), "The estimated upper bound, limited to one full allowance."),
        ("full_allowance", grant, "One full allowance; task work still stops at this exact maximum."),
    ]
    seen: set[int] = set()
    options = []
    for identifier, amount, description in candidates:
        if amount in seen:
            continue
        seen.add(amount)
        options.append({
            "id": identifier,
            "maximumMicrocredits": amount,
            "maximumPercentOfAllowance": _percentage(amount, grant),
            "description": description,
        })
    return options


def _estimate_payload(body: TaskEstimateRequest, allowance: dict, now: float) -> dict:
    unsupported = sorted({item.component for item in body.operations if item.component not in PRICED_COMPONENTS})
    if unsupported:
        return {
            "supported": False,
            "reasonCode": "component_rate_unavailable",
            "unsupportedComponents": unsupported,
            "rateVersion": allowance["rateVersion"],
            "policyVersion": allowance["policyVersion"],
            "providerRateStatus": "uncertain",
            "admissionPerformed": False,
        }

    from .usage.pricing import price

    minimum = 0
    maximum = 0
    for operation in body.operations:
        minimum += price(operation.component, _credit_quantities(operation.minimum))
        maximum += price(operation.component, _credit_quantities(operation.maximum))
    grant = allowance["grantedMicrocredits"]
    return {
        "supported": True,
        "taskType": body.taskType,
        "estimateBasis": "caller_supplied_quantity_bounds_and_internal_reference_credit_rates",
        "range": {
            "minimumMicrocredits": minimum,
            "maximumMicrocredits": maximum,
            "minimumPercentOfAllowance": _percentage(minimum, grant),
            "maximumPercentOfAllowance": _percentage(maximum, grant),
            "denominator": "full_window_allowance",
        },
        "capOptions": _cap_options(minimum, maximum, grant),
        "allowance": {
            "grantedMicrocredits": grant,
            "policyVersion": allowance["policyVersion"],
            "rateVersion": allowance["rateVersion"],
        },
        "providerCost": {
            "status": "uncertain",
            "estimatedUsdRange": None,
            "reason": "No pinned provider tariff and provider receipt are available for this estimate.",
        },
        "admissionPerformed": False,
        "spendGuaranteed": False,
        "notices": [
            "The range applies the internal reference-credit schedule to the supplied quantity bounds.",
            "Only declared operation components are included; omitted work is outside this estimate.",
            "Provider billing, routing, hidden reasoning, retries, and actual usage may differ.",
            "An estimate reference is not a reservation or admission decision; admission is checked when work starts.",
        ],
        "createdAt": now,
        "expiresAt": now + ESTIMATE_REFERENCE_TTL_SECONDS,
    }


def build_usage_estimate_router(store_provider) -> APIRouter:
    router = APIRouter(prefix="/usage/estimate/task")

    @router.post("")
    def create_task_estimate(body: TaskEstimateRequest, response: Response, owner: str = Depends(material_owner)):
        from .usage.ledger import Ledger

        response.headers["Cache-Control"] = "private, no-store"
        store = store_provider()
        ledger = Ledger(store)
        allowance = ledger.allowance(owner)
        with store.engine.begin() as conn:
            now = ledger.now(conn)
            payload = _estimate_payload(body, allowance, now)
            if not payload["supported"]:
                return payload

            reference = secrets.token_urlsafe(32)
            reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
            payload["createdAt"] = now
            payload["expiresAt"] = now + ESTIMATE_REFERENCE_TTL_SECONDS
            encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            # Remove expired records for this owner during issuance. This keeps
            # the reference table bounded for active users without a global
            # cleanup job or cross-account write on the estimate path.
            conn.execute(
            text("DELETE FROM usage_estimate_refs WHERE owner_id=:owner AND expires_at<=:now"),
                {"owner": owner, "now": now},
            )
            conn.execute(
                text("INSERT INTO usage_estimate_refs(reference_hash,owner_id,payload,created_at,expires_at) "
                     "VALUES(:hash,:owner,:payload,:created,:expires)"),
                {"hash": reference_hash, "owner": owner, "payload": encoded,
                 "created": now, "expires": payload["expiresAt"]},
            )
        return {**payload, "estimateReference": reference}

    @router.get("/{estimate_reference}")
    def read_task_estimate(estimate_reference: str, response: Response, owner: str = Depends(material_owner)):
        from .usage.ledger import Ledger

        response.headers["Cache-Control"] = "private, no-store"
        if len(estimate_reference) > 128:
            raise HTTPException(status_code=404, detail={"code": "usage_estimate_not_found"})
        reference_hash = hashlib.sha256(estimate_reference.encode("utf-8")).hexdigest()
        store = store_provider()
        ledger = Ledger(store)
        with store.engine.begin() as conn:
            now = ledger.now(conn)
            row = conn.execute(
                text("SELECT payload,expires_at FROM usage_estimate_refs "
                     "WHERE reference_hash=:hash AND owner_id=:owner"),
                {"hash": reference_hash, "owner": owner},
            ).mappings().first()
            if not row:
                raise HTTPException(status_code=404, detail={"code": "usage_estimate_not_found"})
            if row["expires_at"] <= now:
                conn.execute(
                    text("DELETE FROM usage_estimate_refs WHERE reference_hash=:hash AND owner_id=:owner"),
                    {"hash": reference_hash, "owner": owner},
                )
                payload = None
            else:
                payload = json.loads(row["payload"])
        if payload is None:
            raise HTTPException(status_code=404, detail={"code": "usage_estimate_not_found"})
        return {**payload, "estimateReference": estimate_reference}

    return router
