"""Capture epochs and append-only transcript correction provenance."""
import sqlalchemy as sa
from alembic import op
revision = '0039_recording_revisions'
down_revision = '0038_academic_planning'
branch_labels = depends_on = None

def upgrade():
    op.add_column('lecture_audio_chunks', sa.Column('capture_epoch', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('lecture_audio_chunks', sa.Column('epoch_sequence', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('lecture_audio_chunks', sa.Column('independent_media', sa.Boolean(), nullable=False, server_default=sa.true()))
    for table in ('lecture_transcript_revisions', 'lecture_observations'):
        op.create_table(table, sa.Column('owner_id', sa.String(160), primary_key=True), sa.Column('id', sa.String(160), primary_key=True), sa.Column('recording_id', sa.String(160), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('payload', sa.Text(), nullable=False), sa.Column('created_at', sa.Float(), nullable=False))
        op.create_index('ix_'+table+'_recording', table, ['owner_id','recording_id'])

def downgrade():
    op.drop_table('lecture_observations'); op.drop_table('lecture_transcript_revisions')
    op.drop_column('lecture_audio_chunks','independent_media'); op.drop_column('lecture_audio_chunks','epoch_sequence'); op.drop_column('lecture_audio_chunks','capture_epoch')
