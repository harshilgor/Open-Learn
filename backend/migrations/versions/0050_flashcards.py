"""Versioned shared flashcard entities, commands and preferences."""
import sqlalchemy as sa
from alembic import op
revision = '0050_flashcards'
down_revision = '0049_mobile_release'
branch_labels = depends_on = None
TABLES = ('flashcard_decks','flashcards','flashcard_versions','flashcard_generation_candidates','flashcard_review_sessions','flashcard_review_attempts','flashcard_schedule_state','flashcard_preferences')
def upgrade():
    for name in TABLES:
        op.create_table(name, sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('parent_id',sa.String(160)),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
        op.create_index('ix_'+name+'_owner_parent',name,['owner_id','parent_id'])
    op.create_table('flashcard_commands',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('target_id',sa.String(160),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
def downgrade():
    op.drop_table('flashcard_commands')
    for name in reversed(TABLES):op.drop_table(name)
