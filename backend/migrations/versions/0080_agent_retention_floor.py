"""Track the oldest replayable agent activity cursor."""
from alembic import op
import sqlalchemy as sa

revision = '0080_agent_retention_floor'
down_revision = '0079_voice_room_cleanup'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('agent_activity_cursors') as batch:
        batch.add_column(sa.Column('pruned_through', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('agent_activity_cursors') as batch:
        batch.drop_column('pruned_through')
