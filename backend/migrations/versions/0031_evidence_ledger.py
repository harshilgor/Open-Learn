"""Normalized immutable observations and owner-local receipt sequences."""
from alembic import op
import sqlalchemy as sa

revision = "0031_evidence_ledger"
down_revision = "0030_identity_sync"
branch_labels = depends_on = None


def upgrade():
    op.create_table("learning_event_sequences",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False))
    op.create_table("learning_event_ledger",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("deduplication_key", sa.String(300), nullable=False),
        sa.Column("occurred_at", sa.Float(), nullable=False),
        sa.Column("received_at", sa.Float(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("attempt_id", sa.String(160)),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.UniqueConstraint("owner_id", "sequence"),
        sa.UniqueConstraint("owner_id", "deduplication_key"))
    op.create_index("ix_ledger_attempt", "learning_event_ledger", ["owner_id", "attempt_id"])
    op.create_index("ix_ledger_occurrence", "learning_event_ledger", ["owner_id", "occurred_at", "id"])
    op.create_table("learning_event_concepts",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column("concept_id", sa.String(160), primary_key=True),
        sa.Column("capability", sa.String(30), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "event_id"], ["learning_event_ledger.owner_id", "learning_event_ledger.id"], ondelete="CASCADE"))
    op.create_index("ix_ledger_concept", "learning_event_concepts", ["owner_id", "concept_id", "capability"])


def downgrade():
    op.drop_table("learning_event_concepts")
    op.drop_table("learning_event_ledger")
    op.drop_table("learning_event_sequences")
