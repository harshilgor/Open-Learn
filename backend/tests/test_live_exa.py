"""Optional live Exa contract checks. Opt-in only.

RUN_LIVE_EXA_TESTS=true EXA_API_KEY=... pytest -m live_provider backend/tests/test_live_exa.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Local server keys live in backend/.env (gitignored). Load before config reads.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from backend.app.web_evidence.config import load_web_evidence_config
from backend.app.web_evidence.exa import ExaWebEvidenceProvider
from backend.app.web_evidence.models import PolicyDecision, PolicyDecisionKind, PolicyReason, SearchIntent


@pytest.mark.live_provider
def test_live_exa_search_contract():
    if os.getenv("RUN_LIVE_EXA_TESTS", "").lower() != "true":
        pytest.skip("Set RUN_LIVE_EXA_TESTS=true to call the live Exa API.")
    config = load_web_evidence_config()
    if not config.exa_api_key:
        pytest.skip("EXA_API_KEY is required for live Exa tests.")
    # Force enabled for the live contract even if the feature flag is off locally.
    live = type(config)(**{**config.__dict__, "enabled": True, "max_retries": 0, "timeout_seconds": 20})
    provider = ExaWebEvidenceProvider(live)
    decision = PolicyDecision(
        decision=PolicyDecisionKind.allow_with_constraints,
        reason_code=PolicyReason.allowed,
        max_results=2,
        max_chars_per_source=400,
        max_total_evidence_chars=800,
    )
    try:
        hits = provider.search(
            "NIST definition of the metre",
            intent=SearchIntent.definition,
            decision=decision,
        )
        assert isinstance(hits, list)
        assert hits, "Live acceptance requires at least one usable source."
        assert len(hits) <= decision.max_results
        for hit in hits:
            assert hit.url.startswith("https://")
            assert hit.excerpt.strip()
            assert len(hit.excerpt) <= decision.max_chars_per_source
            assert hit.provider_result_ref
        opened = provider.open_result(
            hits[0].provider_result_ref, focus=None, decision=decision,
        )
        assert opened.provider_result_ref == hits[0].provider_result_ref
        assert opened.url.startswith("https://")
        assert opened.excerpt.strip()
        assert len(opened.excerpt) <= decision.max_chars_per_source
    finally:
        provider.close()
