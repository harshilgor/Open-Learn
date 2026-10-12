"""Fail-closed P20–P22 evidence gate. Produces eligibility, never deployment approval."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

FAULTS = {'provider-slowdown', 'database-pool-pressure', 'notification-loss',
    'api-worker-restart', 'expired-lease', 'rolling-release'}
METADATA = ('workloadVersion', 'environment', 'region', 'databaseRegion', 'model',
    'providerRateVersion', 'processTopology', 'connectionBudget', 'buildCommit')


def check(evidence, workload):
    failures = []
    def require(condition, code):
        if not condition:
            failures.append(code)
    require(isinstance(evidence, dict), 'invalid_evidence')
    if not isinstance(evidence, dict):
        return failures
    require(evidence.get('scope') == 'isolated-hosted-e2e', 'hosted_scope_required')
    metadata = evidence.get('metadata', {})
    if not isinstance(metadata, dict): metadata = {}
    for key in METADATA:
        require(bool(metadata.get(key)), 'missing_metadata:' + key)
    require(isinstance(metadata.get('buildCommit'), str)
        and bool(re.fullmatch('[a-f0-9]{40}', metadata['buildCommit'])), 'invalid_commit')
    require(type(metadata.get('workloadVersion')) is int and metadata['workloadVersion'] == workload['version'], 'workload_version_mismatch')
    profiles = evidence.get('profiles', {})
    if not isinstance(profiles, dict): profiles = {}
    required_scenarios = {row['id'] for row in workload['scenarios']}
    minimum = workload['minimumSamplesForPercentileGate']
    for name, configuration in workload['profiles'].items():
        profile = profiles.get(name, {})
        if not isinstance(profile, dict): profile = {}
        require(type(profile.get('concurrentUsers')) is int and profile['concurrentUsers'] == configuration['concurrentUsers'], 'profile_concurrency:' + name)
        regions = profile.get('regions', {})
        if not isinstance(regions, dict): regions = {}
        for region in workload['regions']:
            result = regions.get(region, {})
            if not isinstance(result, dict): result = {}
            coverage = result.get('scenarios', {})
            if not isinstance(coverage, dict): coverage = {}
            for scenario in sorted(required_scenarios):
                row = coverage.get(scenario, {})
                if not isinstance(row, dict): row = {}
                count = row.get('successfulSamples')
                require(type(count) is int and count >= minimum, f'samples:{name}:{region}:{scenario}')
                require(row.get('correctnessPassed') is True, f'correctness:{name}:{region}:{scenario}')
            metrics = result.get('metrics', {})
            if not isinstance(metrics, dict): metrics = {}
            for metric, limit in workload['warmP95TargetsMs'].items():
                row = metrics.get(metric, {})
                if not isinstance(row, dict): row = {}
                value, count = row.get('p95Ms'), row.get('successfulSamples')
                require(type(count) is int and count >= minimum, f'metric_samples:{name}:{region}:{metric}')
                require(type(value) in (int, float) and math.isfinite(value) and 0 <= value < limit,
                    f'latency:{name}:{region}:{metric}')
            require(result.get('unexpectedFailures') == 0 and type(result.get('unexpectedFailures')) is int,
                f'unexpected_failures:{name}:{region}')
    invariants = evidence.get('qualityInvariantViolations', {})
    if not isinstance(invariants, dict): invariants = {}
    for invariant in workload['qualityThresholds']:
        require(type(invariants.get(invariant)) is int and invariants[invariant] == 0, 'quality:' + invariant)
    faults = evidence.get('faultExercises', {})
    if not isinstance(faults, dict): faults = {}
    for fault in sorted(FAULTS):
        require(faults.get(fault) == 'passed', 'fault:' + fault)
    for requirement in ('databaseRestoreVerified', 'objectRestoreVerified', 'rpoRtoAccepted',
                        'rollbackRehearsed', 'costAndQuotaReviewed', 'observationWindowComplete'):
        require(evidence.get(requirement) is True, requirement)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--workload', type=Path, default=Path('docs/performance/workload.json'))
    args = parser.parse_args()
    try:
        failures = check(json.loads(args.evidence.read_text(encoding='utf-8')),
            json.loads(args.workload.read_text(encoding='utf-8')))
    except (ValueError, TypeError, KeyError, OSError):
        failures = ['invalid_or_unreadable_evidence']
    report = {'performanceAcceptanceEligible': not failures, 'rolloutApproval': False,
        'failures': failures, 'note': 'Operator evidence must be traceable to actual artifacts; this gate cannot prove provenance or 30-day uptime.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
