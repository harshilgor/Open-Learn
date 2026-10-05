"""Opt-in bounded live adapter acceptance; no secrets in evidence output.

Run from repository root: python -m backend.scripts.agent_daytona_acceptance
--snapshot NAME --output work/daytona-live-acceptance
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

from dotenv import load_dotenv

from backend.app.agent_execution.daytona_adapter import DaytonaAdapter
from backend.app.agent_execution.sandbox import OUTPUTS, runner_source, verify
from backend.app.agent_execution.sandbox_config import SandboxPolicy
from backend.app.agent_execution.tools import FIXTURE
from backend.app.object_store import LocalObjectStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(Path('backend/.env'), override=False)
    args.output.mkdir(parents=True, exist_ok=False)
    policy = SandboxPolicy(enabled=True, snapshot=args.snapshot)
    adapter = DaytonaAdapter()
    key = 'ol-accept-' + uuid.uuid4().hex
    task = {'csvText': FIXTURE, 'constraints': {'distanceUnit': 'cm', 'excludedTrials': [3]},
            'inputHash': hashlib.sha256(FIXTURE.encode()).hexdigest(), 'desired_input_revision': 1}
    evidence = {'creationKey': key, 'snapshot': args.snapshot, 'sdk': adapter.runtime_version,
                'startedAt': time.time(), 'checks': [], 'cleanup': 'pending'}
    receipt = args.output / 'evidence.json'

    def save():
        receipt.write_text(json.dumps(evidence, indent=2), encoding='utf-8')

    identifier = None
    exit_code = 1
    save()
    try:
        identifier = adapter.create(key, policy)
        evidence['providerId'] = identifier
        save()
        adapter.stage(identifier, {'/workspace/uploads/task.json': json.dumps(task).encode(),
                                   '/workspace/working/runner.py': runner_source()})
        adapter.execute(identifier, policy.timeout_seconds)
        outputs = {}
        for name in OUTPUTS:
            content = adapter.download(identifier, '/workspace/outputs/' + name, policy.max_output_bytes)
            outputs[name] = content
        if sum(map(len, outputs.values())) > policy.max_output_bytes:
            raise ValueError('aggregate_output_limit')
        verify(task, outputs)
        objects = LocalObjectStore(args.output / 'objects')
        evidence['outputs'] = []
        for name, content in outputs.items():
            digest = objects.put(name, content)
            evidence['outputs'].append({'name': name, 'bytes': len(content), 'sha256': digest})
        evidence['checks'].append('remote_outputs_independently_verified')
        exit_code = 0
    except Exception as error:
        evidence['failureType'] = type(error).__name__
        evidence['failureCode'] = getattr(error, 'code', None)
        evidence['causeType'] = type(error.__cause__).__name__ if error.__cause__ else None
        print('Acceptance failed:', type(error).__name__, flush=True)
    finally:
        try:
            if identifier is None:
                identifier = adapter.reconcile(key)
            if identifier:
                adapter.release(identifier)
            for attempt in range(6):
                if adapter.reconcile(key) is None:
                    break
                if attempt == 5:
                    raise RuntimeError('resource_still_present')
                time.sleep(2)
            evidence['cleanup'] = 'provider_absence_verified'
        except Exception as error:
            evidence['cleanup'] = 'requires_reconciliation'
            evidence['cleanupFailureType'] = type(error).__name__
            exit_code = 1
        evidence['elapsedSeconds'] = round(time.time() - evidence['startedAt'], 2)
        evidence['status'] = 'passed' if exit_code == 0 else 'failed'
        save()
    if exit_code == 0:
        for output in evidence['outputs']:
            if hashlib.sha256(objects.read(output['name'])).hexdigest() != output['sha256']:
                evidence['status'] = 'failed'
                save()
                return 1
        evidence['checks'].append('exported_outputs_readable_after_compute_deletion')
        save()
    print('Status:', evidence['status'], '| Cleanup:', evidence['cleanup'], flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
