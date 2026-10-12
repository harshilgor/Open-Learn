"""Rehearse PostgreSQL recovery between explicitly isolated localhost databases."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def checked_url(variable):
    value = os.getenv(variable)
    if not value or variable == 'DATABASE_URL':
        raise ValueError('Use dedicated qualification URL variables.')
    url = make_url(value)
    if url.query or url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1'} or not (url.database or '').startswith('openlearn_qualification_'):
        raise ValueError('Recovery rehearsal accepts isolated localhost qualification databases only.')
    return value, url


def environment(url):
    env = dict(os.environ)
    env.update(PGHOST=url.host, PGPORT=str(url.port or 5432), PGDATABASE=url.database,
        PGUSER=url.username or '', PGPASSWORD=url.password or '', PGCONNECT_TIMEOUT='5',
        PGOPTIONS='-c statement_timeout=60000 -c lock_timeout=2000')
    return env


def table_counts(engine):
    with engine.connect() as connection, connection.begin():
        connection.execute(text('SET TRANSACTION READ ONLY'))
        connection.execute(text("SET LOCAL statement_timeout='10s'"))
        names = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        result = {}
        for name in names:
            identifier = engine.dialect.identifier_preparer.quote(name)
            # Hashes are compared in memory; no restored private content is exported.
            row = connection.execute(text(f'''SELECT count(*) AS count,
                md5(coalesce(string_agg(hash, '' ORDER BY hash), '')) AS digest
                FROM (SELECT md5(row_to_json(t)::text) AS hash FROM public.{identifier} t) rows''')).mappings().one()
            result[name] = dict(row)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-env', required=True)
    parser.add_argument('--target-env', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    source = target = None
    started = time.monotonic()
    try:
        source_value, source_url = checked_url(args.source_env)
        target_value, target_url = checked_url(args.target_env)
        if source_url.database == target_url.database:
            raise ValueError('Source and target must be different databases.')
        source = create_engine(source_value, pool_size=1, max_overflow=0)
        target = create_engine(target_value, pool_size=1, max_overflow=0)
        before = table_counts(source)
        if not before or table_counts(target):
            raise ValueError('Source must contain fixture tables; target must have an empty public schema.')
        # Dump never traverses a shell or exposes credentials in argv/logs.
        dump = subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl'],
            env=environment(source_url), capture_output=True, timeout=60, check=True).stdout
        subprocess.run(['pg_restore', '--exit-on-error', '--no-owner', '--no-acl', '--dbname', target_url.database],
            input=dump, env=environment(target_url), capture_output=True, timeout=60, check=True)
        after = table_counts(target)
        matches = before == after
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'scope': 'isolated local database restore rehearsal',
            'databaseIntegrityMatched': matches, 'tableCount': len(before),
            'elapsedSeconds': round(time.monotonic()-started, 3), 'productionRecoveryQualified': False,
            'objectRecoveryQualified': False, 'acceptedRpoRto': False}, indent=2), encoding='utf-8')
        if not matches:
            raise ValueError('Restored table counts or row digests differ.')
    except Exception as cause:
        raise SystemExit(f'Recovery rehearsal failed ({type(cause).__name__}). Private driver/process diagnostics suppressed.') from None
    finally:
        if source is not None: source.dispose()
        if target is not None: target.dispose()


if __name__ == '__main__':
    main()
