"""Durable remote resource obligations and separately retryable learning delivery."""
import sqlalchemy as sa
from alembic import op

revision = '0044_agent_sandbox_learning'
down_revision = '0043_agent_research'
branch_labels = depends_on = None


def upgrade():
    op.create_table('agent_sandbox_leases',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('input_revision', sa.Integer(), nullable=False),
        sa.Column('creation_key', sa.String(160), nullable=False, unique=True),
        sa.Column('provider_id', sa.String(160)),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('run_id', 'input_revision', name='uq_agent_sandbox_input'))
    op.create_index('ix_agent_sandbox_cleanup', 'agent_sandbox_leases', ['status', 'expires_at'])
    op.create_index('ix_agent_sandbox_owner', 'agent_sandbox_leases', ['owner_id', 'run_id'])
    op.create_table('agent_sandbox_cleanup',
        sa.Column('id',sa.String(160),primary_key=True),
        sa.Column('owner_id',sa.String(160),nullable=False),
        sa.Column('creation_key',sa.String(160),nullable=False),
        sa.Column('provider_id',sa.String(160)),
        sa.Column('created_at',sa.Float(),nullable=False))
    op.create_table('agent_sandbox_budgets',
        sa.Column('scope',sa.String(200),primary_key=True),
        sa.Column('day',sa.Integer(),primary_key=True),
        sa.Column('reserved_creations',sa.Integer(),nullable=False))
    op.create_table('agent_learning_continuations',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('input_revision', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('run_id', 'input_revision', 'kind', name='uq_agent_learning_result'))
    op.create_index('ix_agent_learning_owner', 'agent_learning_continuations', ['owner_id', 'run_id'])


def downgrade():
    op.drop_table('agent_learning_continuations')
    op.drop_table('agent_sandbox_leases')
    op.drop_table('agent_sandbox_cleanup')
    op.drop_table('agent_sandbox_budgets')
