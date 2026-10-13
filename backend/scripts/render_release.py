"""Deploy one explicit commit to an existing Render service and await its result.

No environment, plan, region, or permission changes. POST is never blindly retried.
"""
import argparse
import json
import os
import re
import time
from urllib.parse import urlsplit, parse_qsl

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
    hook = os.getenv('RENDER_DEPLOY_HOOK_URL', '')
    if hook:
        origin = os.getenv('OPENLEARN_API_ORIGIN', '')
        parts = urlsplit(hook)
        if parts.scheme != 'https' or parts.hostname != 'api.render.com' or not re.fullmatch(r'/deploy/srv-[a-z0-9]+', parts.path):
            parser.error('Invalid Render deploy hook configuration.')
        if not any(key == 'key' and value for key, value in parse_qsl(parts.query)):
            parser.error('Render deploy hook requires its service key.')
        if urlsplit(origin).scheme != 'https':
            parser.error('Set the public HTTPS OPENLEARN_API_ORIGIN for deploy qualification.')
        # The hook grants deployment access to one service, rather than general
        # account administration. Never print its URL, including HTTP errors.
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            try:
                response = client.post(hook, params=[(key, value) for key, value in parse_qsl(parts.query) if key != 'ref'] + [('ref', args.commit)])
                if response.status_code not in {200, 202}:
                    raise RuntimeError('Render rejected the scoped deployment request.')
            except httpx.HTTPError:
                raise RuntimeError('Deployment submission failed; inspect Render before retrying.') from None
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                try:
                    response = client.get(origin.rstrip('/') + '/release')
                    if response.status_code == 200 and response.json().get('commit') == args.commit:
                        print(json.dumps({'commit': args.commit, 'status': 'live', 'qualification': 'release-metadata'}))
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(10)
        raise RuntimeError('Deployment deadline exceeded; inspect Render before retrying.')
    if not re.fullmatch('srv-[a-z0-9]+', service) or not token:
        parser.error('Set RENDER_SERVICE_ID and RENDER_API_TOKEN in the release environment.')
    with httpx.Client(headers={'Authorization': 'Bearer ' + token}, timeout=30, follow_redirects=False) as client:
        print(json.dumps(deploy(client, service, args.commit)))


if __name__ == '__main__':
    main()
