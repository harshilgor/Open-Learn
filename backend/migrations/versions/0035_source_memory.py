"""Immutable source memory and reproducible context manifests."""
from alembic import op
import sqlalchemy as sa
revision = '0035_source_memory'
down_revision = '0034_misconception_hypotheses'
branch_labels = depends_on = None

def upgrade():
    op.create_table('memory_sources', sa.Column('owner_id',sa.String(160),primary_key=True),sa.Column('id',sa.String(160),primary_key=True),sa.Column('kind',sa.String(40),nullable=False),sa.Column('course_id',sa.String(160)),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('deleted',sa.Boolean(),nullable=False),sa.Column('updated_at',sa.Float(),nullable=False))
    op.create_table('memory_revisions',sa.Column('owner_id',sa.String(160),primary_key=True),sa.Column('source_id',sa.String(160),primary_key=True),sa.Column('revision',sa.Integer(),primary_key=True),sa.Column('sha256',sa.String(64),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
    op.create_table('memory_derived',sa.Column('owner_id',sa.String(160),primary_key=True),sa.Column('id',sa.String(160),primary_key=True),sa.Column('kind',sa.String(40),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('valid',sa.Boolean(),nullable=False))
    op.create_table('context_manifests',sa.Column('owner_id',sa.String(160),primary_key=True),sa.Column('id',sa.String(160),primary_key=True),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))

def downgrade():
    for name in ('context_manifests','memory_derived','memory_revisions','memory_sources'): op.drop_table(name)
