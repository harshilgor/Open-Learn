"""Persist low-cardinality live-branching operational measurements."""
from alembic import op
import sqlalchemy as sa

revision = "0083_live_branching_observability"
down_revision = "0082_live_branching"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "generation_acceptance_metrics",
        sa.Column("generation_id", sa.String(160), sa.ForeignKey("generation_records.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("acceptance_latency_ms", sa.Float(), nullable=False),
        sa.Column("measured_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "live_branching_metric_counters",
        sa.Column("name", sa.String(120), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "conversation_outbox_metric_snapshots",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("session_id", sa.String(160), sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("client_id", sa.String(80), primary_key=True),
        sa.Column("queued_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("choice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_pending_age_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_outbox_metric_snapshots_updated",
        "conversation_outbox_metric_snapshots",
        ["updated_at"],
    )


def downgrade():
    op.drop_index("ix_outbox_metric_snapshots_updated", table_name="conversation_outbox_metric_snapshots")
    op.drop_table("conversation_outbox_metric_snapshots")
    op.drop_table("live_branching_metric_counters")
    op.drop_table("generation_acceptance_metrics")
