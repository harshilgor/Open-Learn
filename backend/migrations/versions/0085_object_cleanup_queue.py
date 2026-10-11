"""Retain failed object deletions for retry after upload records are removed."""
from alembic import op
import sqlalchemy as sa

revision = "0085_object_cleanup_queue"
down_revision = "0084_generation_shared_wakeups"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "object_cleanup_queue",
        sa.Column("object_key", sa.String(1000), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_object_cleanup_queue_due",
        "object_cleanup_queue",
        ["next_attempt_at", "created_at"],
    )


def downgrade():
    op.drop_index("ix_object_cleanup_queue_due", table_name="object_cleanup_queue")
    op.drop_table("object_cleanup_queue")
