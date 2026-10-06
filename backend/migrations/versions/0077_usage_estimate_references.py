"""Persist short-lived owner-scoped task estimate references."""
from alembic import op
import sqlalchemy as sa

revision = "0077_usage_estimate_references"
down_revision = "0076_usage_task_caps"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "usage_estimate_refs",
        sa.Column("reference_hash", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="ck_usage_estimate_expiry"),
    )
    op.create_index(
        "ix_usage_estimate_owner_expiry",
        "usage_estimate_refs",
        ["owner_id", "expires_at"],
    )


def downgrade():
    op.drop_index("ix_usage_estimate_owner_expiry", table_name="usage_estimate_refs")
    op.drop_table("usage_estimate_refs")
