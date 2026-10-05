"""Durable browser assistant, evidence, connections and reminder delivery."""
import sqlalchemy as sa
from alembic import op

revision = '0041_browser_assistant'
down_revision = '0040_cloud_foundation_compat'
branch_labels = depends_on = None


def table(name, *columns, constraints=()):
    op.create_table(name, sa.Column('id', sa.String(160), primary_key=True),
                    sa.Column('owner_id', sa.String(160), nullable=False),
                    *columns, *constraints)
    op.create_index('ix_' + name + '_owner', name, ['owner_id'])


def upgrade():
    table('site_connections', sa.Column('revision', sa.Integer(), nullable=False),
          sa.Column('status', sa.String(40), nullable=False), sa.Column('origin', sa.String(2048), nullable=False),
          sa.Column('device_id', sa.String(160)), sa.Column('payload', sa.Text(), nullable=False),
          sa.Column('created_at', sa.Float(), nullable=False), sa.Column('updated_at', sa.Float(), nullable=False))
    table('assistant_runs', sa.Column('revision', sa.Integer(), nullable=False),
          sa.Column('connection_id', sa.String(160)), sa.Column('session_id', sa.String(160)),
          sa.Column('command_key', sa.String(200), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
          sa.Column('status', sa.String(40), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          sa.Column('created_at', sa.Float(), nullable=False), sa.Column('updated_at', sa.Float(), nullable=False),
          constraints=(sa.UniqueConstraint('owner_id', 'command_key', name='uq_assistant_command'),))
    op.create_index('ix_assistant_connection_state', 'assistant_runs', ['owner_id', 'connection_id', 'status'])
    table('assistant_events', sa.Column('run_id', sa.String(160), nullable=False),
          sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          sa.Column('created_at', sa.Float(), nullable=False),
          constraints=(sa.UniqueConstraint('run_id', 'sequence', name='uq_assistant_event_sequence'),))
    table('assistant_steps', sa.Column('run_id', sa.String(160), nullable=False),
          sa.Column('job_id', sa.String(160), nullable=False), sa.Column('generation', sa.String(160), nullable=False),
          sa.Column('connection_revision', sa.Integer(), nullable=False), sa.Column('device_id', sa.String(160)),
          sa.Column('status', sa.String(40), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          sa.Column('result', sa.Text()), sa.Column('expires_at', sa.Float(), nullable=False),
          sa.Column('created_at', sa.Float(), nullable=False),
          constraints=(sa.UniqueConstraint('run_id', 'job_id', name='uq_assistant_step_job'),))
    op.create_index('ix_browser_device_pending', 'assistant_steps', ['device_id', 'status', 'expires_at'])
    table('browser_snapshots', sa.Column('run_id', sa.String(160), nullable=False),
          sa.Column('connection_id', sa.String(160), nullable=False), sa.Column('url', sa.String(2048), nullable=False),
          sa.Column('sha256', sa.String(64), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          sa.Column('created_at', sa.Float(), nullable=False), sa.Column('expires_at', sa.Float(), nullable=False))
    table('browser_session_leases', sa.Column('run_id', sa.String(160), nullable=False),
          sa.Column('connection_id', sa.String(160), nullable=False), sa.Column('provider_session', sa.String(160)),
          sa.Column('status', sa.String(40), nullable=False), sa.Column('expires_at', sa.Float(), nullable=False),
          sa.Column('payload', sa.Text(), nullable=False),
          constraints=(sa.UniqueConstraint('run_id', name='uq_browser_run_session'),))
    table('external_course_links', sa.Column('connection_id', sa.String(160), nullable=False),
          sa.Column('external_id', sa.String(160), nullable=False), sa.Column('term', sa.String(160), nullable=False),
          sa.Column('course_id', sa.String(160), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          constraints=(sa.UniqueConstraint('owner_id', 'connection_id', 'external_id', 'term', name='uq_external_course'),))
    table('academic_scan_coverage', sa.Column('run_id', sa.String(160), nullable=False),
          sa.Column('course_id', sa.String(160)), sa.Column('resource_key', sa.String(240), nullable=False),
          sa.Column('complete', sa.Boolean(), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          constraints=(sa.UniqueConstraint('run_id', 'resource_key', name='uq_scan_coverage'),))
    table('reminder_policies', sa.Column('revision', sa.Integer(), nullable=False),
          sa.Column('active', sa.Boolean(), nullable=False), sa.Column('payload', sa.Text(), nullable=False))
    table('reminders', sa.Column('entity_id', sa.String(160), nullable=False),
          sa.Column('entity_revision', sa.Integer(), nullable=False), sa.Column('policy_id', sa.String(160), nullable=False),
          sa.Column('policy_revision', sa.Integer(), nullable=False), sa.Column('due_at', sa.Float(), nullable=False),
          sa.Column('status', sa.String(40), nullable=False), sa.Column('dedup_key', sa.String(64), nullable=False),
          sa.Column('payload', sa.Text(), nullable=False),
          constraints=(sa.UniqueConstraint('owner_id', 'dedup_key', name='uq_reminder_dedup'),))
    op.create_index('ix_reminders_due', 'reminders', ['status', 'due_at'])
    table('notification_deliveries', sa.Column('reminder_id', sa.String(160), nullable=False),
          sa.Column('channel', sa.String(30), nullable=False), sa.Column('status', sa.String(40), nullable=False),
          sa.Column('payload', sa.Text(), nullable=False), sa.Column('created_at', sa.Float(), nullable=False),
          constraints=(sa.UniqueConstraint('owner_id', 'reminder_id', 'channel', name='uq_notification_channel'),))
    table('notification_subscriptions', sa.Column('endpoint_hash', sa.String(64), nullable=False),
          sa.Column('active', sa.Boolean(), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
          constraints=(sa.UniqueConstraint('owner_id', 'endpoint_hash', name='uq_push_subscription'),))
    table('connection_refresh_schedules', sa.Column('connection_id', sa.String(160), nullable=False),
          sa.Column('revision', sa.Integer(), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
          sa.Column('next_due', sa.Float(), nullable=False), sa.Column('payload', sa.Text(), nullable=False))
    op.create_index('ix_refresh_due', 'connection_refresh_schedules', ['active', 'next_due'])
    table('browser_provider_cleanup', sa.Column('context_id', sa.String(160)),
          sa.Column('session_id', sa.String(160)), sa.Column('created_at', sa.Float(), nullable=False))
    table('assistant_objects', sa.Column('object_key', sa.String(160), nullable=False),
          sa.Column('sha256', sa.String(64), nullable=False), sa.Column('expires_at', sa.Float(), nullable=False))


def downgrade():
    for name in reversed(('site_connections', 'assistant_runs', 'assistant_events', 'assistant_steps',
                          'browser_snapshots', 'browser_session_leases', 'external_course_links',
                          'academic_scan_coverage', 'reminder_policies', 'reminders', 'notification_deliveries',
                          'notification_subscriptions', 'connection_refresh_schedules', 'browser_provider_cleanup', 'assistant_objects')):
        op.drop_table(name)
