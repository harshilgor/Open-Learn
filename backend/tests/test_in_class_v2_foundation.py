import httpx
import pytest
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text

from backend.app import assemblyai_transcription as assembly
from backend.app.in_class_service import practice_due
from backend.app.lecture_provider import TranscriptionFailure
from backend.app.storage import Store
from backend.app.usage.context import usage_scope
from backend.scripts.class_transcription_benchmark import score, tokens, word_errors


def adapter(handler):
    return assembly.AssemblyAITranscriptionAdapter(key="private-key", model="universal-3-5-pro", transport=httpx.MockTransport(handler))


def test_provider_receipt_must_match_original_uploaded_audio():
    provider=adapter(lambda request:httpx.Response(200,json={'id':'receipt','audio_url':'https://cdn.assemblyai.com/upload/original'}))
    assert provider.verify_request_source('receipt','https://cdn.assemblyai.com/upload/original')=='receipt'
    with pytest.raises(TranscriptionFailure) as error:provider.verify_request_source('receipt','https://cdn.assemblyai.com/upload/another')
    assert error.value.code=='provider_receipt_mismatch'


@pytest.mark.parametrize("model", ["", "unreviewed-model"])
def test_missing_or_unreviewed_model_fails_before_upload(model, monkeypatch):
    monkeypatch.delenv("OPENLEARN_CLASS_VERIFICATION_MODEL", raising=False)
    provider = assembly.AssemblyAITranscriptionAdapter(key="private-key", model=model, transport=httpx.MockTransport(lambda request: pytest.fail("must not dispatch")))
    with pytest.raises(TranscriptionFailure) as error:
        provider.upload(b"audio")
    assert error.value.code == "unsupported_model"


def test_upload_uses_documented_cdn_and_keeps_secret_server_side():
    def handle(request):
        assert request.url == "https://api.assemblyai.com/v2/upload"
        assert request.headers["authorization"] == "private-key"
        assert request.content == b"audio"
        return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/audio-id"})
    assert adapter(handle).upload(b"audio").endswith("audio-id")


@pytest.mark.parametrize("url", ["http://cdn.assemblyai.com/upload/a", "https://attacker.test/upload/a", "https://cdn.assemblyai.com.attacker.test/upload/a", "https://secret@cdn.assemblyai.com/upload/a"])
def test_reject_arbitrary_upload_urls_without_network(url):
    with pytest.raises(TranscriptionFailure):
        adapter(lambda request: pytest.fail("must not call network")).submit(url, 1000)


def test_submit_meters_once_and_polling_does_not_charge(monkeypatch):
    calls, metering = [], []
    monkeypatch.setattr(assembly, "_reserve_transcription_usage", lambda *args: metering.append(args) or "ticket")
    monkeypatch.setattr(assembly, "_settle_transcription_usage", lambda ticket: metering.append(ticket))
    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "request-id", "status": "queued"})
        return httpx.Response(200, json={"id": "request-id", "status": "processing"})
    provider = adapter(handle)
    assert provider.submit("https://cdn.assemblyai.com/upload/a", 1000) == "request-id"
    assert provider.get("request-id", 1000).status == "processing"
    assert calls == ["POST", "GET"]
    assert metering == [("assemblyai", "universal-3-5-pro", 1000), "ticket"]


def test_assemblyai_usage_rate_reaches_existing_ledger(monkeypatch):
    monkeypatch.setenv("OPENLEARN_USAGE_PAID_ROUTES_ENABLED", "true")
    monkeypatch.setenv("OPENLEARN_PROVIDER_RATE_VERSION", "test-rates")
    monkeypatch.setenv("OPENLEARN_ASSEMBLYAI_STT_USD_PER_MINUTE", "0.006")
    test_dir = Path("work") / ("assemblyai-ledger-" + uuid4().hex)
    test_dir.mkdir(parents=True)
    store = Store(test_dir / "ledger.sqlite")
    try:
        provider = adapter(lambda request: httpx.Response(200, json={"id": "request-id"}))
        with usage_scope(store, "alice", "class-test"):
            provider.submit("https://cdn.assemblyai.com/upload/a", 1000)
        with store.engine.connect() as conn:
            event = conn.execute(text("SELECT component,cost_nano,source FROM usage_events WHERE owner_id='alice'")).one()
        assert event.component == "stt"
        assert event.cost_nano == 100_000
        assert event.source == "estimated"
    finally:
        store.close()


