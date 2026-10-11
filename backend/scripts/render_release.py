"""Deploy one explicit commit to an existing Render service and await its result.

No environment, plan, region, or permission changes. POST is never blindly retried.
"""
import argparse
import json
import os
import re
import time

import httpx


def deploy(client, service, commit, *, deadline_seconds=1200, pause=time.sleep):
    response = client.post(f'https://api.render.com/v1/services/{service}/deploys',
        json={'commitId': commit, 'clearCache': 'do_not_clear'})
    response.raise_for_status()
    identifier = response.json()['id']
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        response = client.get(f'https://api.render.com/v1/services/{service}/deploys/{identifier}')
        response.raise_for_status()
        result = response.json()
        status = result.get('status')
        if status == 'live':
            if result.get('commit', {}).get('id') != commit:
                raise RuntimeError('Render deployed a different commit.')
            return {'deployId': identifier, 'commit': commit, 'status': status}
        if status in {'build_failed', 'update_failed', 'pre_deploy_failed', 'canceled', 'deactivated'}:
            raise RuntimeError(f'Render deployment ended in {status}.')
        pause(10)
    raise RuntimeError('Render deployment deadline exceeded; inspect the existing deploy before retrying.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.commit):
        parser.error('Use a full immutable Git commit SHA.')
    service, token = os.getenv('RENDER_SERVICE_ID', ''), os.getenv('RENDER_API_TOKEN', '')
    if not re.fullmatch('srv-[a-z0-9]+', service) or not token:
        parser.error('Set RENDER_SERVICE_ID and RENDER_API_TOKEN in the release environment.')
    with httpx.Client(headers={'Authorization': 'Bearer ' + token}, timeout=30, follow_redirects=False) as client:
        print(json.dumps(deploy(client, service, args.commit)))


if __name__ == '__main__':
    main()
