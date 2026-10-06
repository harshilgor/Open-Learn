"""Persist successful media cleanup so failed room deletion can retry."""
from alembic import op
import sqlalchemy as sa

revision = '0079_voice_room_cleanup'
down_revision = '0078_usage_test_identity'
branch_labels = depends_on = None


def upgrade():
    op.add_column('voice_sessions', sa.Column('room_closed_at', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('voice_sessions', 'room_closed_at')
