"""Immutable, credential-free assessment role snapshots and provider resolution."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import logging
import time
from decimal import Decimal

from .model_provider import ModelProviderError, OpenRouterLessonProvider

ROLES = ("quiz_author", "assessment_verifier", "written_answer_evaluator")
PREFIXES = {role: "AI_TUTOR_" + role.upper() for role in ROLES}
SOL_MODEL = "openai/gpt-6.1-sol"


def enabled(name: str, default=False) -> bool:
    return os.getenv("AI_TUTOR_" + name.upper(), str(default)).lower() in {"true", "1", "yes"}


def profile_snapshot() -> dict:
    if not enabled("assessment_model_profiles"):
        return {}
    profiles = {}
    for role, prefix in PREFIXES.items():
        profile = {
            "role": role, "provider": os.getenv(prefix + "_PROVIDER", "openrouter"),
            "model": os.getenv(prefix + "_MODEL", SOL_MODEL),
            "effort": os.getenv(prefix + "_EFFORT", "high" if role == "quiz_author" else "medium"),
            "maxOutputTokens": int(os.getenv(prefix + "_OUTPUT_TOKENS", "6000" if role == "quiz_author" else "4000")),
            "inputBudgetTokens": int(os.getenv(prefix + "_INPUT_TOKENS", "10000")),
            "timeoutSeconds": int(os.getenv(prefix + "_TIMEOUT_SECONDS", "150")),
            "strictSchema": os.getenv(prefix + "_STRICT_SCHEMA", "true").lower() == "true",
            "rateVersion": os.getenv("OPENLEARN_ASSESSMENT_RATE_VERSION", ""),
        }
        if profile["provider"] not in {"openrouter", "openai"} or not profile["model"]:
            raise ModelProviderError("Invalid assessment model configuration.")
        if profile["effort"] not in {"low", "medium", "high", "xhigh", "max"}:
            raise ModelProviderError("Unsupported assessment reasoning effort.")
        if not 1 <= profile["maxOutputTokens"] <= 16000 or not 1000 <= profile["inputBudgetTokens"] <= 12000 or not 1 <= profile["timeoutSeconds"] <= 300:
            raise ModelProviderError("Assessment model limits are out of bounds.")
        profile["version"] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]
        profiles[role] = profile
    return profiles


def resolve_provider(base, role: str, profiles: dict | None = None):
    profiles = profile_snapshot() if profiles is None else profiles
    profile = profiles.get(role)
    if not profile:
        return base
    # Test doubles retain their deterministic implementation. Production transports
    # receive distinct instances; never mutate the shared lesson provider.
    if base is not None and not isinstance(base, OpenRouterLessonProvider):
        return base
    key_name = "OPENROUTER_API_KEY" if profile["provider"] == "openrouter" else "OPENAI_API_KEY"
    key = os.getenv(key_name)
    if not key and base is not None and getattr(base, "is_openai", False) == (profile["provider"] == "openai"):
        key = base.api_key
    if not key:
        raise ModelProviderError("The configured assessment provider needs a connected API key.")
    provider = (OpenRouterLessonProvider.openai(key, profile["model"]) if profile["provider"] == "openai"
                else OpenRouterLessonProvider(key, profile["model"], None, "Open Learn assessments"))
    provider.assessment_profile = copy.deepcopy(profile)
    provider.context_input_budget_tokens = profile["inputBudgetTokens"]
    return provider


def approved_tariff(model: str, profile: dict) -> dict:
    """Only explicitly configured assessment models may enter the paid ledger."""
    # Enrollment flags can be disabled during rollback without breaking sessions
    # already carrying an immutable profile. The explicit tariff allowlist still
    # controls which providers/models may spend, and its rate version stays pinned.
    content = {key: value for key, value in profile.items() if key != "version"}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]
    if (profile.get("version") != digest or profile.get("role") not in ROLES
            or profile.get("provider") not in {"openrouter", "openai"}
            or profile.get("model") != model
            or profile.get("effort") not in {"low", "medium", "high", "xhigh", "max"}
            or not 1 <= profile.get("maxOutputTokens", 0) <= 16000
            or not 1000 <= profile.get("inputBudgetTokens", 0) <= 12000
            or not 1 <= profile.get("timeoutSeconds", 0) <= 300):
        raise ValueError("Assessment profile is invalid or is not approved")
    version = os.getenv("OPENLEARN_ASSESSMENT_RATE_VERSION", "").strip()
    if not version or version != profile["rateVersion"]:
        raise ValueError("Assessment tariff is not pinned")
    tariffs = json.loads(os.getenv("OPENLEARN_ASSESSMENT_MODEL_TARIFFS", "{}"))
    tariff = tariffs.get(profile["provider"] + "/" + model)
    if not isinstance(tariff, dict):
        raise ValueError("No tariff for the configured assessment model")
    result = {key: Decimal(str(tariff[key])) for key in (
        "usd_per_million_input", "usd_per_million_output", "usd_per_million_cache_read")}
    result["usd_per_million_cache_write"] = Decimal(str(tariff.get("usd_per_million_cache_write", result["usd_per_million_input"])))
    if any(not value.is_finite() or value <= 0 for value in result.values()):
        raise ValueError("Assessment rates must be finite and positive")
    return result


def schema_for_transport(schema: dict) -> dict:
    """Strict JSON schema requires closed objects and all properties required."""
    schema = copy.deepcopy(schema)
    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in list(node.values()):
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    return schema


def complete(provider, instructions: str, data: dict, schema: dict):
    from .json_context_prompt import bounded_json_prompt
    profile = getattr(provider, "assessment_profile", None)
    # The transport already supplies the strict schema; avoid billing it twice.
    prompt_data = {key: value for key, value in data.items() if key != "schema"} if profile and profile["strictSchema"] else data
    prompt = bounded_json_prompt(provider, instructions, prompt_data, required=set(prompt_data))
    started = time.monotonic()
    status = "failed"
    try:
        if profile:
            result = provider.complete_json(prompt, max_tokens=profile["maxOutputTokens"],
                response_schema=schema if profile["strictSchema"] else None,
                reasoning_effort=profile["effort"], request_timeout=profile["timeoutSeconds"])
        else:
            result = provider.complete_json(prompt)
        status = "completed"
        return result
    finally:
        logging.getLogger(__name__).info("assessment_model_call", extra={
            "assessment_role": (profile or {}).get("role", "legacy"),
            "assessment_profile_version": (profile or {}).get("version"),
            "assessment_call_status": status, "assessment_latency_ms": round((time.monotonic() - started) * 1000)})
