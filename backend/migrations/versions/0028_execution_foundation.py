"""Durable execution metadata and transactional delivery."""
from alembic import op
import sqlalchemy as sa

revision = "0028_execution_foundation"
down_revision = "0027_lecture_capture_interrupted_repair"
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column("input_revision", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_retry_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80), nullable=True),
        # Compatibility fields for the separately supervised worker CLI.
        # The in-process worker uses cancellation_requested/error_code; both
        # paths write both representations during the transition.
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("queue", sa.String(20), nullable=False, server_default="interactive"),
    ):
        op.add_column("learning_jobs", column)
    op.create_index("ix_learning_jobs_ready", "learning_jobs", ["status", "next_retry_at", "kind"])
    op.create_index("ix_learning_job_ready", "learning_jobs", ["queue", "status", "next_retry_at"])
    op.create_table("execution_outbox",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(160), nullable=False),
        sa.Column("dedup_key", sa.String(300), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("delivered_at", sa.Float()),
        sa.UniqueConstraint("owner_id", "dedup_key", name="uq_outbox_owner_key"))
    op.create_index("ix_execution_outbox_delivery", "execution_outbox", ["delivered_at", "created_at"])
    op.create_table("projection_watermarks",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("projection", sa.String(100), primary_key=True),
        sa.Column("target_id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False))


def downgrade():
    op.drop_table("projection_watermarks")
    op.drop_table("execution_outbox")
    op.drop_index("ix_learning_jobs_ready", table_name="learning_jobs")
    op.drop_index("ix_learning_job_ready", table_name="learning_jobs")
    for name in ("queue", "safe_error_code", "cancel_requested", "error_code", "cancellation_requested", "progress", "next_retry_at", "max_attempts", "attempt_count", "input_revision"):
        op.drop_column("learning_jobs", name)
