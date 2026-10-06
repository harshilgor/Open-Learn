"""Audio transcription adapter and conservative boundary normalization."""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class TranscribedSpan:
    start_ms: int
    end_ms: int
    text: str
    speaker: str = "unknown"
    speaker_confidence: float | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    provider: str
    model: str
    spans: list[TranscribedSpan]


class TranscriptionProvider(Protocol):
    def transcribe_chunk(self, content: bytes, mime_type: str, duration_ms: int, previous_tail: str = "") -> TranscriptionResult: ...


class TranscriptionFailure(RuntimeError):
    def __init__(self, message: str, code: str = "transcription_failed", status_code: int = 502):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


_AUDIO_FORMATS = {
    "audio/webm": "webm", "audio/mp4": "m4a", "audio/mpeg": "mp3",
    "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/ogg": "ogg", "audio/aac": "aac", "audio/flac": "flac",
}


def _usage_failure(exc) -> TranscriptionFailure:
    """Translate a usage admission/settlement failure without losing its code."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        message = str(detail.get("message") or "Usage could not be confirmed for transcription.")
        code = str(detail.get("code") or "usage_accounting_unavailable")
    else:
        message, code = "Usage could not be confirmed for transcription.", "usage_accounting_unavailable"
    return TranscriptionFailure(message, code=code, status_code=getattr(exc, "status_code", 503))


def _reserve_transcription_usage(provider: str, model: str, duration_ms: int):
    """Reserve the configured per-minute maximum before each paid STT attempt."""
    from .usage.ledger import UsageError
    from .usage.operations import begin_external, configured_rate

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise TranscriptionFailure("The audio duration is invalid.", code="invalid_audio_duration", status_code=422)
    rate_name = {
        "openai": "OPENLEARN_OPENAI_STT_USD_PER_MINUTE",
        "openrouter": "OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE",
    }[provider]
    try:
        # Rates are operator-confirmed USD/minute ceilings. Prorate by known
        # media duration, rounding upward at nanodollar precision. Rounding
        # every short chunk to a whole provider-minute would multiply the
        # allowance charge for long recordings with many chunks.
        rate_nano = configured_rate(rate_name)
        liability = max(1, (rate_nano * duration_ms + 59_999) // 60_000)
        ticket = begin_external(
            "stt", {"milliseconds": duration_ms}, liability, seconds=240,
            provider=provider, model=model,
            provider_rates={"usd_nano_per_minute": rate_nano, "billing_unit": "minute"},
        )
    except UsageError as exc:
        raise _usage_failure(exc) from exc
    if ticket is None:
        raise TranscriptionFailure(
            "Sign in so usage can be checked before transcription.",
            code="usage_accounting_unavailable",
            status_code=503,
        )
    return ticket


def _settle_transcription_usage(ticket) -> None:
    """Retain the full estimate because these providers return no cost receipt."""
    from .usage.ledger import UsageError
    from .usage.operations import finish_external

    try:
        finish_external(ticket, source="estimated")
    except UsageError as exc:
        raise _usage_failure(exc) from exc
    except Exception as exc:
        raise TranscriptionFailure(
            "Usage could not be recorded after transcription. The saved audio is safe; retry after the service recovers.",
            code="usage_accounting_unavailable",
            status_code=503,
        ) from exc


def _metered_transcription_post(provider: str, model: str, duration_ms: int, *args, **kwargs):
    """Dispatch one request only after reserving; settle even on transport failure."""
    ticket = _reserve_transcription_usage(provider, model, duration_ms)
    try:
        response = httpx.post(*args, **kwargs)
    except BaseException:
        _settle_transcription_usage(ticket)
        raise
    _settle_transcription_usage(ticket)
    return response


def _transcription_spans(result: dict, duration_ms: int) -> list[TranscribedSpan]:
    spans: list[TranscribedSpan] = []
    provider_segments = result.get("segments")
    if isinstance(provider_segments, list) and provider_segments:
        for segment in provider_segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                continue
            try:
                start = max(0, min(duration_ms, int(float(segment.get("start", 0)) * 1000)))
                end = max(start, min(duration_ms, int(float(segment.get("end", duration_ms / 1000)) * 1000)))
            except (TypeError, ValueError, OverflowError):
                continue
            if segment["text"].strip():
                spans.append(TranscribedSpan(start, end, segment["text"].strip()))
    else:
        content_text = result.get("text")
        if isinstance(content_text, str) and content_text.strip():
            spans.append(TranscribedSpan(0, duration_ms, content_text.strip()))
    return spans


class OpenAITranscriptionProvider:
    def __init__(self, key: str | None = None, model: str | None = None):
        self.key = key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("AI_TUTOR_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")

    def transcribe_chunk(self, content: bytes, mime_type: str, duration_ms: int, previous_tail: str = "") -> TranscriptionResult:
        if not self.key:
            raise TranscriptionFailure("Connect an OpenAI API key to transcribe this lecture.")
        extension = "mp4" if mime_type == "audio/mp4" else _AUDIO_FORMATS.get(mime_type)
        if extension is None:
            raise TranscriptionFailure("The uploaded audio format is unsupported.")
        data = {"model": self.model, "response_format": "verbose_json" if self.model == "whisper-1" else "json"}
        if previous_tail.strip():
            data["prompt"] = previous_tail[-300:]
        try:
            response = _metered_transcription_post(
                "openai", self.model, duration_ms,
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.key}"},
                data=data,
                files={"file": (f"chunk.{extension}", content, mime_type)},
                timeout=httpx.Timeout(180, connect=15),
            )
            response.raise_for_status()
            result = response.json()
        except TranscriptionFailure:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise TranscriptionFailure("The transcription provider could not process this chunk. Retry it later.") from exc
        if not isinstance(result, dict):
            raise TranscriptionFailure("The transcription provider returned an invalid result.")
        return TranscriptionResult("openai", self.model, _transcription_spans(result, duration_ms))


class OpenRouterTranscriptionProvider:
    """Speech-to-text through OpenRouter, using its existing server-side key."""

    def __init__(self, key: str | None = None, model: str | None = None):
        self.key = key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("AI_TUTOR_OPENROUTER_TRANSCRIPTION_MODEL", "openai/whisper-large-v3")

    def transcribe_chunk(self, content: bytes, mime_type: str, duration_ms: int, previous_tail: str = "") -> TranscriptionResult:
        if not self.key:
            raise TranscriptionFailure("Connect an OpenRouter API key to transcribe this lecture.")
        audio_format = _AUDIO_FORMATS.get(mime_type)
        if audio_format is None:
            raise TranscriptionFailure("The uploaded audio format is unsupported.")
        try:
            request = ({"data": {"model": self.model, "response_format": "json"},
                        "files": {"file": (f"recording.{audio_format}", content, mime_type)}}
                       if len(content) > 4 * 1024 * 1024 else
                       {"json": {"model": self.model, "input_audio": {
                           "data": base64.b64encode(content).decode("ascii"), "format": audio_format}}})
            response = _metered_transcription_post("openrouter", self.model, duration_ms,
                "https://openrouter.ai/api/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=httpx.Timeout(75, connect=15), **request)
            response.raise_for_status()
            result = response.json()
        except TranscriptionFailure:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise TranscriptionFailure("OpenRouter could not transcribe this audio slice. Check model access and credits, then retry.") from exc
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise TranscriptionFailure("OpenRouter returned an invalid transcript.")
        return TranscriptionResult("openrouter", self.model, _transcription_spans(result, duration_ms))


def configured_transcription_provider() -> TranscriptionProvider:
    """Follow the selected text provider unless an audio provider is explicit."""
    selected = os.getenv("AI_TUTOR_TRANSCRIPTION_PROVIDER", "auto").strip().lower()
    if selected not in {"auto", "openai", "openrouter"}:
        raise TranscriptionFailure("AI_TUTOR_TRANSCRIPTION_PROVIDER must be auto, openai, or openrouter.")
    if selected == "auto":
        preferred = os.getenv("AI_TUTOR_PROVIDER", "").strip().lower()
        if preferred in {"openai", "openrouter"}:
            selected = preferred
        elif os.getenv("OPENROUTER_API_KEY"):
            selected = "openrouter"
        elif os.getenv("OPENAI_API_KEY"):
            selected = "openai"
        else:
            raise TranscriptionFailure("Connect an OpenRouter or OpenAI API key to transcribe this lecture.")
    return OpenRouterTranscriptionProvider() if selected == "openrouter" else OpenAITranscriptionProvider()


def normalize_text(raw_text: str, previous_normalized: str = "") -> str:
    """Keep raw speech immutable; remove only whitespace and exact boundary repeats.

    Context prompts can make ASR repeat a previous phrase. A three-word exact
    overlap is unambiguous enough to remove from the normalized display while
    preserving the raw segment and its evidence span.
    """
    current = " ".join(raw_text.split())
    if not previous_normalized or not current:
        return current
    prior_words = re.findall(r"\S+", previous_normalized)
    words = re.findall(r"\S+", current)
    for count in range(min(12, len(prior_words), len(words)), 2, -1):
        left = [word.casefold().strip(".,;:!?—-") for word in prior_words[-count:]]
        right = [word.casefold().strip(".,;:!?—-") for word in words[:count]]
        if left == right:
            return " ".join(words[count:])
    return current
