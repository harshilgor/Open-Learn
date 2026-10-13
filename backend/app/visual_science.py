"""Topic-routed scientific checks run inside a rendered visual.

Runtime verification proves a visual works; these checks test that what it
shows agrees with the governing formula for the product's priority topics:
the approved simulations of the original visual system (gradient descent,
projectile motion, Ohm's law), the reviewed neural-network domain pack
(weighted neuron and activation), and topics where generated visuals were
measured getting physics wrong (pendulum, transmission-line reflection).

Each check reads the visual's own labeled controls and readouts. It returns
``fail`` only when it can measure unambiguously (controls identified, readout
parsed) and the value is outside a generous tolerance; otherwise ``pass`` or
``unmeasured``. Checks only read and set the visual's own inputs.
"""
from __future__ import annotations

import re

# Shared by these checks and backend/scripts/visual_benchmark.py.
HELPERS = r"""
const text = () => document.body.innerText;
const lower = () => text().toLowerCase();
const fields = () => [...document.querySelectorAll('input,select')];
const labelOf = el => ((el.labels && el.labels[0] && el.labels[0].textContent) || el.getAttribute('aria-label') || el.id || el.name || '').toLowerCase();
const findInput = re => fields().find(el => re.test(labelOf(el)));
const readout = re => { const m = text().match(re); return m ? {value: Number(m[1]), unit: (m[2] || '').trim(), raw: m[0].slice(0, 80)} : null; };
// Every labeled value: visuals mix worked examples ("so Γ = 0") into their
// text, so a check passes when any labeled value matches and fails only when
// none does.
const readouts = (...patterns) => patterns.flatMap(re => [...text().matchAll(new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g'))]
  .map(m => ({value: Number(m[1]), unit: (m[2] || '').trim(), raw: m[0].slice(0, 80)}))).filter(item => Number.isFinite(item.value)).slice(0, 12);
const closest = (items, expected, scale = item => item.value) => items.slice().sort((a, b) => Math.abs(scale(a) - expected) - Math.abs(scale(b) - expected))[0];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const setValue = (el, value) => { el.value = String(value); el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); };
const button = re => [...document.querySelectorAll('button,[role=button]')].find(el => re.test((el.textContent + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase()));
const graphics = () => [...document.querySelectorAll('canvas,svg')].filter(el => { const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 40; });
const graphicState = () => graphics().map(el => { if (el.tagName === 'svg') return el.innerHTML.length + el.innerHTML.slice(-300);
  try { return el.toDataURL().slice(-400); } catch (error) { return 'opaque'; } });
const mentions = words => words.filter(word => !lower().includes(word));
const near = (shown, expected, tolerance) => Math.abs(shown - expected) <= tolerance * Math.max(Math.abs(expected), 1e-9);
const numeric = el => el && el.value !== '' && Number.isFinite(Number(el.value));
"""


def script(body: str) -> str:
    return 'async () => {' + HELPERS + body + '}'


PENDULUM = script(r"""
const g = findInput(/grav|\bg\b/), L = findInput(/length|\bl\b/);
if (!numeric(g) || !numeric(L)) return {status: 'unmeasured', detail: 'gravity or length control not found'};
const amplitude = findInput(/angle|amplitude|θ|theta/);
if (amplitude && Math.abs(Number(amplitude.value)) > 30) return {status: 'unmeasured', detail: 'large amplitude: small-angle period does not apply'};
const results = [];
for (const target of [null, 'max']) {
  if (target) { setValue(g, g.max || Number(g.value) * 2); await sleep(600); }
  let length = Number(L.value); if (/\bcm\b|centimet/.test(labelOf(L))) length /= 100;
  if (!(length > 0) || !(Number(g.value) > 0)) continue;
  const expected = 2 * Math.PI * Math.sqrt(length / Number(g.value));
  const all = readouts(/period(?:\s*\([^)]*\))?(?:\s*T)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(s|sec)\b/i, /\bT\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(s)\b/);
  if (!all.length) return {status: 'unmeasured', detail: 'no period readout'};
  const shown = closest(all, expected);
  results.push({g: Number(g.value), L: length, expected: +expected.toFixed(3), shown: shown.value});
}
if (!results.length) return {status: 'unmeasured', detail: 'controls at zero'};
const ok = results.every(r => near(r.shown, r.expected, 0.1));
return {status: ok ? 'pass' : 'fail', detail: ok ? 'period matches 2π√(L/g)' : 'displayed period disagrees with T = 2π√(L/g)', measured: results};
""")

