"""Persist completed class chunk coverage so partial recovery stays O(1)."""
import sqlalchemy as sa
from alembic import op


revision = '0067_class_chunk_coverage'
down_revision = '0066_class_resource_intents'
branch_labels = depends_on = None


def upgrade():
    op.add_column('class_sessions', sa.Column(
        'completed_chunk_count', sa.Integer(), nullable=False, server_default='0'
    ))
    op.add_column('class_sessions', sa.Column(
        'chunk_coverage_revision', sa.Integer(), nullable=False, server_default='0'
    ))

    conn = op.get_bind()
    coverage = conn.execute(sa.text('''
        SELECT cs.id, COUNT(c.id) AS completed_count
        FROM class_sessions cs
        LEFT JOIN lecture_audio_chunks c
          ON c.recording_id=cs.recording_id AND c.transcription_status='completed'
        GROUP BY cs.id
    ''')).mappings().all()
    for row in coverage:
        count = int(row['completed_count'])
        conn.execute(sa.text('''
            UPDATE class_sessions
            SET completed_chunk_count=:count, chunk_coverage_revision=:count
            WHERE id=:id
        '''), {'count': count, 'id': row['id']})


def downgrade():
    op.drop_column('class_sessions', 'chunk_coverage_revision')
    op.drop_column('class_sessions', 'completed_chunk_count')
