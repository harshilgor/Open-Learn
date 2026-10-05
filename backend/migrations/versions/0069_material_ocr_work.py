"""Page-bounded resumable OCR work."""
import sqlalchemy as sa
from alembic import op
revision = '0069_material_ocr_work'
down_revision = '0068_material_v2'
branch_labels = depends_on = None

def upgrade():
    op.create_table('material_ocr_work',
        sa.Column('version_id', sa.String(160), sa.ForeignKey('material_versions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('page_index', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('source_revision', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease', sa.String(160)),
        sa.Column('expires', sa.Float()),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'))
    op.create_index('ix_material_ocr_claim', 'material_ocr_work', ['status', 'expires'])

def downgrade():
    op.drop_table('material_ocr_work')
