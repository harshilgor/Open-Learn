"""Headless runtime verification for generated visuals.

Static checks (``visual_code``) prove generated JavaScript parses. They cannot
see a runtime exception, a blank canvas, a NaN readout, clipped content, or a
slider that changes nothing. This module mounts a candidate in headless
Chromium through the same verification kit the web app builds from the chat
card's own frame, program and script order, then reports objective findings.

Security boundary: candidates are untrusted. Each check uses a fresh browser
context, every network request except the locally served kit and reviewed
library modules is aborted, Chromium's OS sandbox stays enabled unless an
operator explicitly disables it, and every step is time bounded. Nothing from
the learner's account, credentials or the API is available to the page.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'https://visual-verifier.openlearn.invalid'
VERSION = 1
VIEWPORTS = {'desktop': (720, 900), 'mobile': (360, 740)}
MAX_FINDINGS = 24
MAX_PROBES = 10
BAD_VALUE_PATTERN = r'\bNaN\b|\bundefined\b|-?\bInfinity\b|\[object Object\]'

# Severity semantics: ``error`` blocks publication and is sent back for repair;
# ``warning`` is repaired when the attempt budget allows; ``info`` is advisory.
ERROR, WARNING, INFO = 'error', 'warning', 'info'


def asset_dir() -> Path:
    return Path(os.getenv('OPENLEARN_VISUAL_ASSET_DIR') or ROOT / 'web' / 'public' / 'visual-assets')


def kit_path() -> Path:
    return Path(os.getenv('OPENLEARN_VISUAL_VERIFICATION_KIT') or ROOT / 'web' / '.visual-verification' / 'verification-kit.js')


def enabled() -> bool:
    return os.getenv('OPENLEARN_VISUAL_RUNTIME_VERIFICATION', 'on').lower() not in {'0', 'off', 'false', 'no'}


def unavailable_reason() -> str | None:
    if not enabled():
        return 'disabled'
    if not kit_path().is_file() or not (asset_dir() / 'manifest.json').is_file():
        return 'assets_missing'
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return 'playwright_missing'
    return None


def content_digest(content: dict, controls=(), control_values=None) -> str:
    canonical = json.dumps({'content': {key: content.get(key) for key in ('css', 'html', 'jsFunctions', 'jsExpressions', 'initialHeight')},
                            'controls': [dict(value) for value in controls], 'values': control_values or {}, 'version': VERSION},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def finding(severity, code, message, **detail):
    value = {'severity': severity, 'code': code, 'message': message[:400]}
    if detail:
        value['detail'] = detail
    return value


METRICS_JS = r"""(badPattern) => {
  const doc = document.documentElement, body = document.body;
  const width = doc.clientWidth;
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0; };
  const describe = el => { const id = el.id ? '#' + el.id : ''; const cls = (typeof el.className === 'string' && el.className.trim()) ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return (el.tagName.toLowerCase() + id + cls).slice(0, 80); };
  const rect = el => { const r = el.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; };
  const text = (body.innerText || '').trim();
  const overflowing = [];
  let elementCount = 0, smallText = 0;
  for (const el of body.querySelectorAll('*')) {
    elementCount++;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    // Elements beyond the frame's right edge are clipped: the frame hides overflow.
    if (r.right > width + 2 && overflowing.length < 6 && !el.closest('.leaflet-container')) overflowing.push({el: describe(el), right: Math.round(r.right)});
    if (el.childNodes.length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(el).fontSize) < 10) smallText++;
  }
  const labelled = el => {
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title')) return true;
    if (el.tagName === 'BUTTON') return !!el.textContent.trim();
    if (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) return true;
    return !!el.closest('label');
  };
  const controls = [...document.querySelectorAll('input,select,textarea,button')].filter(visible)
    .filter(el => !['hidden', 'submit', 'image'].includes(el.type) || el.tagName === 'BUTTON');
  const bad = text.match(new RegExp(badPattern, 'g')) || [];
  return {
    textLength: text.length, textSample: text.slice(0, 300), width, bodyHeight: Math.ceil(body.scrollHeight),
    elementCount, overflowing, smallText,
    canvases: [...document.querySelectorAll('canvas')].filter(visible).map(rect),
    svgs: [...document.querySelectorAll('svg')].filter(visible).map(el => ({...rect(el), parts: el.querySelectorAll('*').length})),
    images: [...document.querySelectorAll('img')].filter(visible).length,
    controlCount: controls.length,
    unlabeled: controls.filter(el => !labelled(el)).slice(0, 6).map(describe),
    badValues: [...new Set(bad)].slice(0, 4),
    // Drawing surfaces sized from a container whose height resolves to ~0
    // (height:100% inside the auto-sized frame) render nothing visible.
    collapsed: [...document.querySelectorAll('canvas,svg')].filter(el => {
      const s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden') return false;
      if (el.tagName.toLowerCase() === 'svg' && el.querySelectorAll('*').length < 8) return false;
      const r = el.getBoundingClientRect(), host = el.parentElement ? el.parentElement.getBoundingClientRect().width : r.width;
      return host > 160 && (r.height < 40 || r.width < 40);
    }).slice(0, 4).map(el => describe(el) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height)),
  };
}"""

# Text whose color barely differs from what is behind it, usually from colors
# hardcoded for one theme. Backgrounds resolve through ancestors to the host
# card color, because the frame itself is transparent.
# Text drawn on top of other text (colliding diagram labels, values printed over
# node names). Uses per-line boxes of text nodes, so inline runs and wrapped
# paragraphs never count as overlapping themselves.
OVERLAP_JS = r"""() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const boxes = [];
  for (let node = walker.nextNode(); node && boxes.length < 300; node = walker.nextNode()) {
    const text = node.textContent.trim();
    if (text.length < 2) continue;
    const parent = node.parentElement;
    if (!parent || parent.closest('script,style,option,textarea')) continue;
    const style = getComputedStyle(parent);
    if (style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    for (const r of range.getClientRects()) {
      if (r.width < 4 || r.height < 4) continue;
      boxes.push({source: node, text: text.slice(0, 24), x: r.left, y: r.top, w: r.width, h: r.height});
    }
  }
  const pairs = [];
  for (let i = 0; i < boxes.length && pairs.length < 6; i++) {
    for (let j = i + 1; j < boxes.length && pairs.length < 6; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.source === b.source) continue;
      const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (w <= 0 || h <= 0) continue;
      if (w * h > 0.3 * Math.min(a.w * a.h, b.w * b.h)) pairs.push([a.text, b.text]);
    }
  }
  return pairs;
}"""

CONTRAST_JS = r"""(fallback) => {
  const parse = value => { const m = /rgba?\(([^)]+)\)/.exec(value || ''); if (!m) return null;
    const p = m[1].split(',').map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const channel = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const luminance = c => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
  const backdrop = el => { for (let node = el; node; node = node.parentElement) { const c = parse(getComputedStyle(node).backgroundColor);
    if (c && c.a > 0.5) return c; } return fallback; };
  const samples = [], low = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (samples.length >= 80) break;
    if (el.closest('svg') || !el.childNodes.length) continue;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1)) continue;
    const style = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!r.width || !r.height || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const fg = parse(style.color); if (!fg) continue;
    const bg = backdrop(el); const a = luminance(fg), b = luminance(bg);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    samples.push(ratio);
    if (ratio < 3) low.push({text: el.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100});
  }
  return {sampled: samples.length, low: low.length, examples: low.slice(0, 3)};
}"""

PROBE_TARGETS_JS = r"""(limit) => {
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = el => (el.getAttribute('aria-label') || el.id || (el.labels && el.labels[0] && el.labels[0].textContent) || el.textContent || el.tagName).trim().slice(0, 60);
  const fields = [...document.querySelectorAll('input[type=range],input[type=number],select,input[type=checkbox],input[type=radio]')].filter(el => visible(el) && !el.disabled);
  const buttons = [...document.querySelectorAll('button,[role=button]')].filter(el => visible(el) && !el.disabled);
  const chosen = [...fields.slice(0, Math.max(limit - 4, 6)), ...buttons.slice(0, 4)].slice(0, limit);
  return chosen.map((el, index) => { el.setAttribute('data-openlearn-probe', String(index));
    return {index, kind: el.tagName === 'SELECT' ? 'select' : el.tagName === 'INPUT' ? el.type : 'button', label: label(el)}; });
}"""

ACT_JS = r"""(index) => {
  const el = document.querySelector('[data-openlearn-probe="' + index + '"]');
  if (!el) return false;
  const fire = () => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); };
  if (el.tagName === 'SELECT') { if (el.options.length < 2) return false; el.selectedIndex = (el.selectedIndex + 1) % el.options.length; fire(); return true; }
  if (el.tagName === 'INPUT' && (el.type === 'range' || el.type === 'number')) {
    const min = el.min !== '' ? Number(el.min) : 0, max = el.max !== '' ? Number(el.max) : min + 10;
    const current = Number(el.value);
    el.value = String(Math.abs(current - max) > 1e-9 ? max : min); fire(); return true;
  }
  el.click(); return true;
}"""

EDGE_JS = r"""(edge) => {
  for (const el of document.querySelectorAll('input[type=range],input[type=number]')) {
    if (el.disabled) continue;
    const value = edge === 'min' ? el.min : el.max;
    if (value === '') continue;
    el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));
  }
}"""

FINGERPRINT_JS = r"""() => {
  const text = (document.body.innerText || '').trim();
  const svg = [...document.querySelectorAll('svg')].map(el => el.innerHTML.length + ':' + el.innerHTML.slice(0, 4000)).join('|');
  const values = [...document.querySelectorAll('[style]')].slice(0, 400).map(el => el.getAttribute('style')).join('|');
  return {text, svg, style: values};
}"""


def _hash(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _image_regions(png: bytes, regions):
    """Per-region (stddev, quantized digest) of a screenshot; None if Pillow is absent."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return None
    image = Image.open(io.BytesIO(png)).convert('RGB')
    results = []
    for region in regions:
        x, y = max(0, region['x']), max(0, region['y'])
        box = (x, y, min(image.width, x + region['w']), min(image.height, y + region['h']))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            results.append(None)
            continue
        crop = image.crop(box)
        deviation = max(ImageStat.Stat(crop).stddev)
        small = crop.convert('L').resize((24, 24))
        digest = hashlib.sha1(bytes(value // 16 for value in small.tobytes())).hexdigest()
        results.append({'stddev': round(deviation, 2), 'digest': digest})
    return results


class _Runtime:
    """One browser on one dedicated event loop, shared by every caller thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name='visual-verifier', daemon=True)
        self.thread.start()
        self.playwright = None
        self.browser = None
        self.lock = None
        self.slots = None

    async def browser_instance(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
            self.slots = asyncio.Semaphore(max(1, min(4, int(os.getenv('OPENLEARN_VISUAL_VERIFY_CONCURRENCY', '2')))))
        async with self.lock:
            if self.browser is not None and self.browser.is_connected():
                return self.browser
            from playwright.async_api import async_playwright
            if self.playwright is None:
                self.playwright = await async_playwright().start()
            sandbox = os.getenv('OPENLEARN_VISUAL_VERIFY_CHROMIUM_SANDBOX', 'true').lower() not in {'0', 'false', 'no'}
            # SwiftShader provides software WebGL so Three.js scenes are verified headlessly.
            self.browser = await self.playwright.chromium.launch(
                headless=True, chromium_sandbox=sandbox,
                args=['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--mute-audio', '--disable-extensions'])
            return self.browser

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)


_runtime: _Runtime | None = None
_runtime_lock = threading.Lock()
_cache: OrderedDict[str, dict] = OrderedDict()
_cache_lock = threading.Lock()


def _shared_runtime() -> _Runtime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = _Runtime()
        return _runtime


def cached(digest: str) -> dict | None:
    with _cache_lock:
        value = _cache.get(digest)
        if value is not None:
            _cache.move_to_end(digest)
        return value


def _remember(digest: str, report: dict):
    if report.get('status') == 'unavailable':
        return
    with _cache_lock:
        _cache[digest] = report
        _cache.move_to_end(digest)
        while len(_cache) > 64:
            _cache.popitem(last=False)


def verify_blocking(content: dict, controls=(), control_values=None, *, probe=True, screenshot_dir=None, timeout=45.0,
                    checks: dict[str, str] | None = None) -> dict:
    """Verify from any thread. Never raises for candidate defects.

    ``checks`` maps names to JavaScript functions evaluated in the settled
    desktop frame (benchmarks use them for task-specific assertions).
    """
    digest = content_digest(content, controls, control_values)
    if screenshot_dir is None and not checks and (value := cached(digest)):
        return value | {'cached': True}
    reason = unavailable_reason()
    if reason:
        return {'version': VERSION, 'status': 'unavailable', 'reason': reason, 'findings': [], 'digest': digest}
    runtime = _shared_runtime()
    future = runtime.submit(_verify(runtime, content, list(controls), control_values or {}, probe, screenshot_dir, digest, checks or {}))
    try:
        report = future.result(timeout=timeout + 15)
    except concurrent.futures.TimeoutError:
        future.cancel()
        report = {'version': VERSION, 'status': 'unavailable', 'reason': 'verifier_timeout', 'findings': [], 'digest': digest}
    if not checks:
        _remember(digest, report)
    return report


async def verify(content: dict, controls=(), control_values=None, **options) -> dict:
    return await asyncio.to_thread(verify_blocking, content, controls, control_values, **options)


def _host_page(width: int, theme: str) -> str:
    background = '#1f1e1d' if theme == 'dark' else '#ffffff'
    return (f'<!doctype html><html class="{theme}" data-theme="{theme}"><head><meta charset="utf-8">'
            f'<style>html,body{{margin:0;padding:0;background:{background}}}body{{width:{width}px}}#root{{width:100%}}</style></head>'
            '<body><div id="root"></div><script type="module" src="/verification-kit.js"></script></body></html>')


async def _route(route, width, theme, blocked):
    url = route.request.url
    if not url.startswith(ORIGIN + '/'):
        if len(blocked) < 20:
            blocked.append(urlparse(url).netloc or url[:40])
        await route.abort('blockedbyclient')
        return
    path = urlparse(url).path
    headers = {'access-control-allow-origin': '*', 'cache-control': 'no-store'}
    if path == '/host.html':
        await route.fulfill(status=200, body=_host_page(width, theme), headers=headers | {'content-type': 'text/html'})
        return
    if path == '/verification-kit.js':
        await route.fulfill(status=200, body=kit_path().read_bytes(), headers=headers | {'content-type': 'text/javascript'})
        return
    name = path.removeprefix('/visual-assets/')
    candidate = (asset_dir() / name).resolve()
    if path.startswith('/visual-assets/') and name.endswith('.js') and '/' not in name and candidate.parent == asset_dir().resolve() and candidate.is_file():
        await route.fulfill(status=200, body=candidate.read_bytes(), headers=headers | {'content-type': 'text/javascript'})
        return
    await route.fulfill(status=404, body='', headers=headers)


def _errors(events, after=0):
    found = []
    for event in events:
        if event.get('at', 0) < after:
            continue
        if event.get('type') == 'error':
            detail = event.get('detail') or {}
            found.append({'kind': str(detail.get('kind', 'error')), 'message': str(detail.get('message', ''))[:300]})
        elif event.get('type') == 'runError':
            found.append({'kind': 'script', 'message': str((event.get('detail') or {}).get('message', ''))[:300]})
    return found


async def _settle(frame, budget=2.5):
    """Wait until text and structure stop changing (or the budget ends)."""
    deadline = time.monotonic() + budget
    previous, stable = None, 0
    await asyncio.sleep(0.6)
    while time.monotonic() < deadline:
        value = await frame.evaluate('() => [document.body.innerText.length, document.body.querySelectorAll("*").length, document.body.scrollHeight]')
        stable = stable + 1 if value == previous else 0
        if stable >= 2:
            return
        previous = value
        await asyncio.sleep(0.25)


async def _mount(context, content, controls, control_values, timeout):
    page = await context.new_page()
    await page.goto(ORIGIN + '/host.html', wait_until='load', timeout=timeout * 1000)
    await page.wait_for_function('() => !!window.__openlearnVerification', timeout=timeout * 1000)
    payload = {'content': content, 'controls': [{'id': c['id'], 'initial': c['initial']} for c in controls], 'controlValues': control_values}
    await page.evaluate('''async (input) => {
        const handle = await window.__openlearnVerification.mountVisual(document.getElementById('root'), input);
        window.__visualEvents = handle.events; }''', payload)
    frame = next((value for value in page.frames if value != page.main_frame), None)
    return page, frame


async def _events(page):
    return await page.evaluate('() => (window.__visualEvents || []).slice()')


async def _screenshot(page):
    return await page.locator('iframe[data-openlearn-visual]').screenshot(timeout=8000)


THEME_BACKDROPS = {'light': {'r': 255, 'g': 255, 'b': 255, 'a': 1}, 'dark': {'r': 31, 'g': 30, 'b': 29, 'a': 1}}


async def _viewport_pass(browser, name, content, controls, control_values, probe, screenshot_dir, findings, checks=None, theme='light'):
    width, height = VIEWPORTS[name]
    label = name if theme == 'light' else f'{name} dark theme'
    blocked: list[str] = []
    context = await browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1,
                                        java_script_enabled=True, service_workers='block', accept_downloads=False)
    result = {'viewport': name}
    try:
        await context.route('**/*', lambda route: _route(route, width, theme, blocked))
        started = time.monotonic()
        try:
            page, frame = await asyncio.wait_for(_mount(context, content, controls, control_values, 12), 15)
        except asyncio.TimeoutError:
            findings.append(finding(ERROR, 'script_timeout', f'The visual did not finish initializing within 15 seconds at {name} width; check for infinite loops or blocking work during setup.'))
            return result
        if frame is None:
            findings.append(finding(ERROR, 'frame_missing', 'The sandbox frame did not mount.'))
            return result
        await asyncio.wait_for(_settle(frame), 6)
        result['initMs'] = round((time.monotonic() - started) * 1000)
        metrics = await asyncio.wait_for(frame.evaluate(METRICS_JS, BAD_VALUE_PATTERN), 5)
        result['metrics'] = metrics
        events = await _events(page)
        result['frameHeight'] = next((e['detail']['height'] for e in reversed(events) if e.get('type') == 'resize'), None)
        for error in _errors(events)[:3]:
            code = 'console_error' if error['kind'] == 'console' else 'runtime_exception'
            findings.append(finding(ERROR, code, f'{name}: {error["message"] or "uncaught error"}', viewport=name))
        png = await _screenshot(page)
        if screenshot_dir:
            Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
            (Path(screenshot_dir) / f'{name}-{theme}.png').write_bytes(png)
        whole = _image_regions(png, [{'x': 0, 'y': 0, 'w': width, 'h': int(result['frameHeight'] or height)}]) or [None]
        canvas_stats = _image_regions(png, metrics['canvases']) or []
        result['canvasStats'] = canvas_stats
        has_graphics = bool(metrics['canvases'] or metrics['svgs'] or metrics['images'])
        if metrics['textLength'] < 20 and not has_graphics:
            findings.append(finding(ERROR, 'empty_render', f'{name}: the visual rendered almost no content ({metrics["textLength"]} characters, no canvas/SVG/image).'))
        if whole[0] and whole[0]['stddev'] < 1.0:
            findings.append(finding(ERROR, 'blank_render', f'{name}: the rendered frame is a single flat color.'))
        frame_area = max(1, width * int(result['frameHeight'] or height))
        for region, stats in zip(metrics['canvases'], canvas_stats):
            if stats and stats['stddev'] < 1.5:
                severity = ERROR if region['w'] * region['h'] >= 0.25 * frame_area else WARNING
                findings.append(finding(severity, 'blank_canvas', f'{name}: a {region["w"]}x{region["h"]} canvas is blank after initialization; the scene or chart did not draw.'))
        if metrics.get('collapsed'):
            findings.append(finding(ERROR, 'collapsed_graphic', f'{name}: drawing surfaces have almost no size: {", ".join(metrics["collapsed"])}. '
                                    'The frame sizes itself to its content, so height:100% or 100vh resolves to nearly 0; give the '
                                    'container an explicit height (for example height:360px or aspect-ratio:16/9) and size the renderer from it.'))
        frame_height = result['frameHeight']
        for region in ([*metrics['canvases'], *metrics['svgs']] if frame_height else []):
            if region['w'] * region['h'] < 160 * 100:
                continue
            shown = max(0, min(region['y'] + region['h'], frame_height) - max(region['y'], 0))
            if shown < 0.5 * region['h']:
                findings.append(finding(ERROR, 'graphic_clipped', f'{name}: a {region["w"]}x{region["h"]} drawing is mostly outside the '
                                        f'{frame_height}px frame (fixed or absolute positioning takes it out of the page flow); keep it in normal flow.'))
                break
        if metrics['badValues']:
            findings.append(finding(ERROR, 'invalid_value_displayed', f'{name}: visible text contains {", ".join(metrics["badValues"])}; validate inputs and format computed values.'))
        if metrics['overflowing']:
            severity = ERROR if name == 'desktop' else WARNING
            items = ', '.join(f'{item["el"]} (right edge {item["right"]}px)' for item in metrics['overflowing'][:3])
            findings.append(finding(severity, 'horizontal_overflow', f'{name} ({width}px wide): content is clipped beyond the right edge: {items}. Use fluid widths (max-width:100%, flex-wrap, responsive canvas sizing).'))
        if (result['frameHeight'] or 0) >= 4000:
            findings.append(finding(WARNING, 'height_clipped', f'{name}: the visual is taller than 4000px and is clipped; make it more compact.'))
        if metrics['unlabeled'] and name == 'desktop':
            findings.append(finding(WARNING, 'unlabeled_control', f'Controls without an accessible label: {", ".join(metrics["unlabeled"][:4])}. Add a <label for>, aria-label, or button text.'))
        if metrics['smallText'] > 3 and name == 'mobile':
            findings.append(finding(INFO, 'small_text', f'{metrics["smallText"]} text elements render below 10px on mobile.'))
        if theme == 'light':
            overlaps = await asyncio.wait_for(frame.evaluate(OVERLAP_JS), 5)
            result['overlappingText'] = overlaps
            if overlaps:
                examples = '; '.join(f'"{a}" over "{b}"' for a, b in overlaps[:3])
                findings.append(finding(WARNING, 'overlapping_text', f'{name}: text is drawn on top of other text ({examples}). '
                                        'Offset labels from shapes and from each other, or reduce label density.'))
        contrast = await asyncio.wait_for(frame.evaluate(CONTRAST_JS, THEME_BACKDROPS[theme]), 5)
        result['contrast'] = contrast
        if contrast['low'] >= 2 and contrast['low'] > 0.2 * contrast['sampled']:
            examples = ', '.join(f'"{item["text"]}" ({item["ratio"]}:1)' for item in contrast['examples'])
            findings.append(finding(WARNING, 'low_contrast', f'{label}: {contrast["low"]} of {contrast["sampled"]} text elements are hard to read '
                                    f'against their background, e.g. {examples}. Use the theme color variables instead of fixed colors.'))
        if blocked:
            findings.append(finding(INFO, 'network_blocked', f'{name}: {len(blocked)} external requests were blocked during verification ({", ".join(sorted(set(blocked))[:3])}).'))
        if checks:
            result['checks'] = {}
            for key, source in checks.items():
                try:
                    result['checks'][key] = await asyncio.wait_for(frame.evaluate(source), 10)
                except Exception as error:  # noqa: BLE001 - a failing check is a result, not a verifier fault
                    result['checks'][key] = {'pass': False, 'error': f'{type(error).__name__}: {str(error)[:200]}'}
        if probe:
            result['resources'] = await _resources(context, page)
            result['controls'] = await _probe(page, frame, findings, events)
        return result
    finally:
        await context.close()


async def _resources(context, page):
    """Main-thread busy fraction and JS heap over one idle second (animation cost)."""
    try:
        session = await context.new_cdp_session(page)
        await session.send('Performance.enable')

        async def sample():
            return {item['name']: item['value'] for item in (await session.send('Performance.getMetrics'))['metrics']}
        first = await sample()
        await asyncio.sleep(1.0)
        second = await sample()
        elapsed = max(1e-3, second['Timestamp'] - first['Timestamp'])
        return {'busyFraction': round((second['TaskDuration'] - first['TaskDuration']) / elapsed, 3),
                'scriptFraction': round((second['ScriptDuration'] - first['ScriptDuration']) / elapsed, 3),
                'heapMb': round(second['JSHeapUsedSize'] / 1_048_576, 1)}
    except Exception as error:  # noqa: BLE001 - a measurement gap is not a candidate defect
        return {'error': type(error).__name__}


async def _fingerprint(page, frame, regions):
    value = await frame.evaluate(FINGERPRINT_JS)
    stats = _image_regions(await _screenshot(page), regions) if regions else []
    return {'text': _hash(value['text']), 'svg': _hash(value['svg']), 'style': _hash(value['style']),
            'canvas': _hash([item and item['digest'] for item in (stats or [])])}


async def _probe(page, frame, findings, events):
    targets = await frame.evaluate(PROBE_TARGETS_JS, MAX_PROBES)
    if not targets:
        return []
    regions = (await frame.evaluate(METRICS_JS, BAD_VALUE_PATTERN))['canvases']
    first = await _fingerprint(page, frame, regions)
    await asyncio.sleep(0.45)
    baseline = await _fingerprint(page, frame, regions)
    drifting = {key for key in baseline if baseline[key] != first[key]}
    results, unresponsive = [], []
    started_at = (events[-1]['at'] if events else 0) + 1
    for target in targets:
        acted = await asyncio.wait_for(frame.evaluate(ACT_JS, target['index']), 5)
        await asyncio.sleep(0.45)
        after = await _fingerprint(page, frame, regions)
        changed = {key for key in after if after[key] != baseline[key]}
        stable_changed = changed - drifting
        outcome = 'responsive' if stable_changed else ('inconclusive' if changed or not acted else 'unresponsive')
        results.append(target | {'outcome': outcome})
        # Reset, previous, pause and similar buttons are legitimately inert in the
        # initial state; a field or a forward/step/play/add action is not.
        inert_ok = target['kind'] == 'button' and re.search(r'reset|clear|prev|back|pause|stop|close|undo|delete|remove|copy|ask|link', target['label'], re.I)
        if outcome == 'unresponsive' and (target['kind'] in {'range', 'number', 'select', 'checkbox'} or (target['kind'] == 'button' and not inert_ok)):
            unresponsive.append(target['label'] or target['kind'])
        baseline = after
    probe_errors = _errors(await _events(page), after=started_at)
    for error in probe_errors[:3]:
        findings.append(finding(ERROR, 'interaction_exception', f'Interacting with a control raised: {error["message"] or "an uncaught error"}'))
    if unresponsive:
        findings.append(finding(WARNING, 'unresponsive_control', f'Changing these controls did not change any visible output: {", ".join(unresponsive[:4])}. Wire each input to recompute and redraw.'))
    # Every numeric field at its minimum, then at its maximum: edge values such
    # as zero gravity or zero length are where NaN and Infinity appear.
    for edge in ('min', 'max'):
        await frame.evaluate(EDGE_JS, edge)
        await asyncio.sleep(0.45)
        bad = (await frame.evaluate(METRICS_JS, BAD_VALUE_PATTERN))['badValues']
        if bad:
            findings.append(finding(ERROR, 'invalid_value_after_interaction', f'With every slider and number input at its {edge}imum the visual '
                                    f'shows {", ".join(bad)}; guard edge values (for example clamp to a small positive minimum).'))
            break
    edge_errors = _errors(await _events(page), after=started_at)[len(probe_errors):]
    for error in edge_errors[:2]:
        findings.append(finding(ERROR, 'interaction_exception', f'Moving controls to their limits raised: {error["message"] or "an uncaught error"}'))
    return results


async def _verify(runtime, content, controls, control_values, probe, screenshot_dir, digest, checks):
    started = time.monotonic()
    findings: list[dict] = []
    try:
        browser = await runtime.browser_instance()
    except Exception as error:  # noqa: BLE001 - launch failures degrade to static validation
        LOG.warning('Visual verifier unavailable: %s', type(error).__name__)
        return {'version': VERSION, 'status': 'unavailable', 'reason': 'browser_unavailable', 'findings': [], 'digest': digest}
    passes = {}
    async with runtime.slots:
        try:
            # Desktop (with control probing and checks), mobile, then desktop in the dark theme.
            for name, theme in (('desktop', 'light'), ('mobile', 'light'), ('desktop', 'dark')):
                key = name if theme == 'light' else f'{name}-{theme}'
                passes[key] = await _viewport_pass(browser, name, content, controls, control_values,
                                                   probe and key == 'desktop', screenshot_dir and Path(screenshot_dir), findings,
                                                   checks if key == 'desktop' else None, theme)
                if any(item['code'] in {'script_timeout', 'frame_missing'} for item in findings):
                    break
        except Exception as error:  # noqa: BLE001 - an internal verifier fault must not fail a candidate
            LOG.warning('Visual verifier fault: %s: %s', type(error).__name__, str(error)[:200])
            return {'version': VERSION, 'status': 'unavailable', 'reason': 'verifier_fault', 'findings': findings[:MAX_FINDINGS],
                    'digest': digest, 'durationMs': round((time.monotonic() - started) * 1000)}
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    unique, seen = [], set()
    for item in sorted(findings, key=lambda value: order[value['severity']]):
        key = (item['code'], item['message'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    status = 'failed' if any(item['severity'] == ERROR for item in unique) else 'passed'
    return {'version': VERSION, 'status': status, 'findings': unique[:MAX_FINDINGS], 'viewports': passes, 'digest': digest,
            'durationMs': round((time.monotonic() - started) * 1000)}


HINTS = [
    (r'Failed to resolve module specifier', 'Only these bare imports resolve: three, three/addons/controls/OrbitControls.js, d3, chart.js, gsap, leaflet. Other packages and URLs are unavailable; implement the logic directly.'),
    (r"reading '(?:Scene|WebGLRenderer|select|Chart|to|registerPlugin)'", 'A library object is undefined: use `const THREE = await import("three")` (or its .default) inside an async function, and await that function before using the library.'),
    (r'Cannot read properties of null', 'An element lookup returned null: create the element in html (or before the lookup) and use the exact id.'),
    (r'is not defined', 'A name is used before it is declared or outside its scope: declare shared state at the top of jsFunctions and call functions only from jsExpressions after they are defined.'),
    (r'collapsed_graphic|graphic_clipped', 'Example sizing: #scene{width:100%;height:360px} then renderer.setSize(scene.clientWidth, scene.clientHeight) and a ResizeObserver on #scene. Avoid height:100%, 100vh and position:fixed for the main graphic.'),
    (r'Unexpected end of input|Unexpected token', 'The code is syntactically incomplete; return the full code without truncation and balance every bracket and quote.'),
]


def repair_feedback(report: dict, include_warnings=True) -> str:
    """Bounded, model-facing summary of actionable findings with targeted hints."""
    items = [item for item in report.get('findings', []) if item['severity'] == ERROR or (include_warnings and item['severity'] == WARNING)]
    lines = [f'- [{item["severity"]}] {item["code"]}: {item["message"]}' for item in items[:8]]
    text = '\n'.join(lines)
    hints = [hint for pattern, hint in HINTS if re.search(pattern, text)]
    if hints:
        text += '\nHints:\n' + '\n'.join(f'- {hint}' for hint in hints[:3])
    return text[:2400]


def summary(report: dict) -> dict:
    """Compact, persisted form: no screenshots, page text or candidate code."""
    return {'status': report.get('status'), 'reason': report.get('reason'), 'digest': report.get('digest'),
            'durationMs': report.get('durationMs'),
            'findings': [{'severity': item['severity'], 'code': item['code']} for item in report.get('findings', [])][:MAX_FINDINGS]}
