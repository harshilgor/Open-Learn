"""Owner-scoped idempotent short voice transcription receipts."""
import sqlalchemy as sa
from alembic import op
revision='0049_mobile_release'
down_revision='0048_in_class'
branch_labels=depends_on=None
def upgrade():
    op.create_table('mobile_voice_receipts',sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False),sa.Column('updated_at',sa.Float(),nullable=False))
    op.create_index('ix_mobile_voice_budget','mobile_voice_receipts',['owner_id','created_at'])
def downgrade():op.drop_table('mobile_voice_receipts')
