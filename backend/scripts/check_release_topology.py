"""Check production release destination before any hosted write. No secrets logged."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def main():
    if os.getenv('RELEASE_ENVIRONMENT') != 'production':
        print(json.dumps({'passed': True, 'scope': 'non-production'}))
        return
    path = Path(__file__).resolve().parents[2] / 'deploy/production-topology.json'
    target = json.loads(path.read_text())
    errors = []
    if os.getenv('RENDER_SERVICE_ID') != target['serviceId']:
        errors.append('production_service_target_mismatch')
    if os.getenv('OPENLEARN_API_ORIGIN', '').rstrip('/') != target['apiOrigin']:
        errors.append('production_api_target_mismatch')
    hook = os.getenv('RENDER_DEPLOY_HOOK_URL')
    if hook and urlsplit(hook).path != '/deploy/' + target['serviceId']:
        errors.append('production_hook_target_mismatch')
    print(json.dumps({'passed': not errors, 'errors': errors}))
    raise SystemExit(0 if not errors else 1)


if __name__ == '__main__':
    main()
