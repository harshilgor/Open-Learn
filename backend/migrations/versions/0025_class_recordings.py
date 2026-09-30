"""Persist uploaded class recordings and processing state."""
import sqlalchemy as sa
from alembic import op

revision = "0025_class_recordings"
down_revision = "0024_generation_event_replay"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "class_recordings",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("learner_id", sa.String(120), nullable=False),
        sa.Column("note_id", sa.String(80), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("markers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("learner_id", "note_id", name="uq_class_recording_note"),
    )
    op.create_index("ix_class_recordings_owner_updated", "class_recordings", ["learner_id", "updated_at"])


def downgrade():
    op.drop_index("ix_class_recordings_owner_updated", table_name="class_recordings")
    op.drop_table("class_recordings")
