"""Owner-scoped immutable decisions and dependency invalidations."""
from alembic import op
import sqlalchemy as sa

revision = "0029_shared_contracts"
down_revision = "0028_execution_foundation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "decision_snapshots",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_revision", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_decision_revision"),
        sa.CheckConstraint("schema_revision = 1", name="ck_decision_schema"),
    )
    op.create_index("ix_decision_owner_purpose_time", "decision_snapshots", ["owner_id", "purpose", "created_at", "id"])
    op.create_table(
        "decision_dependencies",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("snapshot_id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(100), primary_key=True),
        sa.Column("record_id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "snapshot_id"], ["decision_snapshots.owner_id", "decision_snapshots.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 1", name="ck_dependency_revision"),
    )
    op.create_index("ix_decision_dependency_lookup", "decision_dependencies", ["owner_id", "kind", "record_id", "revision"])
    op.create_table(
        "contract_invalidations",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("record_id", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("schema_revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_invalidation_revision"),
        sa.CheckConstraint("schema_revision = 1", name="ck_invalidation_schema"),
    )
    op.create_index("ix_contract_invalidation_lookup", "contract_invalidations", ["owner_id", "kind", "record_id", "revision"])


def downgrade():
    op.drop_table("contract_invalidations")
    op.drop_table("decision_dependencies")
    op.drop_table("decision_snapshots")
