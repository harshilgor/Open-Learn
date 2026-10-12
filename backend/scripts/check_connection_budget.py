"""Reject deployment shapes exceeding the database connection envelope."""
import argparse
import json
from pathlib import Path


def validate(budget):
    def number(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Connection budget values must be nonnegative integers')
        return value
    steady = sum(number(role['replicas']) * number(role['poolSize']) for role in budget['roles'])
    peak = (steady * number(budget['deploymentOverlapFactor']) + number(budget['migrationConnections'])
            + number(budget['listenerConnections']) + number(budget['reservedConnections']))
    if peak > number(budget['databaseConnectionLimit']):
        raise ValueError(f'Peak connection budget {peak} exceeds database limit')
    return {'steadyApplicationConnections': steady, 'peakIncludingReserves': peak,
            'remainingConnections': budget['databaseConnectionLimit'] - peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=Path, default=Path('deploy/connection-budget.json'))
    parser.add_argument('--blueprint', type=Path, help='Also check all proposed role pools against a Render Blueprint')
    args = parser.parse_args()
    budget = json.loads(args.budget.read_text())
    result = validate(budget)
    if args.blueprint:
        import yaml
        from backend.app.capacity import ROLE_POOLS
        blueprint = yaml.safe_load(args.blueprint.read_text())
        services = list(blueprint.get('services', []))
        for project in blueprint.get('projects', []):
            for environment in project.get('environments', []):
                services.extend(environment.get('services', []))
        recorded = {row['role']: row for row in budget['roles']}
        seen = set()
        for service in services:
            command = service.get('dockerCommand', '')
            env = {row['key']: row.get('value') for row in service.get('envVars', []) if 'key' in row}
            role = command.split('hosted_runtime ', 1)[1].split()[0] if 'hosted_runtime ' in command else env.get('OPENLEARN_PROCESS_ROLE')
            if role is None:
                raise ValueError('Every database consumer needs an explicit process role')
            if role in seen or role not in recorded:
                raise ValueError('Blueprint role is duplicated or missing from connection budget')
            seen.add(role)
            pool = int(env.get('OPENLEARN_DB_POOL_SIZE') or ROLE_POOLS.get(role, 0))
            replicas = int(service.get('numInstances', 1))
            if 'scaling' in service:
                replicas = int(service['scaling']['maxInstances'])
            if pool != recorded[role]['poolSize'] or replicas != recorded[role]['replicas']:
                raise ValueError('Blueprint pool/replica count does not match connection budget')
        if seen != set(recorded):
            raise ValueError('Budget contains a role absent from the Blueprint')
        result['blueprintPoolsMatched'] = True
    print(json.dumps(result))


if __name__ == '__main__':
    main()
