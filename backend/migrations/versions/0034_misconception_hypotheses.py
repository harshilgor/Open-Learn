"""Tentative explanations with diagnostic and correction history."""
import sqlalchemy as sa
from alembic import op
revision = "0034_misconception_hypotheses"
down_revision = "0033_unified_learner_state"
branch_labels = depends_on = None


def upgrade():
    op.create_table("diagnostic_hypotheses", sa.Column("owner_id", sa.String(160), primary_key=True), sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("concept_id", sa.String(160), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("payload", sa.Text(), nullable=False))
    op.create_index("ix_diagnostic_hypotheses_concept", "diagnostic_hypotheses", ["owner_id", "concept_id", "status"])
    op.create_table("hypothesis_history", sa.Column("owner_id", sa.String(160), primary_key=True), sa.Column("hypothesis_id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True), sa.Column("payload", sa.Text(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False))
    op.create_table("hypothesis_analyses", sa.Column("owner_id", sa.String(160), primary_key=True), sa.Column("event_id", sa.String(160), primary_key=True), sa.Column("payload", sa.Text(), nullable=False))
    op.create_table("hypothesis_checks", sa.Column("owner_id", sa.String(160), primary_key=True), sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("hypothesis_id", sa.String(160), nullable=False), sa.Column("quiz_id", sa.String(160), nullable=False), sa.Column("payload", sa.Text(), nullable=False),
        sa.UniqueConstraint("owner_id", "quiz_id"))


def downgrade():
    for name in ("hypothesis_checks", "hypothesis_analyses", "hypothesis_history", "diagnostic_hypotheses"):
        op.drop_table(name)
