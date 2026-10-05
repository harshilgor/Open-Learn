"""Add bounded per-class stage timing samples."""
from alembic import op
import sqlalchemy as sa

revision = '0053_class_processing_metrics'
down_revision = '0052_chat_reminders'
branch_labels = depends_on = None


def upgrade():
    op.create_table('class_processing_metrics',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage', sa.String(60), nullable=False),
        sa.Column('correlation_id', sa.String(200), nullable=False),
        sa.Column('outcome', sa.String(30), nullable=False),
        sa.Column('queued_at', sa.Float()),
        sa.Column('started_at', sa.Float(), nullable=False),
        sa.Column('finished_at', sa.Float(), nullable=False),
        sa.Column('queue_wait_ms', sa.Float(), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('counters_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.Float(), nullable=False),
    )
    op.create_index('ix_class_metrics_owner_stage_time', 'class_processing_metrics', ['owner_id', 'class_id', 'stage', 'finished_at'])
    op.create_index('ix_class_metrics_owner_time', 'class_processing_metrics', ['owner_id', 'class_id', 'finished_at'])


def downgrade():
    op.drop_index('ix_class_metrics_owner_time', table_name='class_processing_metrics')
    op.drop_index('ix_class_metrics_owner_stage_time', table_name='class_processing_metrics')
    op.drop_table('class_processing_metrics')
