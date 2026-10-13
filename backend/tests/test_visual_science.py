"""Topic science checks against real headless Chromium."""
import pytest

from backend.app import visual_science as science
from backend.app import visual_verification as verification

needs_runtime = pytest.mark.skipif(verification.unavailable_reason() is not None,
                                   reason='Build web visual assets and install Playwright Chromium.')


def visual(controls, readout_js, extra_html=''):
    """Labeled range inputs plus a status line recomputed on every input."""
    inputs = ''.join(f'<label for="{cid}">{label}</label><input id="{cid}" type="range" min="{lo}" max="{hi}" value="{value}" step="any">'
                     for cid, label, lo, hi, value in controls)
    reads = ''.join(f"const {cid}=document.getElementById('{cid}').valueAsNumber;" for cid, *_ in controls)
    return {'html': [f'<h3>Explorer</h3>{inputs}<p id="readout" role="status"></p>{extra_html}'],
            'jsFunctions': f"function update(){{{reads}document.getElementById('readout').textContent={readout_js};}}\n"
                           "function setup(){document.querySelectorAll('input').forEach(i=>i.addEventListener('input',update));update();}",
            'jsExpressions': ['setup()'], 'htmlComplete': True, 'cssComplete': True, 'generating': False}


PENDULUM = [('gravity', 'Gravity (m/s²)', 1, 25, 9.8), ('length', 'Length (m)', 0.1, 5, 1)]
OHM = [('voltage', 'Voltage (V)', 1, 12, 6), ('resistance', 'Resistance (Ω)', 10, 1000, 100)]
PROJECTILE = [('speed', 'Launch speed (m/s)', 1, 50, 20), ('angle', 'Launch angle (°)', 5, 85, 30)]


def outcome(content, topic):
    report = verification.verify_blocking(content, probe=False, science=[topic])
    return report, report['viewports']['desktop']['science'][topic]


@needs_runtime
@pytest.mark.parametrize('topic,controls,correct,wrong', [
    ('pendulum', PENDULUM, "'Period: '+(2*Math.PI*Math.sqrt(length/gravity)).toFixed(3)+' s'",
     "'Period: '+(2*Math.PI*Math.sqrt(gravity/length)).toFixed(3)+' s'"),
    ('ohms_law', OHM, "'Current: '+(voltage/resistance).toFixed(4)+' A'", "'Current: '+(voltage*resistance/1000).toFixed(4)+' A'"),
    ('projectile', PROJECTILE, "'Range: '+(speed*speed*Math.sin(2*angle*Math.PI/180)/9.81).toFixed(2)+' m'",
     "'Range: '+(speed*speed*Math.sin(angle*Math.PI/180)/9.81).toFixed(2)+' m'"),
])
def test_correct_physics_passes_and_wrong_physics_is_an_error(topic, controls, correct, wrong):
    report, result = outcome(visual(controls, correct), topic)
    assert result['status'] == 'pass', result
    assert 'science_mismatch' not in {item['code'] for item in report['findings']}
    report, result = outcome(visual(controls, wrong), topic)
    assert result['status'] == 'fail', result
    mismatch = [item for item in report['findings'] if item['code'] == 'science_mismatch']
    assert mismatch and mismatch[0]['severity'] == 'error' and report['status'] == 'failed'


@needs_runtime
def test_worked_examples_in_text_do_not_hide_a_wrong_live_readout():
    # The explanatory example is right for the starting values only; moving
    # gravity to its maximum exposes the wrong live readout.
    example = '<p>For example, with g = 9.8 and L = 1, Period: 2.007 s.</p>'
    _, result = outcome(visual(PENDULUM, "'Period: '+(2*Math.PI*Math.sqrt(gravity/length)).toFixed(3)+' s'", example), 'pendulum')
    assert result['status'] == 'fail'


@needs_runtime
def test_formula_text_is_not_read_as_a_value():
    controls = [('rl', 'Load resistance R_L (Ω)', 1, 500, 100)]
    formula = '<p>Γ_in = Γ_L · e^(−j2βl); VSWR = (1+|Γ|)/(1−|Γ|)</p>'
    _, result = outcome(visual(controls, "'|Γ| = '+(Math.abs((rl-50)/(rl+50))).toFixed(3)", formula), 'reflection_coefficient')
    assert result['status'] == 'pass', result


@needs_runtime
def test_neuron_activation_values_must_match_the_named_function():
    controls = [('w', 'Weight w', -2, 2, 0.5), ('x', 'Input x', -2, 2, 1)]
    right = "'Sigmoid neuron: z = '+(w*x).toFixed(3)+', σ(z) = '+(1/(1+Math.exp(-w*x))).toFixed(3)"
    wrong = "'Sigmoid neuron: z = '+(w*x).toFixed(3)+', σ(z) = '+(w*x/2).toFixed(3)"
    assert outcome(visual(controls, right), 'neuron_activation')[1]['status'] == 'pass'
    assert outcome(visual(controls, wrong), 'neuron_activation')[1]['status'] == 'fail'


@needs_runtime
def test_unmeasurable_visuals_produce_no_finding():
    report, result = outcome(visual(PENDULUM, "'The pendulum swings.'"), 'pendulum')
    assert result['status'] == 'unmeasured' and report['status'] == 'passed'


@needs_runtime
def test_empty_value_displays_are_a_repairable_warning():
    content = visual(OHM, "'Current: '+(voltage/resistance).toFixed(4)+' A'", '<div id="powerOut" aria-live="polite"></div><div id="errorMsg" aria-live="polite"></div>')
    report = verification.verify_blocking(content, probe=False)
    empty = [item for item in report['findings'] if item['code'] == 'empty_readout']
    assert empty and empty[0]['severity'] == 'warning' and 'powerOut' in empty[0]['message'] and 'errorMsg' not in empty[0]['message']


def test_topics_route_from_the_request():
    assert science.topics_for('Build a working pendulum simulation') == ['pendulum']
    assert 'ohms_law' in science.topics_for('Explain voltage and current with an interactive circuit')
    assert 'projectile' in science.topics_for('Show projectile motion for a ball launched at an angle')
    assert science.topics_for('Thanks, that makes sense now!') == []
    assert verification.content_digest({'html': ['x']}, science=['pendulum']) != verification.content_digest({'html': ['x']})
