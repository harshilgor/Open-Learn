"""Learning objective and adjudication lookup boundaries.

Revision ID: 0036_learning_workflows
"""
from alembic import op

revision = "0036_learning_workflows"
down_revision = "0035_source_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_practice_owner_kind_parent", "practice_records", ["owner_id", "kind", "parent_id"])


def downgrade():
    op.drop_index("ix_practice_owner_kind_parent", table_name="practice_records")
