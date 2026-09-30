"""Durable, evidence-linked lecture processing alongside legacy recordings."""
import sqlalchemy as sa
from alembic import op

revision = "0026_lecture_pipeline"
down_revision = "0025_class_recordings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lecture_recordings",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("learner_id", sa.String(120), nullable=False),
        sa.Column("note_id", sa.String(160), nullable=False),
        sa.Column("course_id", sa.String(160), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expected_chunk_count", sa.Integer(), nullable=True),
        sa.Column("capture_interrupted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("markers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("preferences_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("stage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("pipeline_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generation_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("stopped_at", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.UniqueConstraint("learner_id", "note_id", name="uq_lecture_note"),
    )
    op.create_index("ix_lecture_owner_status", "lecture_recordings", ["learner_id", "status", "updated_at"])
    op.create_index("ix_lecture_course", "lecture_recordings", ["learner_id", "course_id"])
    op.create_table(
        "lecture_audio_chunks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("recording_id", sa.String(80), sa.ForeignKey("lecture_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(160), nullable=False),
        sa.Column("transcription_status", sa.String(32), nullable=False),
        sa.Column("transcription_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transcription_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("recording_id", "sequence_number", name="uq_lecture_chunk_sequence"),
        sa.UniqueConstraint("storage_key", name="uq_lecture_chunk_storage"),
    )
    op.create_index("ix_lecture_chunk_status", "lecture_audio_chunks", ["recording_id", "transcription_status"])
    op.create_table(
        "lecture_transcript_segments",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("recording_id", sa.String(80), sa.ForeignKey("lecture_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.String(80), sa.ForeignKey("lecture_audio_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("speaker_confidence", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("transcription_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("normalization_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("chunk_id", "ordinal", name="uq_lecture_segment_chunk_ordinal"),
    )
    op.create_index("ix_lecture_segment_time", "lecture_transcript_segments", ["recording_id", "start_ms", "end_ms"])
    op.create_table(
        "lecture_sections",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("recording_id", sa.String(80), sa.ForeignKey("lecture_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("section_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("analysis_status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("recording_id", "ordinal", name="uq_lecture_section_ordinal"),
    )
    op.create_index("ix_lecture_section_time", "lecture_sections", ["recording_id", "start_ms"])
    op.create_table(
        "lecture_entities",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("recording_id", sa.String(80), sa.ForeignKey("lecture_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.String(80), sa.ForeignKey("lecture_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("spoken_form", sa.Text(), nullable=True),
        sa.Column("latex", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_lecture_entity_kind", "lecture_entities", ["recording_id", "kind", "section_id"])
    op.create_table(
        "lecture_note_blocks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("recording_id", sa.String(80), sa.ForeignKey("lecture_recordings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.String(80), sa.ForeignKey("lecture_sections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_id", sa.String(80), sa.ForeignKey("lecture_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("generation_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("recording_id", "generation_version", "ordinal", name="uq_lecture_block_order"),
    )
    op.create_index("ix_lecture_block_version", "lecture_note_blocks", ["recording_id", "generation_version", "ordinal"])


def downgrade():
    for index, table in (
        ("ix_lecture_block_version", "lecture_note_blocks"),
        ("ix_lecture_entity_kind", "lecture_entities"),
        ("ix_lecture_section_time", "lecture_sections"),
        ("ix_lecture_segment_time", "lecture_transcript_segments"),
        ("ix_lecture_chunk_status", "lecture_audio_chunks"),
        ("ix_lecture_course", "lecture_recordings"),
        ("ix_lecture_owner_status", "lecture_recordings"),
    ):
        op.drop_index(index, table_name=table)
    for table in ("lecture_note_blocks", "lecture_entities", "lecture_sections", "lecture_transcript_segments", "lecture_audio_chunks", "lecture_recordings"):
        op.drop_table(table)
