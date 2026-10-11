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
    if not isinstance(report, dict):
        return ['backend_metadata_invalid']
    errors = []
    if report.get("protocolVersion") != contract["protocolVersion"]:
        errors.append("protocol_version_mismatch")
    capabilities = report.get('capabilities')
    if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
        errors.append('backend_capability_metadata_invalid')
    elif not set(contract["requiredCapabilities"]) <= set(capabilities):
        errors.append("missing_capability")
    schema = report.get("schema") if isinstance(report.get("schema"), dict) else {}
    heads = schema.get('actualHeads')
    if (schema.get("compatible") is not True or not isinstance(heads, list)
            or not all(isinstance(value, str) for value in heads) or sorted(heads) != sorted(contract["schemaHeads"])):
        errors.append("schema_mismatch")
    if expected_sha and report.get("commit") != expected_sha:
        errors.append("commit_mismatch")
    return errors


def check_backend(client, origin, contract, expected_sha=None, require_external_migrations=False):
    readiness = client.get(origin.rstrip('/') + '/ready')
    if readiness.status_code != 200:
        return ["backend_not_ready"]
    response = client.get(origin.rstrip('/') + '/release')
    if response.status_code != 200:
        return ["release_metadata_unavailable"]
    report = response.json()
    errors = validate_report(report, contract, expected_sha)
    if require_external_migrations and isinstance(report, dict) and report.get('migrationOwner') != 'single-release-job':
        errors.append('startup_migration_owner_conflict')
    return errors


def validate_frontend_report(frontend, contract, api, expected_sha=None):
    if not isinstance(frontend, dict):
        return ['frontend_metadata_invalid']
    errors = []
    if frontend.get('protocolVersion') != contract['protocolVersion']:
        errors.append('frontend_protocol_mismatch')
    for field, expected, error in (
        ('requiredCapabilities', contract['requiredCapabilities'], 'frontend_capability_mismatch'),
        ('schemaHeads', contract['schemaHeads'], 'frontend_schema_contract_mismatch')):
        values = frontend.get(field)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values) or sorted(values) != sorted(expected):
            errors.append(error)
    if expected_sha and frontend.get('commit') != expected_sha:
        errors.append('frontend_commit_mismatch')
    expected_origin = str(httpx.URL(api)).rstrip('/')
    if frontend.get('apiOriginFingerprint') != hashlib.sha256(expected_origin.encode()).hexdigest():
        errors.append('frontend_api_origin_mismatch')
    return errors


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
            errors = check_backend(client, args.api, contract, args.expected_sha, args.require_external_migrations)
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
                    errors.extend(validate_frontend_report(frontend, contract, args.api, args.expected_frontend_sha))
    except httpx.TimeoutException:
        errors = ['release_probe_timeout']
    except httpx.ConnectError:
        errors = ['release_probe_connection_failed']
    except httpx.HTTPError:
        errors = ['release_probe_http_failed']
    except (OSError, ValueError, TypeError):
        errors = ['release_metadata_invalid_or_unreadable']
    print(json.dumps({'passed': not errors, 'errors': errors}))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
