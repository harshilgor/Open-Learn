"""Read-only verification of the deployed pair using its immutable Git contract."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topology', type=Path, default=ROOT / 'deploy/production-topology.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    target = json.loads(args.topology.read_text())
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        backend = client.get(target['apiOrigin'] + '/release')
        frontend = client.get(target['frontendOrigin'] + '/api/release')
        ready = client.get(target['apiOrigin'] + '/ready')
        for response in (backend, frontend, ready):
            response.raise_for_status()
        b, f = backend.json(), frontend.json()
        commit = b['commit']
        import re
        if not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise ValueError('Invalid deployed commit')
        contract = json.loads(subprocess.check_output(['git', 'show', commit + ':deploy/release-contract.json'], cwd=ROOT))
        old = client.get(target['rollbackApiOrigin'] + '/release')
        old.raise_for_status()
    checks = {
        'sameCommit': commit == f.get('commit'),
        'schemaMatchesDeployedContract': b.get('schema', {}).get('actualHeads') == contract['schemaHeads'],
        'frontendSchemaMatches': f.get('schemaHeads') == contract['schemaHeads'],
        'capabilitiesPresent': set(contract['requiredCapabilities']).issubset(b.get('capabilities', [])),
        'frontendOriginMatches': f.get('apiOriginFingerprint') == hashlib.sha256(target['apiOrigin'].encode()).hexdigest(),
        'activeExecutionMatches': b.get('workerMode') == target['executionMode'],
        'rollbackApiExternal': old.json().get('workerMode') == 'external',
        'externalMigrationOwnership': b.get('migrationOwner') == 'single-release-job',
        'readiness': ready.status_code == 200,
    }
    report = {'passed': all(checks.values()), 'commit': commit, 'checks': checks,
              'limitations': ['Does not execute feature jobs or qualify latency, backup recovery or whole-fleet ownership.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
