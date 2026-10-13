"""Persist auditable operator actions and usage capability kill switches."""
from alembic import op
import sqlalchemy as sa

revision = '0075_usage_operator_controls'
down_revision = '0074_usage_accounting_hardening'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'usage_admin_audit',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('idempotency_key', sa.String(160), nullable=False, unique=True),
        sa.Column('actor', sa.String(160), nullable=False),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('target', sa.String(240), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
    )
    op.create_index('ix_usage_admin_audit_target', 'usage_admin_audit', ['target', 'created_at'])
    op.create_table(
        'usage_capability_controls',
        sa.Column('capability', sa.String(40), primary_key=True),
        sa.Column('disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('actor', sa.String(160), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table('usage_capability_controls')
    op.drop_index('ix_usage_admin_audit_target', table_name='usage_admin_audit')
    op.drop_table('usage_admin_audit')
