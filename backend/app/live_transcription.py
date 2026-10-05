"""Short-lived credentials for opt-in, provisional lecture captions."""
from __future__ import annotations

import hashlib
import os
from typing import Protocol

import httpx


class LiveTranscriptionProvider(Protocol):
    def create_client_secret(self, owner_id: str) -> dict[str, object]: ...


class OpenAIRealtimeTranscriptionProvider:
    """Mint a transcription-only Realtime credential; the API key stays server-side."""

    SUPPORTED_MODELS = frozenset({"gpt-live-transcribe"})

    def __init__(self, key: str | None = None):
        self.key = key or os.getenv("OPENAI_API_KEY")

    def create_client_secret(self, owner_id: str) -> dict[str, object]:
        if not self.key:
            raise RuntimeError("Live captions are not configured.")
        model = os.getenv("AI_TUTOR_LIVE_TRANSCRIPTION_MODEL", "gpt-live-transcribe").strip()
        if model not in self.SUPPORTED_MODELS:
            raise RuntimeError(
                "AI_TUTOR_LIVE_TRANSCRIPTION_MODEL must be gpt-live-transcribe."
            )
        session = {
            "type": "transcription",
            "audio": {
                "input": {
                    "transcription": {"model": model},
                    "turn_detection": None,
                }
            },
        }
        try:
            response = httpx.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                    "OpenAI-Safety-Identifier": hashlib.sha256(owner_id.encode("utf-8")).hexdigest(),
                },
                json={"session": session},
                timeout=httpx.Timeout(20, connect=8),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("The live caption provider could not start a session.") from exc
        value = payload.get("value") if isinstance(payload, dict) else None
        expires_at = payload.get("expires_at") if isinstance(payload, dict) else None
        if not isinstance(value, str) or not value or not isinstance(expires_at, (int, float)):
            raise RuntimeError("The live caption provider returned an invalid session.")
        return {"value": value, "expiresAt": int(expires_at)}


def live_transcription_enabled() -> bool:
    return os.getenv("OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def configured_live_transcription_provider() -> LiveTranscriptionProvider:
    return OpenAIRealtimeTranscriptionProvider()