OHMS_LAW = script(r"""
const V = findInput(/volt|battery|emf|source/);
const Rs = fields().filter(el => /resist|ohm|Ω|\br\d?\b/.test(labelOf(el)) && el.type !== 'checkbox' && numeric(el));
if (!numeric(V) || !Rs.length) return {status: 'unmeasured', detail: 'voltage or resistance control not found'};
await sleep(300);
const all = readouts(/current(?:\s*\([^)]*\))?(?:\s*I)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(mA|A)\b/i, /\bI\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(mA|A)\b/);
if (!all.length) return {status: 'unmeasured', detail: 'no current readout'};
const amps = item => item.unit === 'mA' ? item.value / 1000 : item.value, v = Number(V.value);
const values = Rs.map(el => Number(el.value) * (/k\s*ω|kΩ|kohm/i.test(labelOf(el)) ? 1000 : 1)).filter(r => r > 0);
if (!values.length) return {status: 'unmeasured', detail: 'zero resistance'};
const series = values.reduce((a, b) => a + b, 0), parallel = 1 / values.reduce((a, b) => a + 1 / b, 0);
const candidates = [v / values[0], v / series, v / parallel];
const ok = all.some(item => candidates.some(expected => near(amps(item), expected, 0.05)));
const current = amps(closest(all, candidates[0], amps));
return {status: ok ? 'pass' : 'fail', detail: ok ? 'current consistent with I = V/R' : 'displayed current disagrees with I = V/R for the shown voltage and resistance',
        measured: {v, resistances: values, current, candidates: candidates.map(c => +c.toFixed(4))}};
""")

PROJECTILE = script(r"""
const v = findInput(/speed|veloc|\bv0?\b|launch/), angle = findInput(/angle|θ|theta/);
if (!numeric(v) || !numeric(angle)) return {status: 'unmeasured', detail: 'speed or angle control not found'};
if (/air|drag|resist/.test(lower()) && fields().some(el => el.type === 'checkbox' && el.checked && /air|drag/.test(labelOf(el))))
  return {status: 'unmeasured', detail: 'air resistance enabled'};
const gInput = findInput(/grav|\bg\b/), hInput = findInput(/height|h0|initial h/);
const g = numeric(gInput) ? Number(gInput.value) : 9.81, h = numeric(hInput) ? Number(hInput.value) : 0;
await sleep(400);
const speed = Number(v.value), theta = Number(angle.value) * Math.PI / 180;
if (!(speed > 0) || !(g > 0)) return {status: 'unmeasured', detail: 'zero speed or gravity'};
const vy = speed * Math.sin(theta), vx = speed * Math.cos(theta);
const time = (vy + Math.sqrt(vy * vy + 2 * g * h)) / g;
const expected = {range: vx * time, height: h + vy * vy / (2 * g), time};
const shown = {range: readouts(/(?:range|distance)(?:\s*\([^)]*\))?(?:\s*R)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(m)\b/i),
               height: readouts(/(?:max(?:imum)?\.? height|peak height|apex)(?:\s*\([^)]*\))?(?:\s*H)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(m)\b/i),
               time: readouts(/(?:time of flight|flight time|air ?time|total time)(?:\s*\([^)]*\))?(?:\s*T)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)\s*(s)\b/i)};
const compared = Object.keys(shown).filter(key => shown[key].length).map(key => ({quantity: key, shown: closest(shown[key], expected[key]).value, expected: +expected[key].toFixed(3)}));
if (!compared.length) return {status: 'unmeasured', detail: 'no range, height or flight-time readout'};
const ok = compared.every(item => near(item.shown, item.expected, 0.06));
return {status: ok ? 'pass' : 'fail', detail: ok ? 'readouts match ideal projectile motion' : 'readouts disagree with ideal projectile motion (no drag)', measured: {speed, angle: Number(angle.value), g, h, compared}};
""")

REFLECTION = script(r"""
const zl = findInput(/load.*(re|resist|real)|^z_?l|zl|r_?l\b|rnorm|norm.*r|resist|load/);
if (!numeric(zl)) return {status: 'unmeasured', detail: 'no load control'};
const x = findInput(/react|imag|x_?l|xl|xnorm|norm.*x/), z0 = findInput(/z_?0|z0|character/);
await sleep(300);
const all = readouts(/(?:\|Γ(?:_?L)?\||\|gamma\||Γ(?:_?L)?|reflection coefficient)(?:\s*\([^)]*\))?\s*[=≈:]\s*(-?\d+(?:\.\d+)?)()/i);
if (!all.length) return {status: 'unmeasured', detail: 'no reflection coefficient readout'};
const normalized = /norm/.test(labelOf(zl));
const r = Number(zl.value), xi = numeric(x) ? Number(x.value) : 0, z = normalized ? 1 : (numeric(z0) ? Number(z0.value) : 50);
const mag = Math.hypot(r - z, xi) / Math.hypot(r + z, xi), re = ((r - z) * (r + z) + xi * xi) / ((r + z) ** 2 + xi * xi);
const ok = all.some(item => Math.abs(Math.abs(item.value) - mag) < 0.03 || Math.abs(item.value - re) < 0.03);
const shown = closest(all, mag, item => Math.abs(item.value));
return {status: ok ? 'pass' : 'fail', detail: ok ? '|Γ| matches (ZL − Z0)/(ZL + Z0)' : 'reflection coefficient disagrees with Γ = (ZL − Z0)/(ZL + Z0)',
        measured: {r, x: xi, z0: z, shown: shown.value, expectedMagnitude: +mag.toFixed(3)}};
""")

