"""Fail closed on incompatible backend/frontend releases; read-only HTTP checks."""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx

CONTRACT = Path(__file__).resolve().parents[2] / "deploy" / "release-contract.json"


def validate_report(report, contract, expected_sha=None):
    errors = []
    if report.get("protocolVersion") != contract["protocolVersion"]:
        errors.append("protocol_version_mismatch")
    if not set(contract["requiredCapabilities"]) <= set(report.get("capabilities", [])):
        errors.append("missing_capability")
    schema = report.get("schema", {})
    if schema.get("compatible") is not True or sorted(schema.get("actualHeads", [])) != sorted(contract["schemaHeads"]):
        errors.append("schema_mismatch")
    if expected_sha and report.get("commit") != expected_sha:
        errors.append("commit_mismatch")
    return errors


def check_backend(client, origin, contract, expected_sha=None):
    readiness = client.get(origin.rstrip('/') + '/ready')
    if readiness.status_code != 200:
        return ["backend_not_ready"]
    response = client.get(origin.rstrip('/') + '/release')
    if response.status_code != 200:
        return ["release_metadata_unavailable"]
    return validate_report(response.json(), contract, expected_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--expected-sha')
    parser.add_argument('--frontend')
    parser.add_argument('--expected-frontend-sha')
    parser.add_argument('--frontend-metadata', type=Path, help='Metadata fetched from this candidate with authenticated vercel curl')
    parser.add_argument('--require-external-migrations', action='store_true')
    args = parser.parse_args()
    for origin in filter(None, (args.api, args.frontend)):
        parsed = urlparse(origin)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
            parser.error('Use an origin without credentials, path, or query')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
            parser.error('Use HTTPS, or loopback for staging simulation')
    contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            errors = check_backend(client, args.api, contract, args.expected_sha)
            if args.require_external_migrations and not errors:
                if client.get(args.api.rstrip('/') + '/release').json().get('migrationOwner') != 'single-release-job':
                    errors.append('startup_migration_owner_conflict')
            if args.frontend:
                import os
                bypass = os.getenv('VERCEL_AUTOMATION_BYPASS_SECRET')
                if args.frontend_metadata:
                    frontend = json.loads(args.frontend_metadata.read_text(encoding='utf-8-sig'))
                    status = 200
                else:
                    response = client.get(args.frontend.rstrip('/') + '/api/release',
                        headers={'x-vercel-protection-bypass': bypass} if bypass else {})
                    status = response.status_code
                    frontend = response.json() if status == 200 else {}
                if status != 200:
                    errors.append('frontend_metadata_unavailable')
                else:
                    if frontend.get('protocolVersion') != contract['protocolVersion']:
                        errors.append('frontend_protocol_mismatch')
                    if sorted(frontend.get('requiredCapabilities', [])) != sorted(contract['requiredCapabilities']):
                        errors.append('frontend_capability_mismatch')
                    if sorted(frontend.get('schemaHeads', [])) != sorted(contract['schemaHeads']):
                        errors.append('frontend_schema_contract_mismatch')
                    if args.expected_frontend_sha and frontend.get('commit') != args.expected_frontend_sha:
                        errors.append('frontend_commit_mismatch')
                    expected_origin = str(httpx.URL(args.api)).rstrip('/')
                    if frontend.get('apiOriginFingerprint') != hashlib.sha256(expected_origin.encode()).hexdigest():
                        errors.append('frontend_api_origin_mismatch')
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        errors = ['release_probe_failed']
    print(json.dumps({'passed': not errors, 'errors': errors}))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
