"""Generative visual benchmark against the real local pipeline.

Seeds a lesson per task in the running API's database, requests a visual
through the authenticated ``/v1/lessons/{id}/visual-runs`` endpoint (the same
durable child job, sidecars, provider proxy and metering the chat uses), then
measures the published artifact with headless runtime verification and
task-specific checks. Results are written as JSON and Markdown.

Usage (API and both visual sidecars running, OPENLEARN_VISUAL_ENGINE enabled):
    python backend/scripts/visual_benchmark.py --label baseline
    python backend/scripts/visual_benchmark.py --tasks pendulum edit_pendulum

Model calls are real. Free models cost nothing but are rate limited; a paid
visual model is billed through the normal usage ledger.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.visual_science import HELPERS  # noqa: E402 - shared with in-pipeline science checks


def check(body: str) -> str:
    return 'async () => {' + HELPERS + body + '}'


CONTROL_CHECK = """const missing = PATTERNS.filter(re => !findInput(re)).map(String);
return {pass: missing.length === 0, detail: missing.length ? 'missing controls ' + missing.join(', ') : 'all required controls present',
        labels: fields().map(labelOf).slice(0, 12)};"""


def controls_check(*patterns: str) -> str:
    return check(CONTROL_CHECK.replace('PATTERNS', '[' + ','.join(patterns) + ']'))


TASKS = [
    {'id': 'gradient_descent', 'title': 'Gradient descent',
     'explanation': 'Gradient descent minimizes a loss by repeatedly stepping opposite the gradient. The learning rate scales each step: too small converges slowly, too large overshoots or diverges.',
     'question': 'Show me an interactive visualization of gradient descent on a loss curve where I can change the learning rate and starting point and watch the steps converge or diverge.',
     'checks': {'controls': controls_check(r'/learn|rate|alpha|α|step size/'),
                'steps_change': check("""const lr = findInput(/learn|rate|alpha|α|step size/); if (!lr) return {pass: false, detail: 'no learning-rate control'};
                  const before = text() + graphicState().join(); setValue(lr, lr.max || Number(lr.value) * 4); await sleep(1500);
                  const after = text() + graphicState().join(); return {pass: before !== after, detail: before !== after ? 'output changes with learning rate' : 'no visible change'};""")}},
    {'id': 'pendulum', 'title': 'Simple pendulum',
     'explanation': 'A simple pendulum has period T = 2π√(L/g) for small swings, so a longer string or weaker gravity makes it swing more slowly. Mass does not affect the period.',
     'question': 'Build a working pendulum simulation where I can adjust gravity and length, watch it swing, and see the period change.',
     'checks': {'controls': controls_check(r'/grav|\bg\b/', r'/length|\bl\b/'),
                'period_matches_physics': check(r"""const g = findInput(/grav|\bg\b/), L = findInput(/length|\bl\b/);
                  if (!g || !L) return {pass: false, detail: 'gravity or length control not found'};
                  const results = [];
                  for (const target of [null, 'max']) {
                    if (target) { setValue(g, g.max || Number(g.value) * 2); await sleep(700); }
                    let length = Number(L.value); if (/cm/.test(labelOf(L))) length /= 100;
                    const expected = 2 * Math.PI * Math.sqrt(length / Number(g.value));
                    const shown = readout(/period[^0-9\-]{0,40}?(-?\d+(?:\.\d+)?)\s*(s|sec)/i) || readout(/\bT\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(s)/);
                    if (!shown) return {pass: null, detail: 'no period readout to verify'};
                    results.push({expected: +expected.toFixed(3), shown: shown.value, g: Number(g.value), L: length});
                  }
                  const ok = results.every(r => Math.abs(r.shown - r.expected) / r.expected < 0.08);
                  return {pass: ok, detail: ok ? 'period within 8% of 2π√(L/g)' : 'period disagrees with 2π√(L/g)', measured: results};""")}},
    {'id': 'circuit', 'title': 'Voltage and current',
     'explanation': "Ohm's law says current equals voltage divided by resistance (I = V/R). In a series circuit the resistances add, so the same current flows through every resistor.",
     'question': 'Explain voltage and current with an interactive circuit diagram: a battery and resistors where I can change the voltage and resistance and see the current flow.',
     'checks': {'controls': controls_check(r'/volt|battery|emf|source/', r'/resist|ohm|Ω/'),
                'ohms_law': check(r"""const V = findInput(/volt|battery|emf|source/); const Rs = fields().filter(el => /resist|ohm|Ω|\br\d?\b/.test(labelOf(el)) && el.type !== 'checkbox');
                  if (!V || !Rs.length) return {pass: false, detail: 'voltage or resistance control not found'};
                  await sleep(300); const shown = readout(/current[^0-9\-]{0,40}?(-?\d+(?:\.\d+)?)\s*(mA|A)\b/i) || readout(/\bI\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(mA|A)\b/);
                  if (!shown) return {pass: null, detail: 'no current readout to verify'};
                  const current = shown.unit === 'mA' ? shown.value / 1000 : shown.value; const v = Number(V.value);
                  const values = Rs.map(el => Number(el.value)).filter(Number.isFinite); const series = values.reduce((a, b) => a + b, 0);
                  const parallel = 1 / values.reduce((a, b) => a + 1 / b, 0);
                  const candidates = [v / values[0], v / series, v / parallel];
                  const ok = candidates.some(expected => Math.abs(current - expected) / Math.max(1e-9, Math.abs(expected)) < 0.05);
                  return {pass: ok, detail: ok ? 'current consistent with I = V/R' : 'current inconsistent with I = V/R', measured: {v, resistances: values, current, candidates}};""")}},
    {'id': 'neural_network', 'title': 'Neural network training',
     'explanation': 'A neural network computes outputs layer by layer in the forward pass. Backpropagation then sends error gradients backward through the layers to update each weight.',
     'question': 'Visualize a small neural network showing forward propagation and backpropagation of gradients step by step, with controls to step through the training.',
     'checks': {'structure': check("""const nodes = document.querySelectorAll('svg circle').length; const missing = mentions(['forward', 'back']);
                  const stepper = button(/step|next|play|train|forward|backward|run/);
                  const ok = Boolean((nodes >= 6 || document.querySelector('canvas')) && !missing.length && stepper);
                  return {pass: ok, detail: `nodes=${nodes} missingTerms=${missing.join(',')} stepControl=${!!stepper}`};"""),
                'step_changes_state': check("""const stepper = button(/step|next|play|train|forward|backward|run/); if (!stepper) return {pass: false, detail: 'no step control'};
                  const before = text() + graphicState().join(); stepper.click(); await sleep(1200);
                  return {pass: before !== text() + graphicState().join(), detail: 'state after one step'};""")}},
    {'id': 'binary_search_tree', 'title': 'Binary search tree',
     'explanation': 'A binary search tree keeps smaller keys in the left subtree and larger keys in the right subtree, so search, insertion and deletion follow a single path from the root.',
     'question': 'Create an interactive binary search tree where I can insert and delete numbers and see the tree update, highlighting the path taken.',
     'checks': {'insert_delete': check(r"""const input = [...document.querySelectorAll('input[type=number],input[type=text],input:not([type])')][0];
                  const insert = button(/insert|add/), remove = button(/delete|remove/);
                  if (!input || !insert || !remove) return {pass: false, detail: `input=${!!input} insert=${!!insert} delete=${!!remove}`};
                  const count = () => (text().match(/\b737\b/g) || []).length + [...document.querySelectorAll('svg text')].filter(el => el.textContent.trim() === '737').length;
                  const before = count(); setValue(input, 737); insert.click(); await sleep(1500); const inserted = count();
                  setValue(input, 737); remove.click(); await sleep(1500); const removed = count();
                  const ok = inserted > before && removed < inserted;
                  return {pass: ok, detail: `occurrences before=${before} afterInsert=${inserted} afterDelete=${removed}`};""")}},
    {'id': 'scene_3d', 'title': 'Inner solar system',
     'explanation': 'The inner planets Mercury, Venus, Earth and Mars orbit the Sun on nearly circular paths; planets closer to the Sun move faster and have shorter years.',
     'question': "Make a 3D scene of the inner planets orbiting the sun with camera controls so I can rotate and zoom around it.",
     'code_patterns': {'uses_three': r"import\(['\"]three['\"]\)|\bTHREE\b", 'orbit_controls': r'OrbitControls'},
     'checks': {'scene': check("""const canvas = document.querySelector('canvas'); const missing = mentions(['mercury', 'venus', 'earth', 'mars']);
                  return {pass: !!canvas && missing.length <= 1, detail: `canvas=${!!canvas} missingPlanets=${missing.join(',')}`};""")}},
    {'id': 'transmission_line', 'title': 'Transmission line impedance',
     'explanation': 'A load ZL on a line with characteristic impedance Z0 reflects part of the wave with coefficient Γ = (ZL − Z0)/(ZL + Z0). Along the line the input impedance repeats every half wavelength.',
     'question': 'Interactive transmission line impedance visualization: let me change the load impedance and the line length in wavelengths and show the input impedance and reflection coefficient on a Smith chart or plot.',
     # Load inputs may be absolute (ZL, RL) or normalized to Z0 (r, x), the usual Smith-chart convention.
     'checks': {'controls': controls_check(r'/load|z_?l|zl|r_?l\b|rnorm|norm.*r|resist/', r'/length|λ|wavelength|ℓ/'),
                'reflection_coefficient': check(r"""const zl = findInput(/load.*(re|resist|real)|^z_?l|zl|r_?l\b|rnorm|norm.*r|resist|load/); const x = findInput(/react|imag|x_?l|xl|xnorm|norm.*x/); const z0 = findInput(/z_?0|z0|character/);
                  if (!zl) return {pass: null, detail: 'no load control'}; await sleep(300);
                  const shown = readout(/(?:\|Γ\||Γ|reflection coefficient|\|gamma\|)[^0-9\-]{0,40}?(-?\d+(?:\.\d+)?)()/i);
                  if (!shown) return {pass: null, detail: 'no reflection coefficient readout'};
                  const normalized = /norm/.test(labelOf(zl));
                  const r = Number(zl.value), xi = x ? Number(x.value) : 0, z = normalized ? 1 : (z0 ? Number(z0.value) : 50);
                  const nr = r - z, ni = xi, dr = r + z, di = xi; const mag = Math.hypot(nr, ni) / Math.hypot(dr, di); const re = (nr * dr + ni * di) / (dr * dr + di * di);
                  const ok = Math.abs(Math.abs(shown.value) - mag) < 0.03 || Math.abs(shown.value - re) < 0.03;
                  return {pass: ok, detail: ok ? '|Γ| consistent with (ZL−Z0)/(ZL+Z0)' : 'Γ inconsistent with load', measured: {r, x: xi, z0: z, shown: shown.value, expectedMagnitude: +mag.toFixed(3)}};""")}},
    {'id': 'dashboard', 'title': 'Energy dashboard',
     'explanation': 'Energy use changes by season and by sector: heating dominates winter demand while cooling raises summer demand. Comparing views together reveals which sectors drive the peaks.',
     'question': "Build a dashboard for exploring a city's monthly energy use with coordinated charts: a line chart over the year, a bar chart by sector, and a filter that updates both. Use clearly labeled sample data.",
     # Any filter control counts: select, range slider, checkbox/radio or a non-reset button.
     'checks': {'coordinated': check("""const charts = graphics(); const filter = document.querySelector('select') || document.querySelector('input[type=range]') || [...document.querySelectorAll('input[type=checkbox],input[type=radio],button')].find(el => !/reset/i.test(el.textContent));
                  if (charts.length < 2 || !filter) return {pass: false, detail: `charts=${charts.length} filter=${!!filter}`};
                  const before = graphicState(); if (filter.tagName === 'SELECT') { filter.selectedIndex = (filter.selectedIndex + 1) % filter.options.length; filter.dispatchEvent(new Event('change', {bubbles: true})); filter.dispatchEvent(new Event('input', {bubbles: true})); }
                  else if (filter.type === 'range') { setValue(filter, Number(filter.value) === Number(filter.max) ? filter.min : filter.max); } else filter.click();
                  await sleep(1500); const after = graphicState(); const changed = after.filter((value, index) => value !== before[index]).length;
                  return {pass: changed >= 2, detail: `charts=${charts.length} changedByFilter=${changed}`};"""),
                'sample_data_labeled': check("""return {pass: /sample|illustrative|example|synthetic|hypothetical/.test(lower()), detail: 'data provenance label'};""")}},
    {'id': 'heat_pump', 'title': 'Heat pump cycle',
     'explanation': 'A heat pump moves heat from a cold space to a warm one by circulating refrigerant through an evaporator, compressor, condenser and expansion valve. Its efficiency (COP) falls as the temperature gap grows.',
     'question': 'Show how a heat pump moves heat using an interactive diagram of the refrigeration cycle (compressor, condenser, expansion valve, evaporator) where I can change the outdoor temperature and see the COP.',
     'checks': {'components': check("""const missing = mentions(['compressor', 'condenser', 'expansion', 'evaporator']); return {pass: !missing.length, detail: missing.length ? 'missing ' + missing.join(',') : 'all four stages labeled'};"""),
                'cop_physical': check(r"""const t = findInput(/outdoor|outside|temp|cold/); if (!t) return {pass: false, detail: 'no temperature control'};
                  const values = []; for (const target of [t.min, t.max]) { if (target !== '') { setValue(t, target); await sleep(700); }
                    const cop = readout(/COP[^0-9\-]{0,30}?(-?\d+(?:\.\d+)?)()/i); if (cop) values.push({outdoor: Number(t.value), cop: cop.value}); }
                  if (values.length < 2) return /COP[^0-9]{0,30}N\/?A/i.test(text()) ? {pass: false, detail: 'COP shown as N/A instead of being computed'} : {pass: null, detail: 'COP readout not found'};
                  const ok = values.every(v => v.cop > 1 && v.cop < 15) && values[0].cop !== values[1].cop;
                  return {pass: ok, detail: ok ? 'COP physical and responsive' : 'COP implausible or static', measured: values};""")}},
    {'id': 'simple_chart', 'title': 'Boiling points',
     'explanation': 'At sea level water boils at 100 °C, ethanol at about 78 °C and acetone at about 56 °C; weaker intermolecular forces mean lower boiling points.',
     'question': 'Make a bar chart comparing the boiling points of water, ethanol and acetone.',
     'checks': {'labels': check("""return {pass: graphics().length >= 1, detail: `graphics=${graphics().length}`};""")}},
]
TASKS.append({'id': 'no_visual', 'title': 'Acknowledgement', 'expect': 'skipped',
              'explanation': 'You are welcome. Momentum is mass times velocity, and it is conserved in isolated systems.',
              'question': 'Thanks, that makes sense now!', 'checks': {}})
EDIT_TASK = {'id': 'edit_pendulum', 'base': 'pendulum', 'title': 'Pendulum with damping',
             'explanation': 'Air resistance removes energy each swing, so the amplitude decays exponentially while the period stays nearly the same for light damping.',
             'question': 'Now add air resistance to this pendulum simulation with a slider for the damping coefficient, and keep the gravity and length controls working.',
             'checks': {'controls': controls_check(r'/damp|air|drag|friction|resist/', r'/grav|\bg\b/', r'/length|\bl\b/')}}


def seed(store, owner, task, session_id=None, prior=None):
    """A session/lesson as the tutor would have committed it, plus its journey turn."""
    from sqlalchemy import text
    from backend.app.models import utc_now
    from backend.app.session_models import LearningSession, LessonArtifact, LessonBlock
    from backend.app.workflow_store import WorkflowStore
    now = utc_now()
    lesson_id = 'bench_lesson_' + uuid.uuid4().hex[:12]
    if session_id is None:
        session_id = 'bench_session_' + uuid.uuid4().hex[:12]
        with store.transaction() as conn:
            conn.execute(text("INSERT OR IGNORE INTO topic_scopes(id,payload) VALUES('bench-scope','{}')"))
            conn.execute(text("INSERT OR IGNORE INTO graph_versions(id,scope_id,payload) VALUES('bench-graph','bench-scope','{}')"))
        store.save_session(LearningSession(id=session_id, learner_id=owner, graph_id='bench-graph', created_at=now, updated_at=now, title=task['title'][:120]))
    artifact = LessonArtifact(id=lesson_id, session_id=session_id, concept_id='bench-' + task['id'], gear='Quick', title=task['title'],
                              blocks=[LessonBlock(id='block_' + lesson_id, kind='explanation', body=task['explanation'], order=0)])
    store.save_artifact(artifact)
    records = WorkflowStore(store)
    journey_id = 'journey_' + session_id
    turn = {'question': task['question'], 'lesson': artifact.model_dump(mode='json', by_alias=True)}
    with store.transaction() as conn:
        if prior is None:
            records.put(conn, owner, 'journey', {'id': journey_id, 'sessionId': session_id, 'turns': [turn]}, session_id)
        else:
            journey = records.read(owner, journey_id, 'journey', conn)
            for value in journey['turns']:
                if value['lesson']['id'] == prior:
                    value['lesson'] = json.loads(conn.execute(text('SELECT payload FROM lesson_artifacts WHERE id=:id'), {'id': prior}).scalar_one())
            journey['turns'].append(turn)
            records.put(conn, owner, 'journey', journey, session_id, expected=journey['revision'])
    return session_id, lesson_id


def usage(database: Path, job_id: str):
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT component, model, cost_nano, payload FROM usage_events WHERE root_id=?', ('ogui:' + job_id,)).fetchall()
    calls = [{'component': r[0], 'model': r[1], 'costNano': r[2], **json.loads(r[3] or '{}')} for r in rows]
    model = [c for c in calls if c['component'] == 'model']
    return {'modelCalls': len(model), 'routerCalls': len(calls) - len(model),
            'inputTokens': sum(c.get('input_tokens', 0) for c in model), 'outputTokens': sum(c.get('output_tokens', 0) for c in model),
            'maxOutputTokensSingleCall': max((c.get('output_tokens', 0) for c in model), default=0),
            'costUsd': round(sum(c['costNano'] or 0 for c in calls) / 1e9, 6)}


def run_task(client, store, database, owner, task, out_dir, timeout, session_id=None, prior=None):
    session_id, lesson_id = seed(store, owner, task, session_id, prior)
    started = time.monotonic()
    response = client.post(f'/v1/lessons/{lesson_id}/visual-runs', json={'question': task['question']},
                           headers={'Idempotency-Key': uuid.uuid4().hex})
    response.raise_for_status()
    run_id = response.json()['id']
    first_preview = plan_at = first_snapshot = None
    phases, timeline, run = [], [], None
    while time.monotonic() - started < timeout:
        runs = client.get(f'/v1/lessons/{lesson_id}/visual-runs').json()['runs']
        run = next(value for value in runs if value['id'] == run_id)
        if not phases or phases[-1][0] != run['phase']:
            phases.append((run['phase'], round(time.monotonic() - started, 1)))
        progress = run.get('progress')
        if progress and (not timeline or timeline[-1][1:] != [progress['attempt'], progress['stage']]):
            timeline.append([round(time.monotonic() - started, 1), progress['attempt'], progress['stage']])
        if first_snapshot is None and run.get('snapshots'):
            first_snapshot = round(time.monotonic() - started, 1)
        if first_preview is None and any((s.get('content') or {}).get('html') for s in run.get('snapshots', [])):
            first_preview = round(time.monotonic() - started, 1)
        if plan_at is None and run.get('plan'):
            plan_at = round(time.monotonic() - started, 1)
        if run['phase'] in {'completed', 'skipped', 'failed', 'interrupted', 'cancelled'}:
            break
        time.sleep(1)
    total = round(time.monotonic() - started, 1)
    job_id = run.get('jobId') if run else None
    result = {'task': task['id'], 'expect': task.get('expect', 'visual'), 'runId': run_id, 'lessonId': lesson_id, 'sessionId': session_id,
              'phase': run['phase'] if run else 'timeout', 'errorCode': (run or {}).get('errorCode'),
              'phases': phases, 'progress': timeline, 'firstSnapshotSeconds': first_snapshot,
              'firstPreviewSeconds': first_preview, 'planSeconds': plan_at, 'totalSeconds': total,
              'usage': usage(database, job_id) if job_id else None, 'artifacts': []}
    for ref in (run or {}).get('artifactRefs', []):
        spec = client.get(f'/v1/generated-visuals/{ref["id"]}').json()
        result['artifacts'].append(measure_artifact(spec, task, out_dir))
    return result


def measure_artifact(spec, task, out_dir):
    """Runtime verification plus task checks for one published artifact."""
    from backend.app.visual_verification import verify_blocking
    artifact = {'id': spec['id'], 'renderer': spec['renderer'], 'controls': [c['label'] for c in spec.get('controls', [])],
                'lineage': spec.get('lineage')}
    if spec['renderer'] != 'open_generative_ui':
        return artifact
    content = spec['content']
    code = (content.get('jsFunctions') or '') + '\n'.join(content.get('jsExpressions') or [])
    artifact['size'] = {'css': len(content.get('css') or ''), 'html': len(''.join(content.get('html') or [])), 'js': len(code)}
    artifact['libraries'] = sorted(name for name in ('three', 'd3', 'chart.js', 'gsap', 'leaflet')
                                   if re.search(rf"['\"]{re.escape(name)}['\"]", code) or (name == 'three' and 'THREE' in code))
    artifact['codePatterns'] = {key: bool(re.search(pattern, code)) for key, pattern in task.get('code_patterns', {}).items()}
    verify_started = time.monotonic()
    report = verify_blocking(content, spec.get('controls', []), spec.get('controlValues', {}),
                             screenshot_dir=out_dir / 'screens' / task['id'], checks=task.get('checks'))
    artifact['verificationSeconds'] = round(time.monotonic() - verify_started, 1)
    desktop = (report.get('viewports') or {}).get('desktop') or {}
    artifact['verification'] = {'status': report['status'], 'reason': report.get('reason'),
                                'findings': [{k: f[k] for k in ('severity', 'code', 'message')} for f in report['findings']],
                                'controls': desktop.get('controls'), 'frameHeight': desktop.get('frameHeight'),
                                'resources': desktop.get('resources'), 'initMs': desktop.get('initMs')}
    artifact['checks'] = desktop.get('checks', {})
    return artifact


def rescore(directory: Path, database: Path):
    """Re-measure stored artifacts with the current verifier and checks (no generation)."""
    data = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    tasks = {task['id']: task for task in TASKS + [EDIT_TASK]}
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as conn:
        for result in data['results']:
            for index, artifact in enumerate(result.get('artifacts', [])):
                row = conn.execute("SELECT payload FROM practice_records WHERE id=? AND kind='generated_visual'", (artifact['id'],)).fetchone()
                if row:
                    result['artifacts'][index] = measure_artifact(json.loads(row[0])['spec'], tasks[result['task']], directory)
    (directory / 'results-rescored.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    (directory / 'report.md').write_text(markdown(data['label'] + ' (rescored)', (data.get('capability') or {}).get('model'), data['results']),
                                         encoding='utf-8')
    print(directory / 'report.md')


def score(result):
    """Objective per-task outcome used in the summary table."""
    artifacts = [a for a in result['artifacts'] if a['renderer'] == 'open_generative_ui']
    if result.get('expect') == 'skipped':
        calls = (result.get('usage') or {}).get('modelCalls')
        return 'passed' if result['phase'] in {'skipped', 'completed'} and not result['artifacts'] and calls == 0 else 'unnecessary_model_call'
    if result['phase'] != 'completed' or not result['artifacts']:
        return 'not_published'
    if not artifacts:
        return 'published_table'
    best = artifacts[-1]
    status = best['verification']['status']
    checks = [value.get('pass') for value in best.get('checks', {}).values() if isinstance(value, dict)]
    patterns = list(best.get('codePatterns', {}).values())
    if status == 'failed':
        return 'runtime_failed'
    if any(value is False for value in checks + patterns):
        return 'task_check_failed'
    if result['task'] == EDIT_TASK['id'] and not best.get('lineage'):
        return 'new_visual_not_edit'
    return 'passed'


def markdown(label, model, results):
    lines = [f'# Visual benchmark: {label}', '', f'Model: `{model}`. Generated {time.strftime("%Y-%m-%d %H:%M")}.', '',
             '| Task | Outcome | Phase / error | First preview (s) | Total (s) | Model calls | Tokens in/out | Runtime verification | Task checks |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for result in results:
        usage = result.get('usage') or {}
        artifact = next((a for a in reversed(result['artifacts']) if a['renderer'] == 'open_generative_ui'), None)
        verification = '-'
        checks = '-'
        if artifact:
            codes = [f['code'] for f in artifact['verification']['findings'] if f['severity'] in {'error', 'warning'}]
            verification = artifact['verification']['status'] + (f" ({', '.join(sorted(set(codes)))})" if codes else '')
            checks = ', '.join(f"{name}={'pass' if value.get('pass') else ('n/a' if value.get('pass') is None else 'FAIL')}"
                               for name, value in artifact.get('checks', {}).items() if isinstance(value, dict)) or '-'
            if artifact.get('codePatterns'):
                checks += ', ' + ', '.join(f"{k}={'yes' if v else 'NO'}" for k, v in artifact['codePatterns'].items())
        lines.append(f"| {result['task']} | {score(result)} | {result['phase']}{' / ' + result['errorCode'] if result.get('errorCode') else ''} | "
                     f"{result.get('firstPreviewSeconds') or '-'} | {result['totalSeconds']} | {usage.get('modelCalls', '-')} | "
                     f"{usage.get('inputTokens', '-')}/{usage.get('outputTokens', '-')} | {verification} | {checks} |")
    outcomes = [score(r) for r in results]
    published = [r for r in results if r['phase'] == 'completed' and r['artifacts']]
    lines += ['', f"Published: {len(published)}/{len(results)}. Passed all objective checks: {outcomes.count('passed')}/{len(results)}.",
              f"Median total seconds (published): {sorted(r['totalSeconds'] for r in published)[len(published) // 2] if published else '-'}."]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--database', default=str(ROOT / 'backend' / 'data' / 'forma.db'))
    parser.add_argument('--owner', default='local')
    parser.add_argument('--label', default='run')
    parser.add_argument('--tasks', nargs='*')
    parser.add_argument('--timeout', type=float, default=720)
    parser.add_argument('--out', default=str(ROOT / 'work' / 'visual-benchmark'))
    parser.add_argument('--rescore', help='Results directory to re-measure from stored artifacts (no generation).')
    args = parser.parse_args()
    if args.rescore:
        rescore(Path(args.rescore), Path(args.database).resolve())
        return
    from backend.app.storage import Store
    database = Path(args.database).resolve()
    store = Store(database)
    out_dir = Path(args.out) / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(args.tasks or [task['id'] for task in TASKS] + [EDIT_TASK['id']])
    client = httpx.Client(base_url=args.api, timeout=60, trust_env=False, headers={'X-Dev-Learner-Id': args.owner})
    capability = client.get('/v1/visual-pipeline/capability').json()
    if not capability.get('enabled') or not capability.get('configured'):
        raise SystemExit(f'Visual pipeline unavailable: {capability}')
    results, sessions = [], {}
    for task in TASKS + [EDIT_TASK]:
        if task['id'] not in wanted:
            continue
        if task is EDIT_TASK:
            base = sessions.get(EDIT_TASK['base'])
            if base is None:
                base_task = next(t for t in TASKS if t['id'] == EDIT_TASK['base'])
                print(f'[{time.strftime("%H:%M:%S")}] {base_task["id"]} (edit base) ...', flush=True)
                base_result = run_task(client, store, database, args.owner, base_task, out_dir, args.timeout)
                base = (base_result['sessionId'], base_result['lessonId'], base_result)
            if base[2]['phase'] != 'completed' or not base[2]['artifacts']:
                results.append({'task': task['id'], 'phase': 'skipped_base_failed', 'totalSeconds': 0, 'artifacts': [], 'usage': None})
                continue
            print(f'[{time.strftime("%H:%M:%S")}] {task["id"]} ...', flush=True)
            result = run_task(client, store, database, args.owner, task, out_dir, args.timeout, session_id=base[0], prior=base[1])
            result['baseArtifacts'] = base[2]['artifacts']
        else:
            print(f'[{time.strftime("%H:%M:%S")}] {task["id"]} ...', flush=True)
            result = run_task(client, store, database, args.owner, task, out_dir, args.timeout)
            sessions[task['id']] = (result['sessionId'], result['lessonId'], result)
        print(f'    -> {score(result)} phase={result["phase"]} error={result.get("errorCode")} total={result["totalSeconds"]}s usage={result.get("usage")}', flush=True)
        results.append(result)
        (out_dir / 'results.json').write_text(json.dumps({'label': args.label, 'capability': capability, 'results': results}, indent=2), encoding='utf-8')
    (out_dir / 'report.md').write_text(markdown(args.label, capability.get('model'), results), encoding='utf-8')
    print(out_dir / 'report.md')


if __name__ == '__main__':
    main()
