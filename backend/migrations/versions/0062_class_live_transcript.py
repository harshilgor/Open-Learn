"""Persist committed provisional live-caption turns for class replay."""
import sqlalchemy as sa
from alembic import op


revision = '0062_class_live_transcript'
down_revision = '0061_quiz_history_keyset'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'class_live_transcript_segments',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recording_id', sa.String(160), sa.ForeignKey('lecture_recordings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stream_id', sa.String(80), nullable=False),
        sa.Column('stream_sequence', sa.Integer(), nullable=False),
        sa.Column('provider_item_id', sa.String(160), nullable=False),
        sa.Column('transcript', sa.Text(), nullable=False),
        sa.Column('transcription_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('class_id', 'stream_id', 'stream_sequence', name='uq_class_live_transcript_stream_sequence'),
        sa.UniqueConstraint('class_id', 'stream_id', 'provider_item_id', name='uq_class_live_transcript_provider_item'),
    )
    op.create_index(
        'ix_class_live_transcript_owner_class_sequence',
        'class_live_transcript_segments',
        ['owner_id', 'class_id', 'stream_sequence'],
    )


def downgrade():
    op.drop_index('ix_class_live_transcript_owner_class_sequence', table_name='class_live_transcript_segments')
    op.drop_table('class_live_transcript_segments')
