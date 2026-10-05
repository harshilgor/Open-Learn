"""Durable task-scoped research references independent of response aliases."""
import sqlalchemy as sa
from alembic import op

revision = "0043_agent_research"
down_revision = "0042_agent_execution_foundation"
branch_labels = depends_on = None


def upgrade():
    op.create_table("agent_research_runs",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("run_id", sa.String(160), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("run_id", "input_revision", name="uq_agent_research_run"))
    op.create_index("ix_agent_research_runs_owner", "agent_research_runs", ["owner_id", "run_id"])
    op.create_table("agent_research_sources",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("run_id", sa.String(160), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(160), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("content_expires_at", sa.Float(), nullable=False),
        sa.Column("deleted_at", sa.Float()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("run_id", "input_revision", "evidence_id", "content_hash", name="uq_agent_research_source"))
    op.create_index("ix_agent_research_sources_task", "agent_research_sources", ["owner_id", "run_id", "input_revision"])
    op.create_index("ix_agent_research_sources_expiry", "agent_research_sources", ["content_expires_at", "deleted_at"])


def downgrade():
    op.drop_table("agent_research_sources")
    op.drop_table("agent_research_runs")
