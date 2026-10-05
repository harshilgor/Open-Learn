"""Persist In-Class resource intents and course source preferences."""
import sqlalchemy as sa
from alembic import op


revision = '0066_class_resource_intents'
down_revision = '0065_class_live_transcript_timing'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'class_resource_intents',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('need_id', sa.String(160), nullable=False),
        sa.Column('course_id', sa.String(160), sa.ForeignKey('courses.id', ondelete='SET NULL')),
        sa.Column('window_id', sa.String(160), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False, server_default='materials'),
        sa.Column('prompt', sa.Text(), nullable=False, server_default=''),
        sa.Column('query', sa.Text(), nullable=False, server_default=''),
        sa.Column('required_fields', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('options', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(24), nullable=False, server_default='open'),
        sa.Column('selected_connector', sa.String(32)),
        sa.Column('selected_resource', sa.Text()),
        sa.Column('selected_command_id', sa.String(160)),
        sa.Column('request_hash', sa.String(64)),
        sa.Column('material_version_id', sa.String(160)),
        sa.Column('last_error', sa.String(500)),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_id', 'class_id', 'need_id', name='uq_class_resource_intent_need'),
        sa.CheckConstraint("status IN ('open','resolving','resolved','closed')", name='ck_class_resource_intent_status'),
        sa.CheckConstraint(
            "selected_connector IS NULL OR selected_connector IN ('library','upload','url','drive','canvas','blackboard','moodle')",
            name='ck_class_resource_intent_connector',
        ),
    )
    op.create_index('ix_class_resource_intents_owner_course', 'class_resource_intents', ['owner_id', 'course_id', 'status'])
    op.create_index('ix_class_resource_intents_owner_class', 'class_resource_intents', ['owner_id', 'class_id', 'updated_at'])

    op.create_table(
        'course_resource_preferences',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('course_id', sa.String(160), sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_id', 'course_id', name='uq_course_resource_preferences_owner_course'),
    )
    op.create_index('ix_course_resource_preferences_owner', 'course_resource_preferences', ['owner_id', 'course_id'])


def downgrade():
    op.drop_index('ix_course_resource_preferences_owner', table_name='course_resource_preferences')
    op.drop_table('course_resource_preferences')
    op.drop_index('ix_class_resource_intents_owner_class', table_name='class_resource_intents')
    op.drop_index('ix_class_resource_intents_owner_course', table_name='class_resource_intents')
    op.drop_table('class_resource_intents')
