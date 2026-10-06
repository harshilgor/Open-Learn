"""Give failed outbox events bounded retry and dead-letter state."""
import sqlalchemy as sa
from alembic import op


revision = '0063_execution_outbox_retries'
down_revision = '0062_class_live_transcript'
branch_labels = depends_on = None


def upgrade():
    op.add_column('execution_outbox', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('execution_outbox', sa.Column('next_attempt_at', sa.Float(), nullable=False, server_default='0'))
    op.add_column('execution_outbox', sa.Column('failed_at', sa.Float(), nullable=True))
    op.add_column('execution_outbox', sa.Column('last_error', sa.String(200), nullable=True))
    op.create_index(
        'ix_execution_outbox_ready',
        'execution_outbox',
        ['delivered_at', 'failed_at', 'next_attempt_at', 'created_at', 'id'],
    )


def downgrade():
    op.drop_index('ix_execution_outbox_ready', table_name='execution_outbox')
    op.drop_column('execution_outbox', 'last_error')
    op.drop_column('execution_outbox', 'failed_at')
    op.drop_column('execution_outbox', 'next_attempt_at')
    op.drop_column('execution_outbox', 'attempt_count')
