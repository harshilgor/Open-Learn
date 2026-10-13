"""Reject deployment shapes exceeding the database or Redis connection envelope."""
import argparse
import json
from pathlib import Path


def _number(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Connection budget values must be nonnegative integers')
    return value


def validate_redis(redis):
    """Redis pools across roles x replicas x deploy overlap must fit the Key Value plan."""
    steady = sum(_number(role['replicas']) * _number(role['poolSize']) for role in redis['roles'])
    peak = steady * _number(redis['deploymentOverlapFactor']) + _number(redis['reservedConnections'])
    if peak > _number(redis['connectionLimit']):
        raise ValueError(f'Peak Redis connection budget {peak} exceeds Key Value limit')
    return {'steadyRedisConnections': steady, 'peakRedisIncludingReserves': peak,
            'remainingRedisConnections': redis['connectionLimit'] - peak}


def validate(budget):
    number = _number
    steady = sum(number(role['replicas']) * number(role['poolSize']) for role in budget['roles'])
    peak = (steady * number(budget['deploymentOverlapFactor']) + number(budget['migrationConnections'])
            + number(budget['listenerConnections']) + number(budget['reservedConnections']))
    if peak > number(budget['databaseConnectionLimit']):
        raise ValueError(f'Peak connection budget {peak} exceeds database limit')
    result = {'steadyApplicationConnections': steady, 'peakIncludingReserves': peak,
              'remainingConnections': budget['databaseConnectionLimit'] - peak}
    if 'redis' in budget:
        redis_roles = {row['role'] for row in budget['redis']['roles']}
        if redis_roles != {row['role'] for row in budget['roles']}:
            # Every database writer must also be able to invalidate the cache.
            raise ValueError('Redis budget roles must match database roles')
        result.update(validate_redis(budget['redis']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=Path, default=Path('deploy/connection-budget.json'))
    parser.add_argument('--blueprint', type=Path, help='Also check all proposed role pools against a Render Blueprint')
    args = parser.parse_args()
    budget = json.loads(args.budget.read_text())
    result = validate(budget)
    if args.blueprint:
        import yaml
        from backend.app.capacity import REDIS_ROLE_POOLS, ROLE_POOLS
        blueprint = yaml.safe_load(args.blueprint.read_text())
        services = list(blueprint.get('services', []))
        for project in blueprint.get('projects', []):
            for environment in project.get('environments', []):
                services.extend(environment.get('services', []))
        recorded = {row['role']: row for row in budget['roles']}
        redis_recorded = {row['role']: row for row in budget.get('redis', {}).get('roles', [])}
        seen = set()
        for service in services:
            if service.get('type') in {'keyvalue', 'redis'}:
                continue  # the cache itself, not a database consumer
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
            if role in redis_recorded:
                redis_pool = int(env.get('OPENLEARN_REDIS_POOL_SIZE') or REDIS_ROLE_POOLS.get(role, 0))
                if redis_pool != redis_recorded[role]['poolSize'] or replicas != redis_recorded[role]['replicas']:
                    raise ValueError('Blueprint Redis pool/replica count does not match connection budget')
        if seen != set(recorded):
            raise ValueError('Budget contains a role absent from the Blueprint')
        result['blueprintPoolsMatched'] = True
    print(json.dumps(result))


if __name__ == '__main__':
    main()
