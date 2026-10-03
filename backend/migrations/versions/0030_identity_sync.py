"""Verified identities, revocable devices, immutable sync and import checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = '0030_identity_sync'
down_revision = '0029_shared_contracts'
branch_labels = depends_on = None


def upgrade():
    op.create_table('identity_accounts',
        sa.Column('id', sa.String(120), primary_key=True),
        sa.Column('subject_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('display_name', sa.String(250), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('deleted_at', sa.Float()))
    op.create_table('identity_devices',
        sa.Column('id', sa.String(120), primary_key=True),
        sa.Column('owner_id', sa.String(120), nullable=False, index=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('revoked_at', sa.Float()),
        sa.Column('last_seen_at', sa.Float()),
        sa.Column('sequence', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('identity_sync_events',
        sa.Column('accepted_order', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('id', sa.String(120), nullable=False, unique=True),
        sa.Column('owner_id', sa.String(120), nullable=False, index=True),
        sa.Column('device_id', sa.String(120), nullable=False),
        sa.Column('device_sequence', sa.Integer(), nullable=False),
        sa.Column('occurred_at', sa.String(80), nullable=False),
        sa.Column('accepted_at', sa.Float(), nullable=False),
        sa.Column('kind', sa.String(80), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('device_id', 'device_sequence'))
    op.create_table('identity_preferences',
        sa.Column('owner_id', sa.String(120), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_table('identity_resources',
        sa.Column('kind', sa.String(100), primary_key=True),
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(120), primary_key=True))
    op.create_table('identity_imports',
        sa.Column('id', sa.String(120), primary_key=True),
        sa.Column('owner_id', sa.String(120), nullable=False),
        sa.Column('source_profile', sa.String(120), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('mapping', sa.Text(), nullable=False),
        sa.Column('objects', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_id', 'source_profile'))
    op.create_table('identity_object_cleanup',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('recording_id', sa.String(120)),
        sa.Column('object_key', sa.String(250), nullable=False))

    connection = op.get_bind()
    # Historical graphs may be shared by several existing local learner profiles.
    for row in connection.execute(sa.text('SELECT graph_id,learner_id FROM learning_sessions')).mappings():
        connection.execute(sa.text("INSERT INTO identity_resources(kind,id,owner_id) VALUES('graph_versions',:id,:owner) ON CONFLICT DO NOTHING"), {'id': row['graph_id'], 'owner': row['learner_id']})
    for table in ('graph_versions', 'topic_scopes', 'graph_jobs'):
        connection.execute(sa.text(f"INSERT INTO identity_resources(kind,id,owner_id) SELECT :kind,id,'local' FROM {table} WHERE id NOT IN (SELECT id FROM identity_resources WHERE kind=:kind)"), {'kind': table})


def downgrade():
    for name in ['identity_object_cleanup', 'identity_imports', 'identity_resources', 'identity_preferences', 'identity_sync_events', 'identity_devices', 'identity_accounts']:
        op.drop_table(name)
