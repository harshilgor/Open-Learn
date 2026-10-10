import pytest
from backend.app.visual_pricing import approved_visual_tariff


def test_visual_role_requires_exact_model_and_reviewed_tariff(monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL','test/model')
    monkeypatch.setenv('OPENLEARN_VISUAL_RATE_VERSION','review-1')
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL_TARIFFS','{"test/model":{"provider":"openrouter","usd_per_million_input":1,"usd_per_million_output":5,"usd_per_million_cache_read":1}}')
    assert approved_visual_tariff('test/model')['usd_per_million_output']==5
    with pytest.raises(ValueError):approved_visual_tariff('unreviewed/model')
    monkeypatch.setenv('OPENLEARN_VISUAL_RATE_VERSION','')
    with pytest.raises(ValueError):approved_visual_tariff('test/model')


def test_visual_tariffs_reject_nonfinite_rates(monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL','test/model');monkeypatch.setenv('OPENLEARN_VISUAL_RATE_VERSION','review')
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL_TARIFFS','{"test/model":{"provider":"openrouter","usd_per_million_input":"NaN","usd_per_million_output":1,"usd_per_million_cache_read":1}}')
    with pytest.raises(ValueError):approved_visual_tariff('test/model')


def test_visual_tariffs_reject_missing_rate(monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL', 'test/model')
    monkeypatch.setenv('OPENLEARN_VISUAL_RATE_VERSION', 'review')
    monkeypatch.setenv('OPENLEARN_VISUAL_MODEL_TARIFFS', '{"test/model":{"provider":"openrouter"}}')
    with pytest.raises(ValueError, match='Invalid visual model tariff'):
        approved_visual_tariff('test/model')
