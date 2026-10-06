"""Index stable in-class output paging."""
from alembic import op


revision = '0056_class_output_page_index'
down_revision = '0055_resumable_material_uploads'
branch_labels = depends_on = None


def upgrade():
    op.create_index(
        'ix_class_output_page',
        'class_output_versions',
        ['owner_id', 'class_id', 'created_at', 'id'],
    )


def downgrade():
    op.drop_index('ix_class_output_page', table_name='class_output_versions')
