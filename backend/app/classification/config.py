"""Central rollout configuration for semantic classification contracts."""

from __future__ import annotations

import os
import re
import hashlib

_ROLLOUT_MODES = {"off", "shadow", "active"}


def _env_mode(name: str) -> str | None:
    value = os.getenv(name, "").strip().lower()
    if value in _ROLLOUT_MODES:
        return value
    return None


def rollout_mode(contract: str) -> str:
    """Return a contract's rollout mode while preserving the old mode flag.

    New deployments should set OPENLEARN_CLASSIFICATION_MODE and may override
    individual contracts with OPENLEARN_CLASSIFIER_<CONTRACT>_MODE. The old
    mode-only variable remains a compatibility switch for mode classification.
    """
    suffix = re.sub(r"[^A-Z0-9]+", "_", contract.upper()).strip("_")
    specific = _env_mode(f"OPENLEARN_CLASSIFIER_{suffix}_MODE")
    if specific:
        return specific

    global_mode = _env_mode("OPENLEARN_CLASSIFICATION_MODE")
    if global_mode:
        return global_mode

    if contract == "mode_intent":
        legacy = os.getenv("AI_TUTOR_MODE_CLASSIFICATION", "").strip().lower()
        if legacy == "rules":
            return "off"
        if legacy == "jev":
            return "active"
        if legacy in {"provider", "hybrid"}:
            # Keep the legacy provider live while collecting JEV shadow data.
            return "shadow"

    # The staged migration starts in shadow until each domain's evaluation
    # benchmark promotes it. JEV must still be explicitly provisioned/metered.
    return "shadow"


def jev_requested() -> bool:
    """Whether any configured classification contract may dispatch to JEV."""
    modes = [rollout_mode(contract) for contract in (
        "mode_intent", "turn_route", "teaching_intent", "browser_task",
        "reminder_action", "evidence_outcome", "concept_candidate",
    )]
    return "active" in modes or "shadow" in modes and shadow_sample_rate() > 0


def shadow_sample_rate() -> float:
    try:
        rate = float(os.getenv("OPENLEARN_CLASSIFICATION_SHADOW_SAMPLE_RATE", "0"))
    except (TypeError, ValueError):
        return 0.0
    return rate if 0.0 < rate <= 1.0 else 0.0


def should_sample_shadow(contract: str, sample_key: str) -> bool:
    """Stable, privacy-safe sampling for shadow traffic."""
    rate = shadow_sample_rate()
    if rate <= 0:
        return False
    digest = hashlib.sha256((contract + "\0" + str(sample_key)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64) < rate


def score_threshold(contract: str, decision: str = "default", *, default: float = 0.82) -> float:
    """Read a bounded, per-contract promotion threshold.

    Defaults are conservative launch guards, not claims of statistical
    calibration. Production thresholds must be set from the labeled eval set.
    """
    suffix = re.sub(r"[^A-Z0-9]+", "_", f"{contract}_{decision}".upper()).strip("_")
    raw = os.getenv(f"OPENLEARN_CLASSIFIER_{suffix}_SCORE", str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value <= 1.0 else default


def min_score(contract: str, decision: str = "default", *, default: float = 0.82) -> float:
    """Compatibility helper for a minimum-score contract setting."""
    return score_threshold(contract, decision, default=default)
