"""Single release migration job. Never invoked automatically by an API replica."""
import os
from backend.app.database import run_serialized_migrations
from backend.scripts.check_release_contract import main as check_contract


def main():
    check_contract()
    configured = os.getenv('DATABASE_MIGRATION_URL', '')
    if not configured.startswith('postgresql'):
        raise SystemExit('DATABASE_MIGRATION_URL must name the approved PostgreSQL database.')
    # Alembic env.py resolves DATABASE_URL; use the dedicated migration route.
    os.environ['DATABASE_URL'] = configured
    run_serialized_migrations(configured)
    print('Release migrations completed; start compatible services next.')


if __name__ == '__main__':
    main()
