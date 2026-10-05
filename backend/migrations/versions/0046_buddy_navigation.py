"""Persist companion conversation restoration across authenticated devices."""
import sqlalchemy as sa
from alembic import op
revision='0046_buddy_navigation'
down_revision='0045_buddy_profiles'
branch_labels=depends_on=None
def upgrade():
    op.create_table('buddy_navigation',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('last_chat_id',sa.String(160),nullable=False))
    op.create_index('ix_buddy_navigation_owner','buddy_navigation',['owner_id'])
def downgrade():op.drop_table('buddy_navigation')
