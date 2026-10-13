"""Per-fact learner opt-in for sensitive facts (spec §2 rule 6, §10).

A sensitive fact is stored only on an explicit remember request and stays
out of prompts and the core profile unless the learner enables that fact.
It is never embedded, enabled or not.
"""
import sqlalchemy as sa
from alembic import op

revision = "0088_memory_sensitive_enable"
down_revision = "0087_memory_fact_versions"
branch_labels = depends_on = None


def upgrade():
    # A plain ADD COLUMN on both dialects. Batch mode would rebuild the SQLite
    # table and drop the expression-based one-active-fact-per-subject index.
    op.add_column("memory_facts", sa.Column("sensitive_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.execute("ALTER TABLE memory_facts DROP COLUMN sensitive_enabled")
