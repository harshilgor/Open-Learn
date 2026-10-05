"""Bounded ephemeral captions and durable provisional-note reconciliation."""
import sqlalchemy as sa
from alembic import op

revision = '0070_class_live_notes'
down_revision = '0069_material_ocr_work'
branch_labels = depends_on = None


def upgrade():
    op.create_table('class_caption_interims',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stream_id', sa.String(80), nullable=False),
        sa.Column('provider_item_id', sa.String(160), nullable=False),
        sa.Column('update_revision', sa.Integer(), nullable=False),
        sa.Column('transcript', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_id', 'class_id', 'stream_id', 'provider_item_id', name='uq_class_caption_interim'))
    op.create_index('ix_class_caption_interims_expiry', 'class_caption_interims', ['expires_at'])
    op.create_index('ix_class_caption_interims_class', 'class_caption_interims', ['owner_id', 'class_id', 'updated_at'])
    op.create_table('class_live_notes',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('live_segment_id', sa.String(160), sa.ForeignKey('class_live_transcript_segments.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('start_ms', sa.BigInteger()), sa.Column('end_ms', sa.BigInteger()),
        sa.Column('result', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('authoritative_sources', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('error', sa.String(500)),
        sa.Column('created_at', sa.Float(), nullable=False), sa.Column('updated_at', sa.Float(), nullable=False))
    op.create_index('ix_class_live_notes_class_range', 'class_live_notes', ['owner_id', 'class_id', 'start_ms', 'end_ms'])


def downgrade():
    op.drop_table('class_live_notes')
    op.drop_table('class_caption_interims')
