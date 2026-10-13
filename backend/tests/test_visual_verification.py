"""Runtime verification against real headless Chromium and the built verification kit."""
import json
from pathlib import Path

import pytest

from backend.app import visual_verification as verification

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'visuals' / 'cases.json').read_text(encoding='utf-8'))
needs_runtime = pytest.mark.skipif(verification.unavailable_reason() is not None,
                                   reason='Build web visual assets (node web/scripts/build-visual-assets.mjs) and install Playwright Chromium.')


def content(name, **changes):
    value = dict(CASES[name]) | {'htmlComplete': True, 'cssComplete': True, 'generating': False}
    return value | changes


def codes(report, severity=None):
    return {item['code'] for item in report['findings'] if severity is None or item['severity'] == severity}


@needs_runtime
def test_working_interactive_visual_passes_and_controls_respond():
    report = verification.verify_blocking(content('good_slider'))
    assert report['status'] == 'passed', report['findings']
    probes = report['viewports']['desktop']['controls']
    assert probes and probes[0]['outcome'] == 'responsive'


@needs_runtime
def test_webgl_scene_renders_with_local_three_module():
    report = verification.verify_blocking(content('three_scene'))
    assert report['status'] == 'passed', report['findings']
    assert report['viewports']['desktop']['canvasStats'][0]['stddev'] > 5


@needs_runtime
@pytest.mark.parametrize('name,expected', [
    ('reference_error', 'runtime_exception'),
    ('nan_readout', 'invalid_value_displayed'),
    ('overflow', 'horizontal_overflow'),
    ('blank_canvas', 'blank_canvas'),
    ('collapsed_container', 'collapsed_graphic'),
    ('fixed_graphic', 'graphic_clipped'),
    ('infinity_at_minimum', 'invalid_value_after_interaction'),
])
def test_runtime_defects_block_publication(name, expected):
    report = verification.verify_blocking(content(name))
    assert report['status'] == 'failed'
    assert expected in codes(report, 'error')
    feedback = verification.repair_feedback(report)
    assert expected in feedback and len(feedback) <= 2400


@needs_runtime
def test_unwired_control_is_a_repairable_warning_not_a_failure():
    report = verification.verify_blocking(content('unwired'))
    assert report['status'] == 'passed'
    assert 'unresponsive_control' in codes(report, 'warning')


@needs_runtime
def test_blocking_script_times_out_without_hanging_the_verifier():
    report = verification.verify_blocking(content('infinite_loop'), probe=False)
    assert report['status'] == 'failed' and 'script_timeout' in codes(report)
    # The shared browser remains usable for the next candidate.
    assert verification.verify_blocking(content('good_slider', css='.row{gap:13px}'))['status'] == 'passed'


@needs_runtime
def test_network_is_blocked_and_reported():
    # example.com would already be refused by the frame CSP; a CSP-allowed
    # image host proves the verifier's own network block as a second layer.
    html = ['<p>Loading remote data for the chart of current voltage.</p><img alt="remote" src="https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg">']
    report = verification.verify_blocking(content('unwired', html=html), probe=False)
    assert 'network_blocked' in codes(report, 'info')
    assert 'upload.wikimedia.org' in json.dumps(report['findings'])


@needs_runtime
def test_saved_control_values_are_applied_like_the_chat_card():
    controls = [{'id': 'mass', 'label': 'Mass', 'minimum': 1, 'maximum': 10, 'initial': 2}]
    report = verification.verify_blocking(content('good_slider'), controls, {'mass': 7}, probe=False)
    assert 'Force: 70 N' in report['viewports']['desktop']['metrics']['textSample']


def test_reports_are_cached_by_program_digest(monkeypatch):
    digest = verification.content_digest(content('good_slider'))
    assert digest == verification.content_digest(content('good_slider', generating=True))
    assert digest != verification.content_digest(content('good_slider', css='x{}'))
    verification._remember(digest, {'status': 'passed', 'findings': [], 'digest': digest})
    monkeypatch.setattr(verification, '_shared_runtime', lambda: pytest.fail('cached report must not launch a browser'))
    assert verification.verify_blocking(content('good_slider'))['cached'] is True


def test_unavailable_verifier_degrades_without_raising(monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_RUNTIME_VERIFICATION', 'off')
    report = verification.verify_blocking(content('reference_error', css='.uncached{}'))
    assert report['status'] == 'unavailable' and report['reason'] == 'disabled'


def test_summary_excludes_page_content_and_code():
    report = {'status': 'failed', 'digest': 'abc', 'durationMs': 5,
              'findings': [{'severity': 'error', 'code': 'runtime_exception', 'message': 'secret page text'}]}
    assert 'secret' not in json.dumps(verification.summary(report))


@needs_runtime
@pytest.mark.parametrize('name', ['three_default_and_examples_path', 'd3_default'])
def test_common_module_import_idioms_resolve(name):
    # Generated code uses `(await import('three')).default` and the upstream
    # skill's examples/jsm OrbitControls path; both must work in the frame.
    report = verification.verify_blocking(content(name), probe=False)
    assert report['status'] == 'passed', report['findings']


@needs_runtime
def test_colors_hardcoded_for_one_theme_are_flagged_in_the_other():
    report = verification.verify_blocking(content('hardcoded_dark_text'), probe=False)
    contrast = [item for item in report['findings'] if item['code'] == 'low_contrast']
    assert contrast and 'dark theme' in contrast[0]['message']
    assert report['viewports']['desktop']['contrast']['low'] == 0


@needs_runtime
@pytest.mark.parametrize('name', ['overlapping_labels', 'svg_overlapping_labels'])
def test_text_drawn_over_text_is_a_repairable_warning(name):
    report = verification.verify_blocking(content(name), probe=False)
    assert 'overlapping_text' in codes(report, 'warning'), report['findings']


@needs_runtime
def test_wrapped_paragraphs_and_inline_runs_are_not_overlap():
    report = verification.verify_blocking(content('wrapped_inline_text'), probe=False)
    assert 'overlapping_text' not in codes(report)
    assert report['viewports']['desktop']['overlappingText'] == []
