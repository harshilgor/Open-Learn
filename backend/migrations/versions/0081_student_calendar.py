"""Owned calendar events, permissions and durable mutation receipts."""
from alembic import op
import sqlalchemy as sa

revision = '0081_student_calendar'
down_revision = '0080_agent_retention_floor'
branch_labels = depends_on = None


def upgrade():
    for name in ('calendar_calendars', 'calendar_events', 'calendar_overrides', 'calendar_permissions', 'calendar_proposals', 'calendar_operations', 'calendar_preferences', 'calendar_sync'):
        op.create_table(name,
            sa.Column('id', sa.String(160), primary_key=True),
            sa.Column('owner_id', sa.String(160), nullable=False),
            sa.Column('parent_id', sa.String(160)),
            sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('status', sa.String(40), nullable=False, server_default='active'),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.Column('updated_at', sa.Float(), nullable=False),
            sa.Column('payload', sa.Text(), nullable=False))
        op.create_index('ix_' + name + '_owner_parent', name, ['owner_id', 'parent_id', 'status'])


def downgrade():
    for name in reversed(('calendar_calendars', 'calendar_events', 'calendar_overrides', 'calendar_permissions', 'calendar_proposals', 'calendar_operations', 'calendar_preferences', 'calendar_sync')):
        op.drop_table(name)
