"""Server-side provider key management for browser (non-desktop) clients.

The desktop shell keeps keys in the OS credential store and injects them as
process environment. The browser development shell has no such bridge, so this
module persists keys to the server's own ``backend/.env`` file -- the exact
location already documented in ``backend/.env.example``. Key values are never
returned by any endpoint; callers only learn presence. Browser changes are
applied to new requests immediately.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .material_routes import material_owner

APP_ROOT = Path(__file__).resolve().parents[1]

_PROVIDER_ENV_VAR = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY"}
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.\-+/=:]+$")


def env_path() -> Path:
    return APP_ROOT / ".env"


def _read_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name = name.strip()
        if name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            values[name] = value.strip().strip("'\"")
    return values


def _write_values(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Upsert or delete KEY=VALUE lines, preserving comments and ordering."""
    target = path or env_path()
    try:
        lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"code": "env_unreadable", "message": "The server configuration could not be read."}) from exc
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.partition("=")[0].strip()
            if name in updates:
                seen.add(name)
                if updates[name] is not None:
                    output.append(f"{name}={updates[name]}")
                continue
        output.append(line)
    for name, value in updates.items():
        if name not in seen and value is not None:
            output.append(f"{name}={value}")
    try:
        target.write_text("\n".join(output) + "\n", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"code": "env_not_writable", "message": "The server configuration is not writable. Set the key in backend/.env directly."}) from exc


def effective_provider(values: dict[str, str]) -> str:
    name = (os.getenv("AI_TUTOR_PROVIDER") or values.get("AI_TUTOR_PROVIDER") or "deterministic_baseline").lower()
    return name if name in {"openrouter", "openai"} else "deterministic_baseline"


def key_present(var: str, values: dict[str, str]) -> bool:
    return bool(os.getenv(var) or values.get(var))


class ProviderKeyInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: Literal["openrouter", "openai"]
    api_key: str = Field(min_length=8, max_length=500, validation_alias="apiKey")

    @field_validator("api_key")
    @classmethod
    def safe_characters(cls, value: str) -> str:
        value = value.strip()
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError("The API key contains unsupported characters.")
        return value


def build_provider_key_router(on_change: Callable[[dict[str, str]], None] | None = None,
                              provider_getter: Callable[[], object] | None = None) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def restart_required(values: dict[str, str]) -> bool:
        if provider_getter is None:
            return False
        active = provider_getter()
        desired = values.get("AI_TUTOR_PROVIDER", "deterministic_baseline").lower()
        if desired not in {"openrouter", "openai"}:
            return active is not None
        return (active is None or str(getattr(active, "provider_name", "")).split("/")[0] != desired
                or getattr(active, "api_key", None) != values.get(_PROVIDER_ENV_VAR[desired]))

    def apply(values: dict[str, str]) -> None:
        if on_change is not None:
            on_change(values)

    @router.get("/provider-settings")
    def status(owner: str = Depends(material_owner)) -> dict:
        values = _read_values(env_path())
        return {
            "provider": effective_provider(values),
            "openRouterConfigured": key_present("OPENROUTER_API_KEY", values),
            "openAiConfigured": key_present("OPENAI_API_KEY", values),
            "restartRequired": restart_required(values),
        }

    @router.post("/provider-settings/test")
    def test_connection(owner: str = Depends(material_owner)) -> dict:
        provider = provider_getter() if provider_getter is not None else None
        if provider is None:
            raise HTTPException(status_code=503, detail={"code": "provider_unavailable", "message": "Connect a model provider before testing the connection."})
        try:
            result = provider.complete_json('Return exactly this JSON object: {"connection": "ok"}.', 32)
            if not isinstance(result, dict):
                raise ValueError("Invalid provider result")
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"code": "provider_test_failed", "message": "The provider did not complete a small connection check. Verify the key, model access, and provider availability."}) from exc
        return {"connected": True, "provider": str(getattr(provider, "provider_name", "Configured provider")), "model": str(getattr(provider, "model", "Unknown model"))}

    @router.put("/provider-settings")
    def save_key(request: ProviderKeyInput, owner: str = Depends(material_owner)) -> dict:
        _write_values({_PROVIDER_ENV_VAR[request.provider]: request.api_key, "AI_TUTOR_PROVIDER": request.provider})
        values = _read_values(env_path())
        apply(values)
        return {
            "provider": effective_provider(values),
            "openRouterConfigured": key_present("OPENROUTER_API_KEY", values),
            "openAiConfigured": key_present("OPENAI_API_KEY", values),
            "restartRequired": restart_required(values),
        }

    @router.delete("/provider-settings/{provider}")
    def delete_key(provider: Literal["openrouter", "openai"], owner: str = Depends(material_owner)) -> dict:
        values = _read_values(env_path())
        updates: dict[str, str | None] = {_PROVIDER_ENV_VAR[provider]: None}
        if values.get("AI_TUTOR_PROVIDER", "").lower() == provider:
            updates["AI_TUTOR_PROVIDER"] = "deterministic_baseline"
        _write_values(updates)
        values = _read_values(env_path())
        apply(values)
        return {
            "provider": effective_provider(values),
            "openRouterConfigured": key_present("OPENROUTER_API_KEY", values),
            "openAiConfigured": key_present("OPENAI_API_KEY", values),
            "restartRequired": restart_required(values),
        }

    return router
