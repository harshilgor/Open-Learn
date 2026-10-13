"""Fail closed before adding worker pools to a shared Supabase server pool."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=Path, default=Path('deploy/connection-budget.json'))
    parser.add_argument('--server-pool', type=int, required=True)
    parser.add_argument('--reserved-server-connections', type=int, default=3)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.server_pool < 1 or args.reserved_server_connections < 0:
        parser.error('Invalid connection envelope')
    budget = json.loads(args.budget.read_text())
    steady = sum(row['replicas'] * row['poolSize'] for row in budget['roles'])
    peak = steady * budget['deploymentOverlapFactor'] + args.reserved_server_connections
    report = {'passed': peak <= args.server_pool, 'steadyApplicationConnections': steady,
              'peakSessionConnectionsIncludingReserve': peak, 'serverPool': args.server_pool,
              'mode': 'conservative session-pooling envelope',
              'limitations': ['Transaction pooling requires a separately verified workload model; LISTEN remains session-bound.',
                              'Database total/client limits require independent checks.']}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
