"""Optional screenshot review of a runtime-verified visual.

DOM and pixel checks cannot see whether a drawing depicts its concept: an
inverted loss curve, a 1 m pendulum drawn 20 px long, or a circuit that is not
a closed loop all pass them. A multimodal model reviewing the rendered
screenshot catches these. Measured against human-labeled screenshots, paid
judges flagged every badly drawn visual with accurate reasons but were
stricter than a lenient human reviewer, so a judgment never blocks
publication: its problems become a repairable warning for the single polish
attempt.

Disabled unless OPENLEARN_VISUAL_JUDGE_MODEL names a model with a reviewed
tariff in OPENLEARN_VISUAL_MODEL_TARIFFS. Every call is metered; any failure
returns None (no judgment) and never affects the visual.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re

import httpx

LOG = logging.getLogger(__name__)
# The screenshot is cropped to 720x1200 so any provider's image charge stays
# below this reservation bound (about 1,150 tokens at 750 pixels per token).
IMAGE_TOKEN_BOUND = 2000
MAX_JUDGE_OUTPUT_TOKENS = 1500
RUBRIC = ('You review an interactive educational visual (a static screenshot) before a student sees it. The student asked: "{question}".\n'
          'Judge only what is drawn: does the drawing correctly and recognizably depict the concept (correct shapes, orientation, '
          'proportions and scale, readable non-overlapping labels, connected diagrams)? Controls and numbers being present is not enough.\n'
          'Reply with JSON only: {{"acceptable": true|false, "score": 1-5, "problems": ["specific, fixable problem", ...]}}')


def judge_model() -> str | None:
    model = os.getenv('OPENLEARN_VISUAL_JUDGE_MODEL', '').strip()
    return model or None


def prepared_screenshot(png: bytes) -> bytes:
    """Crop to the bounded size the reservation covers."""
    from PIL import Image
    image = Image.open(io.BytesIO(png))
    if image.width > 720 or image.height > 1200:
        image = image.crop((0, 0, min(image.width, 720), min(image.height, 1200)))
    buffer = io.BytesIO()
    image.convert('RGB').save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def parse_judgment(text: str) -> dict | None:
    match = re.search(r'\{[\s\S]*\}', text or '')
    try:
        value = json.loads(match.group(0)) if match else None
    except ValueError:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('acceptable'), bool):
        return None
    problems = [str(item)[:240] for item in value.get('problems') or [] if isinstance(item, str) and item.strip()][:4]
    score = value.get('score') if isinstance(value.get('score'), (int, float)) and not isinstance(value.get('score'), bool) else None
    return {'acceptable': value['acceptable'], 'score': score, 'problems': problems}


def judge(png: bytes, question: str, timeout: float = 60.0) -> dict | None:
    """Review a screenshot. Returns acceptable/score/problems, or None."""
    model = judge_model()
    if not model or not png:
        return None
    from .usage.transport import begin_model, finish_model, UsageError
    image = 'data:image/png;base64,' + base64.b64encode(prepared_screenshot(png)).decode()
    payload = {'model': model, 'max_tokens': MAX_JUDGE_OUTPUT_TOKENS, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': RUBRIC.format(question=question[:1000])},
        {'type': 'image_url', 'image_url': {'url': image}}]}]}
    try:
        ticket = begin_model(payload, visual_profile=True, visual_role='judge', image_token_bound=IMAGE_TOKEN_BOUND)
    except UsageError as error:
        LOG.warning('Visual judge not metered (%s); skipped', error.code if hasattr(error, 'code') else type(error).__name__)
        return None
    receipt = None
    try:
        response = httpx.post('https://openrouter.ai/api/v1/chat/completions', json=payload, timeout=timeout, trust_env=False,
                              headers={'Authorization': 'Bearer ' + os.environ['OPENROUTER_API_KEY']})
        if response.status_code != 200:
            LOG.warning('Visual judge provider HTTP status: %s', response.status_code)
            return None
        data = response.json()
        receipt = data.get('usage') if isinstance(data.get('usage'), dict) else None
        choices = data.get('choices') or []
        text = (choices[0].get('message') or {}).get('content') if choices else ''
        return parse_judgment(text if isinstance(text, str) else '')
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        LOG.warning('Visual judge failed: %s', type(error).__name__)
        return None
    finally:
        finish_model(ticket, receipt)
