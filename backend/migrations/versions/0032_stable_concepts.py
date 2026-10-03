"""Owner-scoped stable concepts, reviewed mappings and immutable graph history."""
import sqlalchemy as sa
from alembic import op

revision = "0032_stable_concepts"
down_revision = "0031_evidence_ledger"
branch_labels = depends_on = None


def upgrade():
    op.create_table("concept_graph_revisions", sa.Column("owner_id", sa.String(160), primary_key=True),
                    sa.Column("revision", sa.Integer(), nullable=False), sa.CheckConstraint("revision>=1"))
    for name, extra in (
        ("stable_concepts", [sa.Column("status", sa.String(20), nullable=False)]),
        ("course_concept_mappings", [sa.Column("course_id", sa.String(160), nullable=False), sa.Column("concept_id", sa.String(160), nullable=False)]),
        ("stable_concept_relations", [sa.Column("from_id", sa.String(160), nullable=False), sa.Column("to_id", sa.String(160), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("review_state", sa.String(20), nullable=False)]),
        ("legacy_concept_mappings", [sa.Column("graph_id", sa.String(160), nullable=False), sa.Column("graph_revision", sa.Integer(), nullable=False), sa.Column("node_id", sa.String(160), nullable=False), sa.Column("concept_id", sa.String(160), nullable=False), sa.UniqueConstraint("owner_id", "graph_id", "graph_revision", "node_id")]),
        ("concept_mapping_reports", [sa.Column("status", sa.String(20), nullable=False)]),
        ("concept_rubric_mappings", [sa.Column("question_id", sa.String(160), nullable=False), sa.Column("question_revision", sa.Integer(), nullable=False), sa.UniqueConstraint("owner_id", "question_id", "question_revision")]),
    ):
        op.create_table(name, sa.Column("owner_id", sa.String(160), primary_key=True), sa.Column("id", sa.String(160), primary_key=True),
                        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("payload", sa.Text(), nullable=False), *extra,
                        sa.CheckConstraint("revision>=1"))
    op.create_index("ix_course_concepts_scope", "course_concept_mappings", ["owner_id", "course_id"])
    op.create_index("ix_concept_prerequisites", "stable_concept_relations", ["owner_id", "kind", "review_state", "to_id"])
    op.create_table("concept_change_history", sa.Column("owner_id", sa.String(160), primary_key=True),
                    sa.Column("id", sa.String(160), primary_key=True), sa.Column("graph_revision", sa.Integer(), nullable=False),
                    sa.Column("payload", sa.Text(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False))


def downgrade():
    for name in ("concept_change_history", "concept_rubric_mappings", "concept_mapping_reports", "legacy_concept_mappings", "stable_concept_relations", "course_concept_mappings", "stable_concepts", "concept_graph_revisions"):
        op.drop_table(name)