NEURON = script(r"""
const t = text();
const sigmoid = /sigmoid|σ\s*\(|logistic/i.test(t), relu = /relu/i.test(t);
if (!sigmoid && !relu) return {status: 'unmeasured', detail: 'no named activation'};
const pairs = [];
const re = /(?:\bz\b|weighted sum|net input)\s*[=:]\s*(-?\d+(?:\.\d+)?)[\s\S]{0,80}?(?:σ\s*\(\s*z\s*\)|sigmoid\s*\(\s*z\s*\)|relu\s*\(\s*z\s*\)|\bactivation\b|\boutput\b|\ba\b)\s*[=:]\s*(-?\d+(?:\.\d+)?)/gi;
for (const m of t.matchAll(re)) { if (pairs.length < 6) pairs.push({z: Number(m[1]), a: Number(m[2])}); }
if (!pairs.length) return {status: 'unmeasured', detail: 'no weighted-sum and activation pair'};
const f = sigmoid ? (z => 1 / (1 + Math.exp(-z))) : (z => Math.max(0, z));
const wrong = pairs.filter(p => Math.abs(f(p.z) - p.a) > 0.011 + 0.01 * Math.abs(f(p.z)));
return {status: wrong.length ? 'fail' : 'pass', detail: wrong.length ? `activation values disagree with ${sigmoid ? 'σ(z) = 1/(1+e^−z)' : 'ReLU(z) = max(0, z)'}` : 'activation values consistent',
        measured: {pairs: pairs.slice(0, 4), wrong: wrong.slice(0, 2)}};
""")

GRADIENT_DESCENT = script(r"""
const step = button(/^\s*step|next|iterate/);
const loss = () => readout(/loss(?:\s*\([^)]*\))?(?:\s*L)?\s*[=≈:]\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)()/i);
const lr = findInput(/learn|rate|alpha|α|step size/);
if (!step || !loss()) return {status: 'unmeasured', detail: 'no step control or loss readout'};
if (numeric(lr)) { const lo = Number(lr.min || 0), hi = Number(lr.max || 1); setValue(lr, lo + 0.1 * (hi - lo) || Number(lr.value)); await sleep(300); }
const reset = button(/reset/); if (reset) { reset.click(); await sleep(300); }
const start = loss().value; const seen = [start];
for (let i = 0; i < 5; i++) { step.click(); await sleep(250); const value = loss(); if (value) seen.push(value.value); }
if (seen.length < 3) return {status: 'unmeasured', detail: 'loss readout did not update'};
const ok = seen[seen.length - 1] <= start + 1e-9 && seen.every(Number.isFinite);
return {status: ok ? 'pass' : 'fail', detail: ok ? 'loss does not increase with a small learning rate' : 'loss increases under gradient descent with a small learning rate', measured: {loss: seen}};
""")

TOPICS = {
    'pendulum': (r'\bpendul', PENDULUM),
    'ohms_law': (r"\bohm|\bvoltage\b|\bcurrent\b.*\bresist|\bcircuit", OHMS_LAW),
    'projectile': (r'projectile|launch angle|trajector|cannon ?ball|thrown at|kicked at', PROJECTILE),
    'reflection_coefficient': (r'transmission line|reflection coefficient|smith chart|standing wave', REFLECTION),
    'neuron_activation': (r'\bneuron|\bactivation|sigmoid|relu|neural network|perceptron', NEURON),
    'gradient_descent': (r'gradient descent|learning rate', GRADIENT_DESCENT),
}


def topics_for(*texts: str) -> list[str]:
    """Priority topics named by the request (question, title, edit target title)."""
    joined = ' '.join(value for value in texts if value)
    return [name for name, (pattern, _) in TOPICS.items() if re.search(pattern, joined, re.IGNORECASE)][:3]


def scripts_for(topics) -> dict[str, str]:
    return {name: TOPICS[name][1] for name in topics if name in TOPICS}
