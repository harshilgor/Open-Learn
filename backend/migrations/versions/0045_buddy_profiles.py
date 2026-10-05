"""Account-owned companions, assignments and historical conversation attribution."""
import sqlalchemy as sa
from alembic import op

revision = '0045_buddy_profiles'
down_revision = '0044_agent_sandbox_learning'
branch_labels = depends_on = None

def upgrade():
    for name, extra in (
        ('buddy_profiles', [sa.Column('name', sa.String(80), nullable=False), sa.Column('payload', sa.Text(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('archived', sa.Boolean(), nullable=False)]),
        ('buddy_accounts', [sa.Column('default_buddy_id', sa.String(160), nullable=False)]),
        ('buddy_courses', [sa.Column('buddy_id', sa.String(160), nullable=False), sa.Column('revision', sa.Integer(), nullable=False)]),
        ('buddy_chats', [sa.Column('buddy_id', sa.String(160), nullable=False),sa.Column('presentation',sa.String(32),nullable=False,server_default='conversation')]),
        ('buddy_classes', [sa.Column('buddy_id', sa.String(160), nullable=False)]),
        ('buddy_responsibilities', [sa.Column('buddy_id',sa.String(160),nullable=False),sa.Column('course_id',sa.String(160)),sa.Column('kind',sa.String(32),nullable=False)]),
    ):
        op.create_table(name, sa.Column('id', sa.String(160), primary_key=True), sa.Column('owner_id', sa.String(160), nullable=False), *extra)
        op.create_index('ix_'+name+'_owner', name, ['owner_id'])

def downgrade():
    for name in ('buddy_responsibilities','buddy_classes','buddy_chats', 'buddy_courses', 'buddy_accounts', 'buddy_profiles'):
        op.drop_table(name)
