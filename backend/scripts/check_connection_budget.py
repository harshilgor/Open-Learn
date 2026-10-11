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
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.budget.read_text()))))


if __name__ == '__main__':
    main()
