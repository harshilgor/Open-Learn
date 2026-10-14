"""Index note evidence ranges and retain immutable chunk capture provenance."""
from alembic import op
import sqlalchemy as sa
revision='0091_class_evidence_indexes'
down_revision='0090_class_topics'
branch_labels=depends_on=None


def upgrade():
    op.add_column('class_document_blocks',sa.Column('source_start_ms',sa.Integer(),nullable=True))
    op.add_column('class_document_blocks',sa.Column('source_end_ms',sa.Integer(),nullable=True))
    op.create_index('ix_class_document_evidence_range','class_document_blocks',['owner_id','class_id','source_start_ms','source_end_ms'])
    op.create_table('class_audio_sources',
        sa.Column('chunk_id',sa.String(160),sa.ForeignKey('lecture_audio_chunks.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('owner_id',sa.String(160),nullable=False),
        sa.Column('class_id',sa.String(160),sa.ForeignKey('class_sessions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('run_id',sa.String(160),nullable=True),
        sa.Column('epoch',sa.Integer(),nullable=False),
        sa.Column('source_kind',sa.String(32),nullable=False))
    op.create_index('ix_class_audio_sources_owner','class_audio_sources',['owner_id','class_id','run_id'])


def downgrade():
    op.drop_table('class_audio_sources')
    op.drop_index('ix_class_document_evidence_range',table_name='class_document_blocks')
    op.drop_column('class_document_blocks','source_end_ms')
    op.drop_column('class_document_blocks','source_start_ms')
