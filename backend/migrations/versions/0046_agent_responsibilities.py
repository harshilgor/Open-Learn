"""Durable responsibility scheduling and scoped operational notes."""
import sqlalchemy as sa
from alembic import op
revision='0046_agent_responsibilities'
down_revision='0045_buddy_profiles'
branch_labels=depends_on=None

def upgrade():
    op.create_table('agent_responsibilities',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('session_id',sa.String(160),nullable=False),sa.Column('course_id',sa.String(160),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('next_due',sa.Float()),sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_agent_responsibility_due','agent_responsibilities',['status','next_due'])
    op.add_column('agent_responsibilities',sa.Column('event_after',sa.Float(),nullable=False,server_default='0'))
    op.add_column('agent_responsibilities',sa.Column('last_checked',sa.Float(),nullable=False,server_default='0'))
    op.create_table('agent_responsibility_occurrences',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('responsibility_id',sa.String(160),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('run_id',sa.String(160)),sa.Column('status',sa.String(32),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_agent_occurrence_scope','agent_responsibility_occurrences',['responsibility_id','created_at'])
    op.create_table('agent_operational_notes',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('responsibility_id',sa.String(160),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('payload',sa.Text(),nullable=False))

def downgrade():
    for name in ['agent_operational_notes','agent_responsibility_occurrences','agent_responsibilities']:op.drop_table(name)
