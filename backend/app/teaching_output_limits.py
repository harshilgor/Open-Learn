"""Generous output ceilings for model-generated teaching responses.

The selected gear controls how much detail to write. These values only leave
enough room to finish a useful response; they are not target lengths.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .context_engine import GenerationContext
from .session_models import TeachingGear


TEACHING_OUTPUT_CEILINGS = {
    TeachingGear.quick: 6144,
    TeachingGear.guided: 12288,
    TeachingGear.deep: 20480,
}

CONVERSATION_OUTPUT_CEILINGS = {
    TeachingGear.quick: 384,
    TeachingGear.guided: 1024,
    TeachingGear.deep: 2048,
}


def _configured_model_limit(variable: str, model: object) -> int | None:
    """Read an optional exact-model limit without guessing provider capacity."""
    if not isinstance(model, str) or not model:
        return None
    try:
        limits = json.loads(os.getenv(variable, "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(limits, dict):
        return None
    limit = limits.get(model)
    return limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else None


def teaching_output_limit(
    gear: TeachingGear | str,
    provider: Any,
    context: GenerationContext,
) -> int:
    """Resolve the gear ceiling against configured model output and context limits."""
    ceiling = TEACHING_OUTPUT_CEILINGS[TeachingGear(gear)]
    model = getattr(provider, "model", None)
    model_maximum = _configured_model_limit("AI_TUTOR_MODEL_MAX_OUTPUT_TOKENS", model)
    if model_maximum is not None:
        ceiling = min(ceiling, model_maximum)

    window = _configured_model_limit("AI_TUTOR_MODEL_CONTEXT_WINDOWS", model)
    if window is not None:
        try:
            safety = max(0, int(os.getenv("AI_TUTOR_CONTEXT_SAFETY_TOKENS", "1024")))
        except (TypeError, ValueError):
            safety = 1024
        available = window - context.estimated_input_tokens - safety
        if available < 1:
            raise ValueError("The teaching request leaves no room for a model response within the configured context window.")
        ceiling = min(ceiling, available)
    return ceiling


def conversation_output_limit(
    gear: TeachingGear | str,
    provider: Any,
    context: GenerationContext,
) -> int:
    """Keep ordinary chat bounded while allowing the selected depth to grow."""
    ceiling = CONVERSATION_OUTPUT_CEILINGS[TeachingGear(gear)]
    model = getattr(provider, "model", None)
    model_maximum = _configured_model_limit("AI_TUTOR_MODEL_MAX_OUTPUT_TOKENS", model)
    if model_maximum is not None:
        ceiling = min(ceiling, model_maximum)

    window = _configured_model_limit("AI_TUTOR_MODEL_CONTEXT_WINDOWS", model)
    if window is not None:
        try:
            safety = max(0, int(os.getenv("AI_TUTOR_CONTEXT_SAFETY_TOKENS", "1024")))
        except (TypeError, ValueError):
            safety = 1024
        available = window - context.estimated_input_tokens - safety
        if available < 1:
            raise ValueError("The conversation leaves no room for a response within this model's context window.")
        ceiling = min(ceiling, available)
    return ceiling
