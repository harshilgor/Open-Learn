"""Optional screenshot judge: metered, bounded, never blocking."""
import base64
import io
import json

import pytest
from PIL import Image

from backend.app import visual_judge
from backend.app.openintelligentui import GeneratedVisual, assess_candidate
from backend.app.usage.transport import bounded_image_payload
from backend.app.usage.ledger import UsageError


def png(width=720, height=1600):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (240, 240, 240)).save(buffer, format='PNG')
    return buffer.getvalue()


def candidate():
    return GeneratedVisual(id='one', renderer='open_generative_ui', title='Pendulum', content={
        'generating': False, 'htmlComplete': True, 'html': ['<p id="out">Period: 2.01 s</p>'], 'jsFunctions': 'function f(){}', 'jsExpressions': ['f()']})


@pytest.fixture
def runtime_passes(monkeypatch):
    calls = []

    def fake(content, controls=(), values=None, **kwargs):
        calls.append(kwargs)
        report = {'status': 'passed', 'findings': [], 'digest': 'd', 'durationMs': 1}
        return report | ({'screenshotPng': png()} if kwargs.get('capture') else {})
    monkeypatch.setattr('backend.app.visual_verification.verify_blocking', fake)
    monkeypatch.setattr('backend.app.visual_verification.unavailable_reason', lambda: None)
    return calls


def test_judge_is_off_unless_configured(runtime_passes, monkeypatch):
    monkeypatch.delenv('OPENLEARN_VISUAL_JUDGE_MODEL', raising=False)
    verdict = assess_candidate(candidate(), judge_question='Show a pendulum')
    assert verdict['ok'] and not verdict['polish'] and runtime_passes[0]['capture'] is False


def test_rejected_screenshot_becomes_a_polish_warning_not_a_failure(runtime_passes, monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_JUDGE_MODEL', 'judge/model')
    monkeypatch.setattr(visual_judge, 'judge', lambda image, question: {'acceptable': False, 'score': 2,
                                                                          'problems': ['The string is drawn 15 px long for 1 m.']})
    verdict = assess_candidate(candidate(), judge_question='Show a pendulum')
    assert verdict['ok'] is True and verdict['polish'] is True
    assert 'visual_quality' in verdict['findings'] and 'drawn 15 px long' in verdict['feedback']
    assert verdict['value'].verification['judge'] == {'acceptable': False, 'score': 2}


def test_accepted_screenshot_or_judge_failure_changes_nothing(runtime_passes, monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_JUDGE_MODEL', 'judge/model')
    for judgment in ({'acceptable': True, 'score': 5, 'problems': []}, None):
        monkeypatch.setattr(visual_judge, 'judge', lambda image, question, value=judgment: value)
        verdict = assess_candidate(candidate(), judge_question='Show a pendulum')
        assert verdict['ok'] and not verdict['polish']


def test_no_screenshot_review_without_a_question(runtime_passes, monkeypatch):
    # Repair attempts after the first are not judged: no polish can follow.
    monkeypatch.setenv('OPENLEARN_VISUAL_JUDGE_MODEL', 'judge/model')
    monkeypatch.setattr(visual_judge, 'judge', lambda *args: pytest.fail('must not judge'))
    assert assess_candidate(candidate(), judge_question=None)['ok']


def test_image_billing_counts_an_explicit_bound_not_base64_bytes():
    image = 'data:image/png;base64,' + base64.b64encode(png()).decode()
    payload = {'model': 'm', 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'review'},
                                                                        {'type': 'image_url', 'image_url': {'url': image}}]}]}
    size = bounded_image_payload(payload, 2000)
    assert 2000 < size < 2400
    with pytest.raises(UsageError):
        bounded_image_payload({'messages': [{'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.com/x.png'}}]}]}, 2000)
    with pytest.raises(UsageError):
        bounded_image_payload({'messages': [{'content': [{'type': 'image_url', 'image_url': {'url': image}}] * 3}]}, 2000)


def test_images_stay_refused_outside_the_judge_role(monkeypatch):
    from backend.app.usage import transport
    monkeypatch.setattr(transport.Policy, 'load', classmethod(lambda cls: transport.Policy(mode='enforce', paid=True)))
    monkeypatch.setattr(transport, 'principal_context', type('P', (), {'get': staticmethod(lambda: type('X', (), {'owner_id': 'o'})())}))
    monkeypatch.setattr('backend.app.visual_pricing.approved_visual_tariff', lambda model, role='producer': {
        'usd_per_million_input': 1, 'usd_per_million_output': 1, 'usd_per_million_cache_read': 1})
    image = 'data:image/png;base64,' + base64.b64encode(png(10, 10)).decode()
    payload = {'model': 'paid/model', 'max_tokens': 100, 'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': image}}]}]}
    with pytest.raises(UsageError):
        transport.begin_model(payload, visual_profile=True)
    with pytest.raises(UsageError):
        transport.begin_model(payload, visual_profile=True, visual_role='judge')


def test_judge_call_is_metered_and_settles_with_the_receipt(monkeypatch):
    import httpx
    monkeypatch.setenv('OPENLEARN_VISUAL_JUDGE_MODEL', 'judge/model')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'key')
    begun, settled, sent = [], [], []
    monkeypatch.setattr('backend.app.usage.transport.begin_model', lambda payload, **kwargs: begun.append(kwargs) or 'ticket')
    monkeypatch.setattr('backend.app.usage.transport.finish_model', lambda ticket, receipt: settled.append(receipt))
    answer = {'choices': [{'message': {'content': '```json\n{"acceptable": false, "score": 1, "problems": ["Curve is inverted."]}\n```'}}],
              'usage': {'prompt_tokens': 900, 'completion_tokens': 60, 'cost': 0.0003}}
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: sent.append(kwargs['json']) or httpx.Response(200, json=answer))
    result = visual_judge.judge(png(), 'Show gradient descent')
    assert result == {'acceptable': False, 'score': 1, 'problems': ['Curve is inverted.']}
    assert begun[0] == {'visual_profile': True, 'visual_role': 'judge', 'image_token_bound': visual_judge.IMAGE_TOKEN_BOUND}
    assert settled == [answer['usage']]
    image = Image.open(io.BytesIO(base64.b64decode(sent[0]['messages'][0]['content'][1]['image_url']['url'].split(',', 1)[1])))
    assert image.size == (720, 1200)  # cropped to the bounded size
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: httpx.Response(503, json={}))
    assert visual_judge.judge(png(), 'Show gradient descent') is None and settled[-1] is None


def test_unparseable_judgment_is_ignored():
    assert visual_judge.parse_judgment('looks fine to me') is None
    assert visual_judge.parse_judgment(json.dumps({'acceptable': 'yes'})) is None
