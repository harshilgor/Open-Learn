"""Index durable, paged synthesis-tree construction."""
import sqlalchemy as sa
from alembic import op


revision = '0058_class_synthesis_plan_pages'
down_revision = '0057_class_window_membership'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'class_synthesis_plan_membership',
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('package_id', sa.String(160), sa.ForeignKey('class_input_windows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('modality', sa.String(24), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.String(160), sa.ForeignKey('class_input_windows.id', ondelete='CASCADE'), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'class_id', 'package_id', 'modality', 'level', 'ordinal',
                                name='pk_class_synthesis_plan_membership'),
        sa.UniqueConstraint('owner_id', 'class_id', 'package_id', 'modality', 'level', 'node_id',
                            name='uq_class_synthesis_plan_membership_node'),
        sa.CheckConstraint("modality IN ('summary','recall')", name='ck_class_synthesis_plan_membership_modality'),
        sa.CheckConstraint('level >= 0 AND ordinal >= 0', name='ck_class_synthesis_plan_membership_position'),
    )
    op.create_index(
        'ix_class_synthesis_plan_page',
        'class_synthesis_plan_membership',
        ['owner_id', 'class_id', 'package_id', 'modality', 'level', 'ordinal'],
    )


def downgrade():
    op.drop_index('ix_class_synthesis_plan_page', table_name='class_synthesis_plan_membership')
    op.drop_table('class_synthesis_plan_membership')
