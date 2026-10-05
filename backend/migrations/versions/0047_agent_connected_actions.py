"""Merge concurrent additive branches; reviewed actions and bounded children."""
import sqlalchemy as sa
from alembic import op
revision = '0047_agent_connected_actions'
down_revision = ('0046_agent_responsibilities', '0046_buddy_navigation')
branch_labels = depends_on = None

def upgrade():
    definitions = {
        'agent_app_connections': [('revision', sa.Integer(), False), ('status', sa.String(40), False), ('payload', sa.Text(), False), ('secret', sa.Text(), False)],
        'agent_app_oauth': [('state_hash', sa.String(64), False), ('expires_at', sa.Float(), False), ('payload', sa.Text(), False)],
        'agent_connector_intakes': [('request_hash', sa.String(64), False), ('payload', sa.Text(), False)],
        'agent_action_drafts': [('run_id', sa.String(160), False), ('input_revision', sa.Integer(), False), ('connection_id', sa.String(160), False), ('connection_revision', sa.Integer(), False), ('revision', sa.Integer(), False), ('status', sa.String(40), False), ('action_hash', sa.String(64), False), ('expires_at', sa.Float(), False), ('payload', sa.Text(), False)],
        'agent_action_operations': [('draft_id', sa.String(160), False), ('status', sa.String(40), False), ('payload', sa.Text(), False), ('updated_at', sa.Float(), False)],
        'agent_action_decisions': [('draft_id', sa.String(160), False), ('request_hash', sa.String(64), False), ('payload', sa.Text(), False)],
        'agent_standing_grants': [('status', sa.String(40), False), ('payload', sa.Text(), False)],
        'agent_delegation_budgets': [('run_id', sa.String(160), False), ('input_revision', sa.Integer(), False), ('children_remaining', sa.Integer(), False), ('calls_remaining', sa.Integer(), False), ('tokens_remaining', sa.Integer(), False)],
        'agent_delegated_children': [('parent_id', sa.String(160), False), ('child_id', sa.String(160), True), ('input_revision', sa.Integer(), False), ('status', sa.String(40), False), ('request_hash', sa.String(64), False), ('payload', sa.Text(), False)],
        'agent_delegation_charges': [('budget_id', sa.String(160), False), ('kind', sa.String(40), False), ('amount', sa.Integer(), False)],
    }
    for name, fields in definitions.items():
        op.create_table(name, sa.Column('id', sa.String(160), primary_key=True), sa.Column('owner_id', sa.String(160), nullable=False), sa.Column('created_at', sa.Float(), nullable=False), *[sa.Column(key, typ, nullable=nullable) for key,typ,nullable in fields])
        op.create_index('ix_'+name+'_owner',name,['owner_id'])
    op.create_index('ix_agent_actions_ready','agent_action_operations',['status','updated_at'])
    op.create_index('ix_agent_children_parent','agent_delegated_children',['owner_id','parent_id'])

def downgrade():
    for name in ['agent_delegation_charges','agent_delegated_children','agent_delegation_budgets','agent_standing_grants','agent_action_decisions','agent_action_operations','agent_action_drafts','agent_connector_intakes','agent_app_oauth','agent_app_connections']:
        op.drop_table(name)