def test_unknown_submission_is_not_retried_and_still_settled(monkeypatch):
    settled, calls = [], []
    monkeypatch.setattr(assembly, "_reserve_transcription_usage", lambda *args: "ticket")
    monkeypatch.setattr(assembly, "_settle_transcription_usage", settled.append)
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-key provider error", request=request)
    with pytest.raises(TranscriptionFailure) as error:
        adapter(handle).submit("https://cdn.assemblyai.com/upload/a", 1000)
    assert error.value.code == "provider_submission_unknown"
    assert "private-key" not in str(error.value)
    assert len(calls) == 1 and settled == ["ticket"]


def test_missing_submission_identifier_requires_reconciliation(monkeypatch):
    monkeypatch.setattr(assembly, "_reserve_transcription_usage", lambda *args: "ticket")
    monkeypatch.setattr(assembly, "_settle_transcription_usage", lambda ticket: None)
    with pytest.raises(TranscriptionFailure) as error:
        adapter(lambda request: httpx.Response(200, json={"status": "queued"})).submit("https://cdn.assemblyai.com/upload/a", 1000)
    assert error.value.code == "provider_submission_unknown"


def test_completed_words_preserve_provider_speaker_and_missing_confidence():
    result = adapter(lambda request: httpx.Response(200, json={"id": "request-id", "status": "completed", "text": "Hello", "words": [{"text": "Hello", "start": 0, "end": 500, "speaker": "A"}]})).get("request-id", 1000)
    assert result.words[0].speaker_id == "A"  # Never assume A means professor.
    assert result.words[0].confidence is None and result.confidence is None


@pytest.mark.parametrize("patch", [{"start": -1}, {"end": 1001}, {"confidence": float("nan")}, {"start": True}])
def test_invalid_evidence_rejected(patch):
    word = {"text": "Hello", "start": 0, "end": 500, **patch}
    with pytest.raises(TranscriptionFailure):
        adapter(lambda request: httpx.Response(200, json={"id": "request-id", "status": "completed", "text": "Hello", "words": [word]})).get("request-id", 1000)


@pytest.mark.parametrize("kwargs", [{"speaker_labels": True}, {"keyterms": ["mitochondria"]}])
def test_unpriced_addons_cannot_dispatch(kwargs):
    with pytest.raises(TranscriptionFailure) as error:
        adapter(lambda request: pytest.fail("must not call network")).submit("https://cdn.assemblyai.com/upload/a", 1000, **kwargs)
    assert error.value.code == "usage_provider_unavailable"


@pytest.mark.parametrize("minutes", [10, 20])
def test_first_interval_practice_waits_for_interval(minutes):
    policy = {"practiceCadence": f"every_{minutes}_minutes"}
    interval = minutes * 60_000
    assert not practice_due(policy, None, interval - 1)
    assert practice_due(policy, None, interval)
    assert not practice_due(policy, interval, interval + 1)
    assert practice_due(policy, interval, interval * 2)


def test_at_end_and_disabled_practice_preserved():
    assert not practice_due({"practiceCadence": "off"}, None, 600_000, at_end=True)
    assert not practice_due({"practiceCadence": "at_end"}, None, 1)
    assert practice_due({"practiceCadence": "at_end"}, None, 1, at_end=True)


def test_benchmark_counts_real_errors_and_preserves_repetition():
    errors = word_errors(tokens("a b c"), tokens("a x c d"))
    assert errors["errors"] == 2 and errors["substitutions"] == 1 and errors["insertions"] == 1
    report = score([{"id": "one", "group": "biology", "reference": "Mitochondria mitochondria", "hypothesis": "mitochondria", "terms": ["mitochondria"]}])
    assert report["overall"]["wer"] == 0.5
    assert report["overall"]["termRecall"] == 0.5
    assert report["groups"]["biology"]["deletions"] == 1


def test_empty_reference_does_not_claim_perfect_recognition():
    result = score([{"id": "silence", "reference": "", "hypothesis": "hallucination"}])
    assert result["overall"]["wer"] is None
    assert result["overall"]["insertions"] == 1
    assert result["overall"]["measuredCostUsd"] is None
    assert result["overall"]["latencyP95Ms"] is None


def test_measured_cost_and_latency_report_their_sample_counts():
    result = score([{"id": "one", "reference": "a", "hypothesis": "a", "costUsd": 0.25, "latencyMs": 800},
                    {"id": "two", "reference": "a", "hypothesis": "a"}])["overall"]
    assert result["costSampleCount"] == result["latencySampleCount"] == 1
    assert result["measuredCostUsd"] == 0.25 and result["latencyP95Ms"] == 800


def test_duplicate_benchmark_samples_rejected():
    with pytest.raises(ValueError):
        score([{"id": "a", "reference": "", "hypothesis": ""}] * 2)
