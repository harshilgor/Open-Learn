"""Index class event revision boundaries and replay pages."""
from alembic import op


revision = '0059_class_event_revision_index'
down_revision = '0058_class_synthesis_plan_pages'
branch_labels = depends_on = None


def upgrade():
    op.create_index(
        'ix_class_session_events_owner_class_revision',
        'class_session_events',
        ['owner_id', 'class_id', 'revision'],
    )


def downgrade():
    op.drop_index('ix_class_session_events_owner_class_revision', table_name='class_session_events')
