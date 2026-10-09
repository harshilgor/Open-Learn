"""Shared, metered transport for OpenRouter's typed JEV Decisions API."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import time
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MAX_PAYLOAD_CHARS = 16_000


class JevClientError(RuntimeError):
    """A safe-to-log JEV error; never includes learner text or provider body."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class JevResult:
    answers: dict
    schema_version: str
    model: str
    request_id: str
    latency_ms: int
    attempts: int
    provider_cost_nano: int | None = None


class JevDecisionClient:
    """Calls JEV with bounded payloads and per-attempt conservative accounting."""

    def decide(self, contract: str, version: str, state: dict, questions: dict) -> JevResult:
        if os.getenv("OPENLEARN_CLASSIFICATION_PROVIDER", "jev").strip().lower() != "jev":
            raise JevClientError("classifier_provider_not_jev")
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise JevClientError("key_unavailable")

        model = (os.getenv("OPENLEARN_JEV_MODEL") or os.getenv("AI_TUTOR_JEV_MODEL") or "typesafe/jev-1.13").strip()
        request_id = uuid4().hex
        payload = {"model": model, "state": state, "questions": questions}
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise JevClientError("invalid_request") from None
        if len(encoded) > MAX_PAYLOAD_CHARS:
            raise JevClientError("payload_too_large")

        timeout_s = self._positive_float("OPENLEARN_JEV_TIMEOUT_SECONDS", "2.5", maximum=10.0)
        total_timeout_s = self._positive_float("OPENLEARN_JEV_TOTAL_TIMEOUT_SECONDS", "3.0", maximum=12.0)
        deadline = time.monotonic() + total_timeout_s
        started = time.monotonic()
        attempts = 0
        while attempts < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                raise JevClientError("deadline_exceeded")
            attempt_timeout = min(timeout_s, remaining)
            ticket = self._begin_usage(model)
            if ticket is False:
                raise JevClientError("usage_identity_unavailable")
            attempts += 1
            retry = False
            provider_cost_nano = None
            receipt_id = None
            try:
                response = httpx.post(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                             "X-OpenLearn-Request-Id": request_id},
                    json=payload,
                    timeout=httpx.Timeout(attempt_timeout, connect=min(1.0, attempt_timeout)),
                    follow_redirects=False,
                    trust_env=False,
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError:
                    retry = response.status_code >= 500
                    raise
                try:
                    body = response.json()
                except (ValueError, json.JSONDecodeError):
                    raise JevClientError("invalid_response") from None
                provider_cost_nano, receipt_id = self._usage_receipt(body)
                answers = body.get("answers") if isinstance(body, dict) else None
                if not isinstance(answers, dict):
                    raise JevClientError("invalid_response")
                result = JevResult(answers, version, model, request_id,
                                   round((time.monotonic() - started) * 1000), attempts,
                                   provider_cost_nano)
                logger.info("jev_decision", extra={
                    "classification_contract": contract,
                    "classification_schema_version": version,
                    "classification_model": model,
                    "classification_request_id": request_id,
                    "classification_latency_ms": result.latency_ms,
                    "classification_attempts": attempts,
                    "classification_status": "ok",
                    "classification_cost_source": "provider_receipt" if provider_cost_nano is not None else "estimated",
                    "classification_provider_cost_nano": provider_cost_nano,
                })
                return result
            except JevClientError as exc:
                logger.info("jev_decision", extra={
                    "classification_contract": contract,
                    "classification_schema_version": version,
                    "classification_model": model,
                    "classification_request_id": request_id,
                    "classification_latency_ms": round((time.monotonic() - started) * 1000),
                    "classification_attempts": attempts,
                    "classification_status": exc.code,
                })
                raise
            except httpx.TimeoutException:
                if attempts < 2 and deadline - time.monotonic() > 0.15:
                    continue
                logger.info("jev_decision", extra={
                    "classification_contract": contract, "classification_schema_version": version,
                    "classification_model": model, "classification_request_id": request_id,
                    "classification_latency_ms": round((time.monotonic() - started) * 1000),
                    "classification_attempts": attempts, "classification_status": "timeout",
                })
                raise JevClientError("timeout") from None
            except httpx.HTTPStatusError:
                if retry and attempts < 2 and deadline - time.monotonic() > 0.15:
                    continue
                logger.info("jev_decision", extra={
                    "classification_contract": contract, "classification_schema_version": version,
                    "classification_model": model, "classification_request_id": request_id,
                    "classification_latency_ms": round((time.monotonic() - started) * 1000),
                    "classification_attempts": attempts, "classification_status": "provider_http_error",
                })
                raise JevClientError("provider_http_error") from None
            except httpx.RequestError:
                retry = True
                if attempts < 2 and deadline - time.monotonic() > 0.15:
                    continue
                logger.info("jev_decision", extra={
                    "classification_contract": contract, "classification_schema_version": version,
                    "classification_model": model, "classification_request_id": request_id,
                    "classification_latency_ms": round((time.monotonic() - started) * 1000),
                    "classification_attempts": attempts, "classification_status": "provider_network_error",
                })
                raise JevClientError("provider_network_error") from None
            finally:
                self._finish_usage(ticket, provider_cost_nano, receipt_id)
        raise JevClientError("provider_unavailable")

    @staticmethod
    def _positive_float(name: str, default: str, *, maximum: float) -> float:
        try:
            value = float(os.getenv(name, default))
        except (TypeError, ValueError):
            return float(default)
        if not 0.1 <= value <= maximum:
            return float(default)
        return value

    @staticmethod
    def _begin_usage(model: str):
        try:
            from ..usage.operations import begin_external, configured_rate
            rate = configured_rate("OPENLEARN_JEV_USD_PER_REQUEST")
            ticket = begin_external(
                "tool", {"requests": 1}, rate, seconds=10,
                provider="openrouter", model=model,
                provider_rates={"usd_nano_per_request": rate, "billing_unit": "request"},
            )
            return ticket if ticket is not None else False
        except Exception as exc:
            # Do not call JEV when the paid capability cannot reserve its bound.
            logger.info("jev_decision", extra={"classification_status": "usage_unavailable",
                                                "classification_error": type(exc).__name__})
            raise JevClientError("usage_unavailable") from None

    @staticmethod
    def _usage_receipt(body) -> tuple[int | None, str | None]:
        """Read OpenRouter's optional raw HTTP usage receipt without trusting it as schema."""
        if not isinstance(body, dict):
            return None, None
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return None, None
        raw_cost = usage.get("cost")
        cost_nano = None
        if isinstance(raw_cost, (int, float, str)) and not isinstance(raw_cost, bool):
            try:
                from ..usage.pricing import dollars_to_nano
                cost_nano = dollars_to_nano(raw_cost)
                if cost_nano < 0:
                    cost_nano = None
            except Exception:
                cost_nano = None
        raw_id = body.get("id")
        receipt_id = raw_id.strip()[:200] if isinstance(raw_id, str) and raw_id.strip() else None
        return cost_nano, receipt_id if cost_nano is not None else None

    @staticmethod
    def _finish_usage(ticket, provider_cost_nano=None, receipt_id=None) -> None:
        if not ticket or ticket is False:
            return
        try:
            from ..usage.operations import finish_external
            if provider_cost_nano is not None:
                finish_external(ticket, cost_nano=provider_cost_nano, source="exact",
                                receipt_id=receipt_id)
            else:
                finish_external(ticket, source="estimated")
        except Exception as exc:
            logger.error("jev_usage_settlement_failed", extra={"classification_error": type(exc).__name__})


def choice(answer, allowed: set[str]) -> tuple[str, float]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise JevClientError("invalid_answer")
    value = answer.get("choice", answer.get("value"))
    if value not in allowed:
        raise JevClientError("invalid_answer")
    probabilities = answer.get("probabilities")
    # JEV's choice confidence describes concentration across the full label
    # distribution; it is not the probability of the selected label.
    score = probabilities.get(value) if isinstance(probabilities, dict) else None
    return value, probability(score)


def noul(answer) -> float:
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise JevClientError("invalid_answer")
    value = answer.get("noul")
    return probability(value)


def probability(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevClientError("invalid_score")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise JevClientError("invalid_score")
    return result
