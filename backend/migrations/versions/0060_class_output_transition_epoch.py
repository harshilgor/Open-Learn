"""Fence durable class output transitions by their creation epoch."""
import sqlalchemy as sa
from alembic import op


revision = '0060_class_output_transition_epoch'
down_revision = '0059_class_event_revision_index'
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        'class_output_versions',
        sa.Column('created_processing_epoch', sa.Integer(), nullable=False, server_default='-1'),
    )
    op.create_index(
        'ix_class_output_transition_page',
        'class_output_versions',
        ['owner_id', 'class_id', 'created_processing_epoch', 'id'],
    )


def downgrade():
    op.drop_index('ix_class_output_transition_page', table_name='class_output_versions')
    op.drop_column('class_output_versions', 'created_processing_epoch')
