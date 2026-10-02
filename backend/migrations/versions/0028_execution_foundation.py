"""Additive execution contracts on the existing learning job table.

This is independently implemented from 0027, not the unavailable Windows 0028.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_execution_foundation"
down_revision = "0027_lecture_capture_interrupted_repair"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("input_revision", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("safe_error_code", sa.String(80)),
        sa.Column("queue", sa.String(20), nullable=False, server_default="interactive"),
    ):
        op.add_column("learning_jobs", column)
    op.execute("UPDATE learning_jobs SET queue='batch' WHERE kind LIKE 'lecture_%'")
    op.create_index("ix_learning_job_ready", "learning_jobs", ["queue", "status", "next_retry_at"])
    op.create_table(
        "execution_outbox",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("delivered_at", sa.Float()),
        sa.UniqueConstraint("owner_id", "topic", "command_key", name="uq_execution_outbox_command"),
    )
    op.create_index("ix_execution_outbox_pending", "execution_outbox", ["delivered_at", "created_at"])
    op.create_table(
        "execution_watermarks",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("projection", sa.String(80), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.String(80), nullable=False),
    )


def downgrade():
    op.drop_table("execution_watermarks")
    op.drop_table("execution_outbox")
    op.drop_index("ix_learning_job_ready", table_name="learning_jobs")
    with op.batch_alter_table("learning_jobs") as batch:
        for name in ("input_revision", "attempt_count", "max_attempts", "next_retry_at", "progress", "cancel_requested", "safe_error_code", "queue"):
            batch.drop_column(name)
