"""Exercise note integrity and diagnostics only on explicitly local staging."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.scripts.performance_report import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    parsed = urlparse(args.api)
    if parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.scheme != 'http' or parsed.username or parsed.password or parsed.query:
        parser.error('This write-capable fixture is restricted to loopback staging.')
    token = os.getenv('LIVE_BRANCHING_METRICS_TOKEN')
    if not token:
        parser.error('Set the local staging metrics token in the environment.')
    evidence = []
    with httpx.Client(base_url=args.api, timeout=15) as client:
        base = '/v1/learners/local/workspace-notes'
        created = client.post(base, json={'title': 'Synthetic staging note', 'body': 'Synthetic original'})
        created.raise_for_status()
        note = created.json()
        path = base + '/' + note['id']
        updated = client.patch(path, json={'expectedRevision': note['revision'], 'body': 'Synthetic updated'})
        updated.raise_for_status()
        stale = client.patch(path, json={'expectedRevision': note['revision'], 'body': 'Stale synthetic write'})
        saved = client.get(path)
        assert stale.status_code == 409
        assert saved.json()['body'] == 'Synthetic updated'
        assert saved.json()['revision'] == note['revision'] + 1
        for label, response in [('create', created), ('save', updated), ('stale-conflict', stale)]:
            assert response.headers.get('x-openlearn-trace-id')
            assert 'database_query;dur=' in response.headers.get('server-timing', '')
            evidence.append({'operation': label, 'status': response.status_code,
                'traceId': response.headers['x-openlearn-trace-id'], 'serverTiming': response.headers['server-timing']})
        assert client.get('/operations/performance').status_code == 401
        response = client.get('/operations/performance', headers={'X-OpenLearn-Metrics-Token': token})
        response.raise_for_status()
        diagnostics = response.json()
        assert diagnostics['queueHealth']['available'] is True
        assert any(row['resource'] == 'notes_save' for row in diagnostics['series'])
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'disposable loopback staging', 'noteIntegrity': 'passed', 'metricsAccess': 'private',
        'requests': evidence, 'diagnostics': diagnostics}
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    output.with_suffix('.html').write_text(render(diagnostics), encoding='utf-8')
    print(json.dumps({'noteIntegrity': 'passed', 'metricsAccess': 'private', 'artifact': str(output)}))


if __name__ == '__main__':
    main()
