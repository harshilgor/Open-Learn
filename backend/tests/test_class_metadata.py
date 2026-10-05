import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from backend.app.class_metadata import get_need, list_needs, migrate_legacy, payload_measurement, snapshot_view, upsert_need


@pytest.fixture
def database():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('PRAGMA foreign_keys=ON'))
        conn.execute(text('CREATE TABLE class_sessions(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,payload TEXT NOT NULL)'))
        conn.execute(text('CREATE TABLE material_attachments(session_id TEXT,version_id TEXT)'))
        item = {'id': 'class_a', 'owner': 'alice', 'sessionId': 'session_a',
                'needInfo': [{'id': f'need_{i:05}', 'windowId': f'w_{i}', 'status': 'open', 'query': 'x' * 280, 'createdAt': i + 1} for i in range(1200)],
                'materialVersionIds': [f'v_{i}' for i in range(1200)]}
        conn.execute(text('INSERT INTO class_sessions VALUES(:id,:owner,:payload)'), {'id': 'class_a', 'owner': 'alice', 'payload': json.dumps(item)})
        conn.execute(text("INSERT INTO class_sessions VALUES('class_b','bob','{}')"))
        conn.execute(text("INSERT INTO material_attachments VALUES('session_a','version_a')"))
        spec = importlib.util.spec_from_file_location('metadata_migration', Path(__file__).parents[1] / 'migrations/versions/0071_class_metadata.py')
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        yield conn, migration, item
    engine.dispose()


def test_backfill_growth_bounds_and_page_replay(database):
    conn, _, original = database
    compact = json.loads(conn.execute(text("SELECT payload FROM class_sessions WHERE id='class_a'")).scalar_one())
    before, after = payload_measurement(original)['bytes'], payload_measurement(compact)['bytes']
    assert before > 400_000
    assert after < 200
    assert 'needInfo' not in compact and 'materialVersionIds' not in compact
    identifiers = []
    cursor = None
    while True:
        page = list_needs(conn, 'alice', 'class_a', after=cursor, limit=10_000)
        assert len(page['items']) <= 100
        identifiers.extend(entry['id'] for entry in page['items'])
        if not page['hasMore']: break
        cursor = page['nextCursor']
    assert len(identifiers) == len(set(identifiers)) == 1200
    view = snapshot_view(conn, compact)
    assert len(view['needInfo']) == 100 and view['needInfoHasMore']
    assert view['materialVersionIds'] == ['version_a']
    assert len(json.dumps(view)) < 50_000


def test_legacy_replay_does_not_overwrite_resolution_and_scopes_owner(database):
    conn, _, original = database
    need = get_need(conn, 'alice', 'class_a', 'need_00000')
    need.update(status='provided', versionId='version_a')
    upsert_need(conn, 'alice', 'class_a', need)
    migrate_legacy(conn, original)
    assert get_need(conn, 'alice', 'class_a', 'need_00000')['status'] == 'provided'
    with pytest.raises(LookupError): get_need(conn, 'bob', 'class_a', 'need_00000')
    with pytest.raises(LookupError): upsert_need(conn, 'bob', 'class_a', need)
    assert list_needs(conn, 'bob', 'class_b')['items'] == []
    assert len(list_needs(conn, 'alice', 'class_a', status='provided')['items']) == 1


def test_downgrade_preserves_resolved_requests_and_attachment_compatibility(database):
    conn, migration, _ = database
    need = get_need(conn, 'alice', 'class_a', 'need_00000'); need['status'] = 'provided'
    upsert_need(conn, 'alice', 'class_a', need)
    with Operations.context(MigrationContext.configure(conn)): migration.downgrade()
    item = json.loads(conn.execute(text("SELECT payload FROM class_sessions WHERE id='class_a'")).scalar_one())
    assert len(item['needInfo']) == 1200 and item['needInfo'][0]['status'] == 'provided'
    assert item['materialVersionIds'] == ['version_a']
    with Operations.context(MigrationContext.configure(conn)): migration.upgrade()
    assert get_need(conn, 'alice', 'class_a', 'need_00000')['status'] == 'provided'


def test_export_owner_rows_and_class_delete_cleanup(database):
    conn, _, _ = database
    from backend.app.identity_data import owned_rows
    _, rows = owned_rows(conn, 'alice')
    assert len(rows['class_need_requests']) == 1200
    assert all(row['owner_id'] == 'alice' for row in rows['class_need_requests'])
    conn.execute(text("DELETE FROM class_sessions WHERE id='class_a'"))
    assert conn.execute(text('SELECT COUNT(*) FROM class_need_requests')).scalar_one() == 0


def test_legacy_profile_import_can_read_then_normalize_request(database):
    conn, _, _ = database
    imported = {'id': 'class_b', 'owner': 'bob', 'needInfo': [{'id': 'need_imported', 'status': 'open'}]}
    conn.execute(text("UPDATE class_sessions SET payload=:payload WHERE id='class_b'"), {'payload': json.dumps(imported)})
    assert get_need(conn, 'bob', 'class_b', 'need_imported')['status'] == 'open'
    migrate_legacy(conn, imported)
    assert 'needInfo' not in imported
    assert get_need(conn, 'bob', 'class_b', 'need_imported')['status'] == 'open'
