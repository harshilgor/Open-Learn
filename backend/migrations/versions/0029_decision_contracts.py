"""Owner-scoped immutable decisions with revision-specific invalidations."""
import sqlalchemy as sa
from alembic import op

revision = "0029_decision_contracts"
down_revision = "0028_execution_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("learning_decisions",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("workflow", sa.String(20), nullable=False),
        sa.Column("schema_revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("owner_id", "command_key", name="uq_learning_decision_command"),
        sa.UniqueConstraint("id", "owner_id", name="uq_learning_decision_owner"))
    op.create_table("learning_decision_dependencies",
        sa.Column("decision_id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(30), primary_key=True),
        sa.Column("entity_id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.String(160), primary_key=True),
        sa.ForeignKeyConstraint(["decision_id", "owner_id"], ["learning_decisions.id", "learning_decisions.owner_id"], ondelete="CASCADE"))
    op.create_index("ix_decision_dependency_entity", "learning_decision_dependencies", ["owner_id", "kind", "entity_id", "revision"])
    op.create_table("learning_decision_invalidations",
        sa.Column("decision_id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("correction_id", sa.String(160), primary_key=True),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["decision_id", "owner_id"], ["learning_decisions.id", "learning_decisions.owner_id"], ondelete="CASCADE"))


def downgrade():
    op.drop_table("learning_decision_invalidations")
    op.drop_table("learning_decision_dependencies")
    op.drop_table("learning_decisions")
