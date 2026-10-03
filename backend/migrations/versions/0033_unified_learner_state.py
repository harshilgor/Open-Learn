"""Capability projections and a single capability review schedule."""
from alembic import op
import sqlalchemy as sa

revision = "0033_unified_learner_state"
down_revision = "0032_stable_concepts"
branch_labels = depends_on = None


def upgrade():
    op.create_table("capability_projections",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("concept_id", sa.String(160), primary_key=True),
        sa.Column("capability", sa.String(30), primary_key=True),
        sa.Column("event_watermark", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False))


def downgrade():
    op.drop_table("capability_projections")
