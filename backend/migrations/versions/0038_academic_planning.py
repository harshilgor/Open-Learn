"""Revisioned academic observations and executable study plans."""
import sqlalchemy as sa
from alembic import op
revision = '0038_academic_planning'
down_revision = '0036_learning_workflows'
branch_labels = depends_on = None


def upgrade():
    for name in ('academic_entities', 'academic_observations', 'readiness_snapshots', 'study_tasks', 'study_plan_revisions', 'canvas_connections', 'canvas_sync_runs'):
        op.create_table(name, sa.Column('owner_id', sa.String(160), primary_key=True), sa.Column('id', sa.String(160), primary_key=True), sa.Column('course_id', sa.String(160), nullable=True), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('payload', sa.Text(), nullable=False), sa.Column('created_at', sa.Float(), nullable=False))
        op.create_index('ix_' + name + '_course', name, ['owner_id', 'course_id'])


def downgrade():
    for name in reversed(('academic_entities', 'academic_observations', 'readiness_snapshots', 'study_tasks', 'study_plan_revisions', 'canvas_connections', 'canvas_sync_runs')):
        op.drop_table(name)
