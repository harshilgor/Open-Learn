"""Persist resumable material upload sessions and immutable parts."""
import sqlalchemy as sa
from alembic import op

revision = '0055_resumable_material_uploads'
down_revision = '0054_class_material_intakes'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'material_upload_sessions',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('material_id', sa.String(160), sa.ForeignKey('materials.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_versions.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE')),
        sa.Column('intake_id', sa.String(160), sa.ForeignKey('class_material_intakes.id', ondelete='CASCADE')),
        sa.Column('total_bytes', sa.BigInteger(), nullable=False),
        sa.Column('chunk_bytes', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='open'),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('lease_expires', sa.Float()),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('completed_at', sa.Float()),
    )
    op.create_index('ix_material_upload_expiry', 'material_upload_sessions', ['status', 'expires_at'])
    op.create_table(
        'material_upload_parts',
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_upload_sessions.version_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('part_index', sa.Integer(), primary_key=True),
        sa.Column('object_key', sa.String(900), nullable=False, unique=True),
        sa.Column('byte_count', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table('material_upload_parts')
    op.drop_index('ix_material_upload_expiry', table_name='material_upload_sessions')
    op.drop_table('material_upload_sessions')
