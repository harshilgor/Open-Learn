"""Repair early scheduling schemas without recreating responsibility rows."""
import sqlalchemy as sa
from alembic import op
revision='0050_agent_worker_compat'
down_revision='0049_mobile_release'
branch_labels=depends_on=None

def upgrade():
    columns={column['name'] for column in sa.inspect(op.get_bind()).get_columns('agent_responsibilities')}
    for name in ['event_after','last_checked']:
        if name not in columns:
            op.add_column('agent_responsibilities',sa.Column(name,sa.Float(),nullable=False,server_default='0'))

def downgrade():
    # These columns belong to 0046 on fresh installs; retain compatibility data.
    pass
