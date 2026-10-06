"""Durable owner-scoped material acquisition for class NeedInfo."""
import sqlalchemy as sa
from alembic import op

revision = '0054_class_material_intakes'
down_revision = '0053_class_processing_metrics'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'class_material_intakes',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('need_id', sa.String(160), nullable=False),
        sa.Column('command_id', sa.String(160), nullable=False),
        sa.Column('source_kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('material_id', sa.String(160)),
        sa.Column('version_id', sa.String(160)),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('lease_expires', sa.Float()),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_id', 'class_id', 'need_id', 'command_id', name='uq_class_material_intake_command'),
    )
    op.create_index('ix_class_material_intakes_owner_class', 'class_material_intakes', ['owner_id', 'class_id'])
    op.create_index('ix_class_material_intakes_status_lease', 'class_material_intakes', ['status', 'lease_expires'])
    op.create_index(
        'uq_class_material_intakes_active_need',
        'class_material_intakes',
        ['owner_id', 'class_id', 'need_id'],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('attached','failed')"),
        sqlite_where=sa.text("status NOT IN ('attached','failed')"),
    )


def downgrade():
    op.drop_index('uq_class_material_intakes_active_need', table_name='class_material_intakes')
    op.drop_index('ix_class_material_intakes_status_lease', table_name='class_material_intakes')
    op.drop_index('ix_class_material_intakes_owner_class', table_name='class_material_intakes')
    op.drop_table('class_material_intakes')
