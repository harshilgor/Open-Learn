from decimal import Decimal

import pytest

from backend.app.usage.ledger import UsageError
from backend.app.usage.policy import Policy
from backend.app.usage.transport import _liability_nano, haiku55_rates


def test_haiku55_requires_all_explicit_rates(monkeypatch):
    monkeypatch.setenv('OPENLEARN_HAIKU55_INPUT_USD_PER_MILLION', '0.10')
    monkeypatch.setenv('OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION', '0.50')
    monkeypatch.delenv('OPENLEARN_HAIKU55_CACHE_READ_USD_PER_MILLION', raising=False)
    with pytest.raises(UsageError) as error:
        haiku55_rates()
    assert error.value.detail['code'] == 'usage_provider_unavailable'


def test_haiku55_liability_uses_integer_nano_dollars_and_ceil_rounding():
    # 1,000 input tokens at $0.10/M plus 100 output tokens at $0.50/M = $0.00015.
    assert _liability_nano(1000, 100, Decimal('0.10'), Decimal('0.50')) == 150_000
    assert _liability_nano(1, 0, Decimal('0.10'), Decimal('0.50')) == 100


def test_production_paid_haiku_requires_explicit_budget_and_tariff(monkeypatch):
    monkeypatch.setenv('AI_TUTOR_ENV', 'production')
    monkeypatch.setenv('OPENLEARN_USAGE_MODE', 'enforce')
    monkeypatch.setenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED', 'true')
    monkeypatch.setenv('OPENLEARN_PLATFORM_DAILY_BUDGET_USD', '1')
    monkeypatch.setenv('OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD', '10')
    monkeypatch.setenv('OPENLEARN_PROVIDER_RATE_VERSION', 'haiku55-2026-10-07-v1')
    monkeypatch.setenv('OPENROUTER_MODEL', 'anthropic/claude-haiku-5.5')
    monkeypatch.setenv('OPENLEARN_HAIKU55_INPUT_USD_PER_MILLION', '0.10')
    monkeypatch.setenv('OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION', '0.50')
    monkeypatch.setenv('OPENLEARN_HAIKU55_CACHE_READ_USD_PER_MILLION', '0.01')
    monkeypatch.setenv('OPENLEARN_VOICE_ENABLED', 'false')
    monkeypatch.setenv('OPENLEARN_DICTATION_ENABLED', 'false')
    monkeypatch.setenv('OPENLEARN_CLOUD_BROWSER_ENABLED', 'false')
    monkeypatch.setenv('OPENLEARN_SANDBOX_ENABLED', 'false')
    monkeypatch.setenv('AI_TUTOR_WEB_EVIDENCE', 'false')
    monkeypatch.setenv('AI_TUTOR_MODE_CLASSIFICATION', 'rules')
    monkeypatch.setenv('AI_TUTOR_EMBEDDING_MODEL', 'off')
    assert Policy.load().paid
    monkeypatch.delenv('OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION')
    with pytest.raises(RuntimeError, match='OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION'):
        Policy.load()
