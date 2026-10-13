"""Read-only, bounded PostgreSQL plans and contention counters; never export SQL/owners."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

PLAN_FIELDS = {'Node Type', 'Relation Name', 'Index Name', 'Join Type', 'Startup Cost',
    'Total Cost', 'Plan Rows', 'Plan Width', 'Actual Startup Time', 'Actual Total Time',
    'Actual Rows', 'Actual Loops', 'Shared Hit Blocks', 'Shared Read Blocks'}


def redact_plan(node):
    if isinstance(node, list):
        return [redact_plan(item) for item in node]
    if not isinstance(node, dict):
        return None
    result = {key: value for key, value in node.items() if key in PLAN_FIELDS}
    for key in ('Plan', 'Plans'):
        if key in node:
            result[key] = redact_plan(node[key])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--owner-env', default='OPENLEARN_PROBE_OWNER')
    args = parser.parse_args()
    database = os.getenv('DATABASE_DIAGNOSTICS_URL')
    owner = os.getenv(args.owner_env)
    if not database or not owner:
        parser.error('Set DATABASE_DIAGNOSTICS_URL and the probe owner environment variable; values are not printed.')
    engine = create_engine(database, pool_size=1, max_overflow=0, pool_timeout=5,
        connect_args={'connect_timeout': 5})
    report = {'scope': 'read-only-point-in-time', 'productionQualification': False}
    try:
        if engine.dialect.name != 'postgresql':
            raise ValueError('PostgreSQL required')
        with engine.connect() as connection, connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            report['activity'] = [dict(row) for row in connection.execute(text('''
                SELECT coalesce(state,'unknown') AS state, coalesce(wait_event_type,'none') AS wait_type,
                    count(*) AS connections, max(extract(epoch from now()-xact_start)) AS oldest_transaction_seconds
                FROM pg_stat_activity WHERE datname=current_database() GROUP BY state,wait_event_type
            ''')).mappings()]
            report['locks'] = [dict(row) for row in connection.execute(text('''
                SELECT mode,granted,count(*) AS locks FROM pg_locks
                WHERE database=(SELECT oid FROM pg_database WHERE datname=current_database())
                GROUP BY mode,granted
            ''')).mappings()]
            # EXPLAIN without ANALYZE does not run the authored-content query.
            plan = connection.execute(text('''EXPLAIN (FORMAT JSON)
                SELECT id,updated_at FROM workspace_notes WHERE learner_id=:owner
                ORDER BY updated_at DESC,id DESC LIMIT 51'''), {'owner': owner}).scalar_one()
            report['notePagePlan'] = redact_plan(plan)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=float), encoding='utf-8')
    except Exception as cause:
        # Driver messages can include connection strings or statement parameters.
        raise SystemExit(f'Probe failed ({type(cause).__name__}); no sensitive driver details exported.') from None
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
