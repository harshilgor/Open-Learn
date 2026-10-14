"""Durable In-Class V2 evidence, device coordination, and study artifacts."""
import sqlalchemy as sa
from alembic import op

revision = '0089_class_experience'
down_revision = '0088_memory_sensitive_enable'
branch_labels = depends_on = None


def upgrade():
    op.create_table('class_pairing_rates',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('window_start', sa.Float(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False))
    op.create_table('class_verification_requests',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recording_id', sa.String(160), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('next_poll_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_class_verification_due', 'class_verification_requests', ['state', 'next_poll_at', 'updated_at'])
    op.create_table('class_evidence_words',
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('segment_id', sa.String(160), sa.ForeignKey('lecture_transcript_segments.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_table('class_pairings',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('challenge_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_class_pairings_owner', 'class_pairings', ['owner_id', 'class_id', 'state'])
    op.create_table('class_capture_runs',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_id', sa.String(160), nullable=False),
        sa.Column('epoch', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('last_seen_at', sa.Float(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.UniqueConstraint('class_id', 'epoch', name='uq_class_capture_epoch'))
    op.create_index('ix_class_runs_owner', 'class_capture_runs', ['owner_id', 'class_id', 'epoch'])
    for table in ('class_capture_commands', 'class_document_blocks', 'class_doubts', 'class_buddy_contexts', 'class_visual_artifacts'):
        op.create_table(table,
            sa.Column('id', sa.String(160), primary_key=True),
            sa.Column('owner_id', sa.String(160), nullable=False),
            sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('state', sa.String(32), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.Column('updated_at', sa.Float(), nullable=False),
            sa.Column('payload', sa.Text(), nullable=False))
        op.create_index('ix_' + table + '_page', table, ['owner_id', 'class_id', 'created_at', 'id'])


def downgrade():
    for table in ('class_visual_artifacts', 'class_buddy_contexts', 'class_doubts', 'class_document_blocks', 'class_capture_commands', 'class_capture_runs', 'class_pairings', 'class_evidence_words', 'class_verification_requests'):
        op.drop_table(table)
    op.drop_table('class_pairing_rates')
