"""Per-owner version of the learner-memory fact and episode sets.

Bumped in the same transaction as every change to which facts or episodes
are active (or to their static fields), so cached retrieval rows can be
revalidated with one primary-key read. Use tracking does not bump it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0087_memory_fact_versions"
down_revision = "0086_learner_memory"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "memory_fact_versions",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("memory_fact_versions")
