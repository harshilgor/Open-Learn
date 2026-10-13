"""Add source documents and auditable agent task records."""

import sqlalchemy as sa
from alembic import op

revision = "0005_agent_tasks"
down_revision = "0004_teaching_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "agent_documents" not in tables:
        op.create_table(
            "agent_documents",
            sa.Column("id", sa.String(160), primary_key=True),
            sa.Column("learner_id", sa.String(120), sa.ForeignKey("learners.id"), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(120), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_documents_learner_created", "agent_documents", ["learner_id", "created_at"])
    if "agent_tasks" not in tables:
        op.create_table(
            "agent_tasks",
            sa.Column("id", sa.String(160), primary_key=True),
            sa.Column("learner_id", sa.String(120), sa.ForeignKey("learners.id"), nullable=False),
            sa.Column("idempotency_key", sa.String(200)),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("uq_agent_task_idempotency", "agent_tasks", ["learner_id", "idempotency_key"], unique=True)
        op.create_index("ix_agent_tasks_learner_updated", "agent_tasks", ["learner_id", "updated_at"])
    if "agent_task_events" not in tables:
        op.create_table(
            "agent_task_events",
            sa.Column("id", sa.String(160), primary_key=True),
            sa.Column("task_id", sa.String(160), sa.ForeignKey("agent_tasks.id"), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
        )
        op.create_index("uq_agent_task_event_sequence", "agent_task_events", ["task_id", "sequence"], unique=True)

    note_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("notes")}
    if "document_id" not in note_columns:
        op.add_column("notes", sa.Column("document_id", sa.String(160), nullable=True))


def downgrade() -> None:
    # Preserve generated learner artifacts and task audit history.
    pass
