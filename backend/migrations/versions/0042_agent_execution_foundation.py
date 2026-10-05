"""Add conversational execution without copying legacy browser runs."""
import sqlalchemy as sa
from alembic import op

revision = '0042_agent_execution_foundation'
down_revision = '0041_browser_assistant'
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column('runtime_owner', sa.String(40), nullable=False, server_default='browser_legacy'),
        sa.Column('event_sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('desired_input_revision', sa.Integer(), nullable=False, server_default='1'),
    ): op.add_column('assistant_runs', column)
    op.execute('UPDATE assistant_runs SET event_sequence=(SELECT COALESCE(MAX(sequence),0) FROM assistant_events WHERE run_id=assistant_runs.id)')
    op.create_index('ix_assistant_runtime_session', 'assistant_runs', ['owner_id', 'runtime_owner', 'session_id', 'status'])
    def table(name, *columns, constraints=()):
        op.create_table(name, sa.Column('id', sa.String(160), primary_key=True),
            sa.Column('owner_id', sa.String(160), nullable=False), *columns, *constraints)
        op.create_index('ix_' + name + '_owner', name, ['owner_id'])
    table('agent_messages', sa.Column('session_id', sa.String(160), nullable=False),
        sa.Column('client_message_id', sa.String(160), nullable=False), sa.Column('command_key', sa.String(200), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('response', sa.Text(), nullable=False), sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('owner_id', 'client_message_id', name='uq_agent_message_client'),
                     sa.UniqueConstraint('owner_id', 'command_key', name='uq_agent_message_key')))
    table('agent_commands', sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('cursor', sa.Integer(), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False), sa.Column('ack', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('run_id', 'cursor', name='uq_agent_command_cursor'),))
    table('agent_input_requests', sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('session_id', sa.String(160), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False))
    table('agent_checkpoints', sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('run_id', 'version', name='uq_agent_checkpoint'),))
    table('agent_operations', sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('input_revision', sa.Integer(), nullable=False), sa.Column('step_key', sa.String(160), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('run_id', 'input_revision', 'step_key', name='uq_agent_operation'),))
    table('agent_artifacts', sa.Column('run_id', sa.String(160), nullable=False),
        sa.Column('operation_id', sa.String(160), nullable=False), sa.Column('name', sa.String(160), nullable=False),
        sa.Column('object_key', sa.String(160), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('operation_id', 'name', name='uq_agent_output'),))
    table('agent_activity', sa.Column('session_id', sa.String(160), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('item_key', sa.String(200), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False), sa.Column('created_at', sa.Float(), nullable=False),
        constraints=(sa.UniqueConstraint('owner_id', 'session_id', 'sequence', name='uq_agent_activity_sequence'),
                     sa.UniqueConstraint('owner_id', 'session_id', 'item_key', name='uq_agent_activity_item')))
    op.create_table('agent_activity_cursors', sa.Column('owner_id', sa.String(160), primary_key=True),
        sa.Column('session_id', sa.String(160), primary_key=True), sa.Column('sequence', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('agent_activity_cursors')
    for name in ('agent_activity', 'agent_artifacts', 'agent_operations', 'agent_checkpoints', 'agent_input_requests', 'agent_commands', 'agent_messages'):
        op.drop_table(name)
    op.drop_index('ix_assistant_runtime_session', table_name='assistant_runs')
    for name in ('desired_input_revision', 'event_sequence', 'runtime_owner'): op.drop_column('assistant_runs', name)
