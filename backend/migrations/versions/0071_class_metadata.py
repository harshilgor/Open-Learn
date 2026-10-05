"""Normalize unbounded class NeedInfo requests; attachments already have a ledger."""
import json
import sqlalchemy as sa
from alembic import op

revision = '0071_class_metadata'
down_revision = '0070_class_live_notes'
branch_labels = depends_on = None


def upgrade():
    op.create_table('class_need_requests',
        sa.Column('id', sa.String(160), nullable=False),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('window_id', sa.String(160)),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'class_id', 'id', name='pk_class_need_requests'))
    op.create_index('ix_class_need_requests_status', 'class_need_requests', ['owner_id', 'class_id', 'status', 'id'])
    conn = op.get_bind()
    after = ''
    try:
        from backend.app.class_metadata import migrate_legacy
    except ModuleNotFoundError:
        from app.class_metadata import migrate_legacy
    while True:
        rows = conn.execute(sa.text('SELECT id,owner_id,payload FROM class_sessions WHERE id>:after ORDER BY id LIMIT 100'), {'after': after}).mappings().all()
        if not rows:
            break
        for row in rows:
            item = json.loads(row['payload']); item.update(id=row['id'], owner=row['owner_id'])
            migrate_legacy(conn, item)
            conn.execute(sa.text('UPDATE class_sessions SET payload=:payload WHERE id=:id'), {'id': row['id'], 'payload': json.dumps(item, separators=(',', ':'))})
        after = rows[-1]['id']


def downgrade():
    conn = op.get_bind()
    after = ''
    while True:
        rows = conn.execute(sa.text('SELECT id,owner_id,payload FROM class_sessions WHERE id>:after ORDER BY id LIMIT 100'), {'after': after}).mappings().all()
        if not rows:
            break
        for row in rows:
            item = json.loads(row['payload'])
            item['needInfo'] = [json.loads(raw) for raw in conn.execute(sa.text('SELECT payload FROM class_need_requests WHERE owner_id=:owner AND class_id=:class ORDER BY id'), {'owner': row['owner_id'], 'class': row['id']}).scalars()]
            item['materialVersionIds'] = list(conn.execute(sa.text('SELECT version_id FROM material_attachments WHERE session_id=:session ORDER BY version_id'), {'session': item.get('sessionId')}).scalars())
            item.pop('metadataVersion', None)
            conn.execute(sa.text('UPDATE class_sessions SET payload=:payload WHERE id=:id'), {'id': row['id'], 'payload': json.dumps(item)})
        after = rows[-1]['id']
    op.drop_index('ix_class_need_requests_status', table_name='class_need_requests')
    op.drop_table('class_need_requests')
