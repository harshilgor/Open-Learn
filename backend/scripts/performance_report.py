"""Generate a private operational dashboard from bounded process diagnostics."""
import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


def alerts(report):
    result = []
    for row in report.get('series', []):
        if row['sampleCount'] < 50:
            continue
        if row['stage'] == 'database_checkout' and row['p95Ms'] > 200:
            result.append('Database checkout p95 exceeds 200 ms; inspect pool wait and connection establishment.')
        if row['stage'] == 'event_loop_lag' and row['p95Ms'] > 50:
            result.append('Event loop lag p95 exceeds 50 ms; inspect blocking work and CPU pressure.')
        if row['stage'] == 'api_headers' and row['resource'] == 'notes_save' and row['p95Ms'] > 1000:
            result.append('Note-save response-header p95 exceeds 1 second; inspect note persistence separately from chat.')
        if row['stage'] == 'api_total' and row['sampleFailures'] / row['sampleCount'] > .01:
            result.append(f"{row['resource']} HTTP rejection/failure fraction exceeds 1%; inspect statuses to separate expected conflicts from outages.")
    queues = report.get('queueHealth', {})
    if not queues.get('available'):
        result.append('Queue health unavailable; do not interpret missing data as healthy.')
    if queues.get('databaseLockWaiters', 0):
        result.append('PostgreSQL lock waiters exist; inspect transaction duration and contention.')
    terminal = queues.get('terminalGenerationsLastHour', {})
    eligible = sum(terminal.get(status, 0) for status in ('completed', 'failed', 'interrupted'))
    if eligible >= 50 and (terminal.get('failed', 0) + terminal.get('interrupted', 0)) / eligible > .01:
        result.append('Generation failures/interruptions exceed 1% of non-cancelled terminal work in the last hour; SSE HTTP status alone is insufficient.')
    for row in [queues.get('generations', {}), *queues.get('jobs', [])]:
        if row.get('oldestQueuedSeconds', 0) > 30:
            result.append('Oldest queued work exceeds 30 seconds; inspect capacity, priority and provider quotas.')
        if row.get('expiredLeases', 0):
            result.append('Expired execution leases exist; inspect recovery and worker health.')
    return sorted(set(result))


def render(report):
    warnings = alerts(report)
    rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(row.get(key, "")))}</td>' for key in
        ('resource', 'stage', 'sampleCount', 'sampleFailures', 'p50Ms', 'p95Ms', 'p99Ms')) + '</tr>' for row in report.get('series', []))
    runbook_links = (
        ('database checkout', 'database-pool-exhaustion'),
        ('database lock', 'database-pool-exhaustion'),
        ('event loop lag', 'slow-api'),
        ('note-save', 'failed-note-saves'),
        ('queue health', 'queue-health'),
        ('queued work', 'queue-health'),
        ('expired execution leases', 'queue-health'),
        ('generation failures', 'provider-outage'),
    )
    linked_warnings = []
    for warning in warnings:
        anchor = next((target for marker, target in runbook_links if marker in warning.lower()), 'feature-readiness')
        href = '../../docs/performance/P20_P22_Operational_Readiness.md#' + anchor
        linked_warnings.append('<li>' + html.escape(warning) + f' <a href="{href}">Open runbook</a></li>')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Learn performance diagnostics</title><style>body{{font:16px system-ui;background:#111814;color:#edf4ef;max-width:1100px;margin:40px auto;padding:20px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid #34483b;text-align:left}}.warning{{color:#f6ce83}}pre{{white-space:pre-wrap}}</style>
<h1>Open Learn performance diagnostics</h1><p>Process {report.get('pid')}; snapshot {html.escape(str(report.get('observedAt', '')))}.</p>
<p>Rolling bounded samples, including failures. This is one process, not fleet-wide availability or a production SLO verdict. Header timing excludes streamed completion. SQL execution timing includes lock waits but does not isolate them.</p>
<h2>Signals to investigate</h2><ul class="warning">{''.join(linked_warnings) or '<li>No threshold exceeded in available samples; small sample sizes are not a qualification.</li>'}</ul>
<h2>Timing samples</h2><table><thead><tr><th>Resource</th><th>Stage</th><th>Samples</th><th>Failures</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Durable work</h2><pre>{html.escape(json.dumps(report.get('queueHealth', {}), indent=2))}</pre></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api')
    parser.add_argument('--snapshot', help='Read an existing content-free diagnostic JSON snapshot instead of HTTP')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if bool(args.api) == bool(args.snapshot):
        parser.error('Choose --api or --snapshot')
    if args.snapshot:
        report = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    else:
        from urllib.parse import urlparse
        origin = urlparse(args.api)
        if origin.username or origin.password or origin.query or origin.fragment or origin.path not in {'', '/'}:
            parser.error('Use an origin without credentials or query strings')
        if origin.scheme != 'https' and not (origin.scheme == 'http' and origin.hostname in {'127.0.0.1', 'localhost'}):
            parser.error('Use HTTPS or loopback')
        token = os.environ.get('LIVE_BRANCHING_METRICS_TOKEN')
        if not token:
            parser.error('Set LIVE_BRANCHING_METRICS_TOKEN in the operator environment; never pass it in a URL')
        response = httpx.get(args.api.rstrip('/') + '/operations/performance', headers={'X-OpenLearn-Metrics-Token': token}, timeout=15, follow_redirects=False)
        response.raise_for_status()
        report = response.json()
        report['scope'] = args.api.rstrip('/')
        try:
            release_response = httpx.get(args.api.rstrip('/') + '/release', timeout=10, follow_redirects=False)
            if release_response.status_code == 200:
                release = release_response.json()
                report['release'] = release
                report['commit'] = release.get('commit')
        except (httpx.HTTPError, ValueError):
            # Metrics remain useful when release metadata has not been deployed.
            pass
    report['observedAt'] = datetime.now(timezone.utc).isoformat()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report), encoding='utf-8')
    output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'dashboard': str(output), 'alerts': alerts(report)}))


if __name__ == '__main__':
    main()
