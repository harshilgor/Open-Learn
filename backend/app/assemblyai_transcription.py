"""Nonblocking AssemblyAI prerecorded transport for durable class jobs.

The caller must persist the upload URL and returned transcript ID between
steps. This adapter deliberately does not poll, sleep, or automatically retry
submission: a lost submission response may already have incurred a charge.
It is not enabled in the legacy synchronous chunk selector.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

import httpx

from .lecture_provider import (
    TranscriptionFailure, _reserve_transcription_usage, _settle_transcription_usage,
)


@dataclass(frozen=True)
class AssemblyWord:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None
    speaker_id: str | None


@dataclass(frozen=True)
class AssemblyTranscript:
    request_id: str
    status: str
    text: str | None
    words: tuple[AssemblyWord, ...]
    model: str | None
    confidence: float | None


def _confidence(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid confidence")
    if not 0 <= value <= 1 or not math.isfinite(value):
        raise ValueError("Invalid confidence")
    return float(value)


def _request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise TranscriptionFailure("AssemblyAI returned an invalid request identifier.")
    return value


class AssemblyAITranscriptionAdapter:
    # Reviewed against the prerecorded API's speech_models contract. Extend
    # deliberately when adding model-specific languages/capabilities/pricing.
    SUPPORTED_MODELS = frozenset({"universal-3-5-pro", "universal-2"})

    def __init__(self, *, key=None, model=None, region="us", transport=None):
        self.key = key or os.getenv("ASSEMBLYAI_API_KEY")
        self.model = model or os.getenv("OPENLEARN_CLASS_VERIFICATION_MODEL", "")
        if region not in {"us", "eu"}:
            raise ValueError("AssemblyAI region must be us or eu.")
        self.base_url = "https://api.assemblyai.com" if region == "us" else "https://api.eu.assemblyai.com"
        self.transport = transport

    def _configured(self):
        if not self.key:
            raise TranscriptionFailure("AssemblyAI is not configured.", code="provider_unavailable", status_code=503)
        if self.model not in self.SUPPORTED_MODELS:
            raise TranscriptionFailure("Configure a supported AssemblyAI verification model.", code="unsupported_model", status_code=422)

    def _request(self, method, path, *, uncertain_submission=False, **kwargs):
        self._configured()
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
                headers = {"Authorization": self.key}
                if "content" in kwargs:
                    headers["Content-Type"] = "application/octet-stream"
                response = client.request(method, self.base_url + path, headers=headers, **kwargs)
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid payload")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            # Provider response bodies/URLs can contain private audio or secrets.
            # Do not surface them through API errors or exception chaining.
            ambiguous = uncertain_submission and (
                not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
            )
            code = "provider_submission_unknown" if ambiguous else "transcription_provider_failed"
            message = ("AssemblyAI submission outcome is unknown; reconcile it before resubmitting."
                       if ambiguous else "AssemblyAI could not complete this request.")
            raise TranscriptionFailure(message, code=code) from None

    def upload(self, content: bytes) -> str:
        self._configured()
        if not isinstance(content, bytes) or not 0 < len(content) <= 24 * 1024 * 1024:
            raise TranscriptionFailure("Verification audio must be between 1 byte and 24 MB.", code="invalid_audio", status_code=422)
        value = self._request("POST", "/v2/upload", content=content).get("upload_url")
        self.validate_upload_url(value)
        return value

    def validate_upload_url(self, value):
        # Documented provider CDN URLs only; arbitrary source URLs must not
        # reach provider fetches through this adapter.
        try:
            url = httpx.URL(value) if isinstance(value, str) else None
        except httpx.InvalidURL:
            url = None
        if (url is None or url.scheme != "https" or url.host not in {"cdn.assemblyai.com", "cdn.eu.assemblyai.com"}
                or not url.path.startswith("/upload/") or url.username or url.password or url.port not in {None, 443}):
            raise TranscriptionFailure("AssemblyAI returned an invalid upload URL.")

    def submit(self, upload_url: str, duration_ms: int, *, keyterms=(), speaker_labels=False) -> str:
        self._configured()
        self.validate_upload_url(upload_url)
        if (isinstance(duration_ms, bool) or not isinstance(duration_ms, int)
                or not 0 < duration_ms <= 120_000):
            raise TranscriptionFailure("Verification windows must be at most two minutes.", code="invalid_audio_duration", status_code=422)
        if (not isinstance(keyterms, (list, tuple)) or len(keyterms) > 100
                or any(not isinstance(term, str) or not term.strip() or len(term) > 50 for term in keyterms)):
            raise TranscriptionFailure("Course vocabulary exceeds the bounded hint limit.", code="invalid_vocabulary", status_code=422)
        payload = {"audio_url": upload_url, "speech_models": [self.model], "language_detection": True}
        addons = []
        if speaker_labels:
            payload['speaker_labels'] = True
            addons.append('OPENLEARN_ASSEMBLYAI_DIARIZATION_USD_PER_MINUTE')
        if keyterms:
            payload['keyterms_prompt'] = list(dict.fromkeys(term.strip() for term in keyterms))
            if self.model != 'universal-2':
                addons.append('OPENLEARN_ASSEMBLYAI_KEYTERMS_USD_PER_MINUTE')
        ticket = (_reserve_transcription_usage("assemblyai", self.model, duration_ms, addon_rates=tuple(addons)) if addons
                  else _reserve_transcription_usage("assemblyai", self.model, duration_ms))
        try:
            result = self._request("POST", "/v2/transcript", json=payload, uncertain_submission=True)
            try:
                return _request_id(result.get("id"))
            except TranscriptionFailure:
                raise TranscriptionFailure(
                    "AssemblyAI accepted a submission without a usable request ID; reconcile it before resubmitting.",
                    code="provider_submission_unknown",
                ) from None
        finally:
            # Conservatively retain the bounded cost estimate even if the
            # request result is ambiguous. Never bill status polling again.
            _settle_transcription_usage(ticket)

    def verify_request_source(self,request_id,upload_url):
        identifier=_request_id(request_id)
        self.validate_upload_url(upload_url)
        result=self._request('GET','/v2/transcript/'+identifier)
        if result.get('id')!=identifier or result.get('audio_url')!=upload_url:
            raise TranscriptionFailure('Provider receipt does not match this uploaded recording.',code='provider_receipt_mismatch',status_code=409)
        return identifier

    def get(self, request_id: str, duration_ms: int) -> AssemblyTranscript:
        identifier = _request_id(request_id)
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 0 < duration_ms <= 120_000:
            raise TranscriptionFailure("Invalid verification duration.", code="invalid_audio_duration", status_code=422)
        result = self._request("GET", "/v2/transcript/" + identifier)
        if result.get("id") != identifier:
            raise TranscriptionFailure("AssemblyAI returned a different transcript.")
        status = result.get("status")
        if status not in {"queued", "processing", "completed", "error"}:
            raise TranscriptionFailure("AssemblyAI returned an invalid processing state.")
        if status == "error":
            raise TranscriptionFailure("AssemblyAI could not transcribe this saved audio.")
        if status != "completed":
            return AssemblyTranscript(identifier, status, None, (), None, None)
        try:
            text = result.get("text")
            words = result.get("words")
            if words is None:
                words = []
            if (not isinstance(text, str) or len(text) > 100_000
                    or not isinstance(words, list) or len(words) > 10_000):
                raise ValueError("Invalid transcript")
            prepared = []
            previous_start = -1
            for word in words:
                start, end = word["start"], word["end"]
                if (any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end))
                        or not 0 <= start <= end <= duration_ms or start < previous_start
                        or not isinstance(word["text"], str) or not 0 < len(word["text"]) <= 1000):
                    raise ValueError("Invalid word")
                speaker = word.get("speaker")
                if speaker is not None and (not isinstance(speaker, str) or len(speaker) > 100):
                    raise ValueError("Invalid speaker")
                prepared.append(AssemblyWord(word["text"], start, end, _confidence(word.get("confidence")), speaker))
                previous_start = start
            model = result.get("speech_model_used")
            if model is not None and (not isinstance(model, str) or len(model) > 100):
                raise ValueError("Invalid model")
            return AssemblyTranscript(identifier, status, text, tuple(prepared), model, _confidence(result.get("confidence")))
        except (ValueError, TypeError, KeyError):
            raise TranscriptionFailure("AssemblyAI returned invalid transcript evidence.") from None

    def delete(self, request_id: str):
        """Delete remote transcript data during retention cleanup."""
        self._request("DELETE", "/v2/transcript/" + _request_id(request_id))
