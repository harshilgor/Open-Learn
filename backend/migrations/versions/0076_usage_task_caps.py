"""Bound a durable task root across allowance window resets."""
from alembic import op
import sqlalchemy as sa

revision = '0076_usage_task_caps'
down_revision = '0075_usage_operator_controls'
branch_labels = depends_on = None


def upgrade():
    op.create_index('ix_usage_event_owner_root_source', 'usage_events', ['owner_id', 'root_id', 'source'])
    op.create_index('ix_usage_reservation_owner_root_state', 'usage_reservations', ['owner_id', 'root_id', 'state'])
    op.create_table(
        'usage_task_caps',
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('root_id', sa.String(160), nullable=False),
        sa.Column('maximum_micro', sa.BigInteger(), nullable=False),
        sa.Column('period_id', sa.String(160), sa.ForeignKey('usage_periods.id'), nullable=True),
        sa.Column('policy_version', sa.String(80), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'root_id'),
        sa.CheckConstraint('maximum_micro > 0', name='ck_usage_task_cap_positive'),
    )
    op.create_index('ix_usage_task_cap_created', 'usage_task_caps', ['created_at'])


def downgrade():
    op.drop_index('ix_usage_task_cap_created', table_name='usage_task_caps')
    op.drop_table('usage_task_caps')
    op.drop_index('ix_usage_reservation_owner_root_state', table_name='usage_reservations')
    op.drop_index('ix_usage_event_owner_root_source', table_name='usage_events')
