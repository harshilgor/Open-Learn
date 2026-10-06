"""Unified allowance, reservations, liability and durable usage events."""
from alembic import op
import sqlalchemy as sa

revision = '0073_unified_usage'
down_revision = '0072_voice'
branch_labels = depends_on = None


def upgrade():
    op.create_table('usage_accounts', sa.Column('owner_id',sa.String(160),primary_key=True), sa.Column('revision',sa.BigInteger(),nullable=False,server_default='0'),sa.Column('blocked',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_table('usage_periods',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('starts_at',sa.Float(),nullable=False),sa.Column('expires_at',sa.Float(),nullable=False),sa.Column('grant_micro',sa.BigInteger(),nullable=False),sa.Column('used_micro',sa.BigInteger(),nullable=False,server_default='0'),sa.Column('held_micro',sa.BigInteger(),nullable=False,server_default='0'),sa.Column('policy_version',sa.String(80),nullable=False),sa.CheckConstraint('used_micro >= 0 AND held_micro >= 0 AND used_micro + held_micro <= grant_micro'),sa.UniqueConstraint('owner_id','starts_at'))
    op.create_index('ix_usage_period_owner','usage_periods',['owner_id','expires_at'])
    op.create_table('usage_platform_periods',sa.Column('id',sa.String(80),primary_key=True),sa.Column('used_nano',sa.BigInteger(),nullable=False,server_default='0'),sa.Column('held_nano',sa.BigInteger(),nullable=False,server_default='0'))
    op.create_table('usage_reservations',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('period_id',sa.String(160),sa.ForeignKey('usage_periods.id'),nullable=False),sa.Column('operation_key',sa.String(200),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('component',sa.String(32),nullable=False),sa.Column('root_id',sa.String(160),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('held_micro',sa.BigInteger(),nullable=False),sa.Column('liability_nano',sa.BigInteger(),nullable=False),sa.Column('day_id',sa.String(80),nullable=False),sa.Column('month_id',sa.String(80),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),sa.Column('deadline',sa.Float(),nullable=False),sa.Column('rate_version',sa.String(80),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.UniqueConstraint('owner_id','operation_key'))
    op.create_index('ix_usage_reservation_owner','usage_reservations',['owner_id','state'])
    op.create_table('usage_events',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('reservation_id',sa.String(160),nullable=False),sa.Column('period_id',sa.String(160),nullable=False),sa.Column('root_id',sa.String(160),nullable=False),sa.Column('component',sa.String(32),nullable=False),sa.Column('microcredits',sa.BigInteger(),nullable=False),sa.Column('cost_nano',sa.BigInteger(),nullable=False),sa.Column('source',sa.String(32),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_usage_event_owner','usage_events',['owner_id','created_at'])
    op.create_table('usage_rate_cards',sa.Column('id',sa.String(80),primary_key=True),sa.Column('payload',sa.Text(),nullable=False))
    op.create_table('usage_outbox',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('revision',sa.BigInteger(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),sa.Column('kind',sa.String(60),nullable=False),sa.Column('payload',sa.Text(),nullable=False))


def downgrade():
    for name in ('usage_outbox','usage_rate_cards','usage_events','usage_reservations','usage_platform_periods','usage_periods','usage_accounts'): op.drop_table(name)
