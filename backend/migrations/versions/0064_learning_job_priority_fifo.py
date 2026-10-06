"""Add stable priority and FIFO ordering to durable learning jobs."""
import sqlalchemy as sa
from alembic import op


revision = '0064_learning_job_priority_fifo'
down_revision = '0063_execution_outbox_retries'
branch_labels = depends_on = None


def upgrade():
    op.add_column('learning_jobs', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('learning_jobs', sa.Column('created_at', sa.Float(), nullable=False, server_default='0'))
    op.create_index(
        'ix_learning_jobs_priority_fifo',
        'learning_jobs',
        ['queue', 'status', 'next_retry_at', 'priority', 'created_at', 'id'],
    )


def downgrade():
    op.drop_index('ix_learning_jobs_priority_fifo', table_name='learning_jobs')
    op.drop_column('learning_jobs', 'created_at')
    op.drop_column('learning_jobs', 'priority')
