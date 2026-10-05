"""General reminders and resumable action ledger."""
from alembic import op
import sqlalchemy as sa

revision = '0052_chat_reminders'
down_revision = '0051_mobile_flashcards_merge'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('reminders') as batch:
        for name, typ in [('entity_id', sa.String(160)), ('entity_revision', sa.Integer()), ('policy_id', sa.String(160)), ('policy_revision', sa.Integer())]:
            batch.alter_column(name, existing_type=typ, nullable=True)
        batch.add_column(sa.Column('kind', sa.String(30), nullable=False, server_default='academic'))
        batch.add_column(sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('last_error', sa.String(100)))
    with op.batch_alter_table('reminder_policies') as batch:
        batch.add_column(sa.Column('kind', sa.String(30), nullable=False, server_default='academic'))
    op.create_index('ix_reminders_owner_status', 'reminders', ['owner_id', 'status'])
    op.create_table('reminder_action_runs',
        sa.Column('fire_id', sa.String(160), primary_key=True),
        sa.Column('step_id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('skill_id', sa.String(100), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('job_id', sa.String(160)),
        sa.Column('artifacts_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.Float()), sa.Column('finished_at', sa.Float()),
        sa.Column('error', sa.String(100)))
    op.create_table('reminder_preferences', sa.Column('owner_id', sa.String(160), primary_key=True), sa.Column('payload', sa.Text(), nullable=False))
    op.create_table('reminder_runtime', sa.Column('id', sa.String(30), primary_key=True), sa.Column('last_tick', sa.Float(), nullable=False), sa.Column('payload', sa.Text(), nullable=False))


def downgrade():
    for name in ('reminder_runtime', 'reminder_preferences', 'reminder_action_runs'):
        op.drop_table(name)
    op.drop_index('ix_reminders_owner_status', table_name='reminders')
    with op.batch_alter_table('reminder_policies') as batch:
        batch.drop_column('kind')
    with op.batch_alter_table('reminders') as batch:
        for name in ('kind', 'attempt_count', 'last_error'):
            batch.drop_column(name)
