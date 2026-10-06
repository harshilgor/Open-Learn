"""Snapshot usage caps and retain provider, receipt, and operator audit data."""
from alembic import op
import sqlalchemy as sa

revision = '0074_usage_accounting_hardening'
down_revision = '0073_unified_usage'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('usage_accounts') as batch:
        batch.add_column(sa.Column('status', sa.String(24), nullable=False, server_default='active'))
        batch.add_column(sa.Column('plan_id', sa.String(80), nullable=False, server_default='free-v1'))
        batch.add_column(sa.Column('current_period_id', sa.String(160),
                                   sa.ForeignKey('usage_periods.id', name='fk_usage_account_current_period'), nullable=True))
    with op.batch_alter_table('usage_platform_periods') as batch:
        batch.add_column(sa.Column('budget_nano', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('cleanup_used_nano', sa.BigInteger(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('cleanup_held_nano', sa.BigInteger(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('blocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('usage_reservations') as batch:
        batch.add_column(sa.Column('provider', sa.String(80), nullable=True))
        batch.add_column(sa.Column('model', sa.String(160), nullable=True))
        batch.add_column(sa.Column('provider_rate_version', sa.String(80), nullable=True))
        batch.add_column(sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'))
        batch.add_column(sa.Column('lease_generation', sa.Integer(), nullable=False, server_default='1'))
        batch.add_column(sa.Column('dispatched_at', sa.Float(), nullable=True))
        batch.add_column(sa.Column('settled_at', sa.Float(), nullable=True))
        batch.add_column(sa.Column('receipt_id', sa.String(200), nullable=True))
        batch.add_column(sa.Column('receipt_at', sa.Float(), nullable=True))
    with op.batch_alter_table('usage_events') as batch:
        batch.add_column(sa.Column('provider', sa.String(80), nullable=True))
        batch.add_column(sa.Column('model', sa.String(160), nullable=True))
        batch.add_column(sa.Column('provider_rate_version', sa.String(80), nullable=True))
        batch.add_column(sa.Column('currency', sa.String(3), nullable=False, server_default='USD'))
        batch.add_column(sa.Column('receipt_id', sa.String(200), nullable=True))
        batch.add_column(sa.Column('adjustment_of', sa.String(160), nullable=True))

    op.create_table('usage_adjustments',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('actor', sa.String(160), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('microcredits', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('reservation_id', sa.String(160), nullable=True),
    )
    op.create_index('ix_usage_adjustment_owner', 'usage_adjustments', ['owner_id', 'created_at'])
    op.create_table('usage_alerts',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=True),
        sa.Column('reservation_id', sa.String(160), nullable=True),
        sa.Column('kind', sa.String(60), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('acknowledged_at', sa.Float(), nullable=True),
    )
    op.create_index('ix_usage_alert_open', 'usage_alerts', ['acknowledged_at', 'created_at'])
    op.create_table('usage_provider_rate_cards',
        sa.Column('id', sa.String(400), primary_key=True),
        sa.Column('version', sa.String(80), nullable=False),
        sa.Column('provider', sa.String(240), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('version', 'provider', name='uq_usage_provider_rate_version'),
    )

    # The versioned policy card is immutable history; runtime only accepts this
    # audited identifier and never silently edits rates for older reservations.
    card = sa.table('usage_rate_cards', sa.column('id', sa.String), sa.column('payload', sa.Text))
    row={'id': 'reference-v1', 'payload':
        '{"currency":"USD","credit_usd":"0.001","uncached_input_usd_per_1000_tokens":"0.0005",'
        '"cached_input_usd_per_1000_tokens":"0.0001","output_usd_per_1000_tokens":"0.002",'
        '"stt_usd_per_minute":"0.01","tts_usd_per_1000_characters":"0.06",'
        '"voice_usd_per_minute":"0.015","browser_usd_per_minute":"0.005",'
        '"provider_liability_multiplier":"1.25"}'}
    bind=op.get_bind()
    if not bind.execute(sa.select(card.c.id).where(card.c.id==row['id'])).first():
        bind.execute(card.insert().values(**row))


def downgrade():
    op.drop_table('usage_provider_rate_cards')
    op.drop_index('ix_usage_alert_open', table_name='usage_alerts')
    op.drop_table('usage_alerts')
    op.drop_index('ix_usage_adjustment_owner', table_name='usage_adjustments')
    op.drop_table('usage_adjustments')
    with op.batch_alter_table('usage_events') as batch:
        for name in ('adjustment_of', 'receipt_id', 'currency', 'provider_rate_version', 'model', 'provider'):
            batch.drop_column(name)
    with op.batch_alter_table('usage_reservations') as batch:
        for name in ('receipt_at', 'receipt_id', 'settled_at', 'dispatched_at', 'lease_generation', 'attempt', 'provider_rate_version', 'model', 'provider'):
            batch.drop_column(name)
    with op.batch_alter_table('usage_platform_periods') as batch:
        for name in ('blocked', 'cleanup_held_nano', 'cleanup_used_nano', 'budget_nano'):
            batch.drop_column(name)
    with op.batch_alter_table('usage_accounts') as batch:
        for name in ('current_period_id', 'plan_id', 'status'):
            batch.drop_column(name)
