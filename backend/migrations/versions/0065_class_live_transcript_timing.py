"""Store recording-relative timing for provisional live-caption turns."""
import sqlalchemy as sa
from alembic import op


revision = '0065_class_live_transcript_timing'
down_revision = '0064_learning_job_priority_fifo'
branch_labels = depends_on = None


def upgrade():
    op.add_column('class_live_transcript_segments', sa.Column('start_ms', sa.Integer(), nullable=True))
    op.add_column('class_live_transcript_segments', sa.Column('end_ms', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('class_live_transcript_segments', 'end_ms')
    op.drop_column('class_live_transcript_segments', 'start_ms')
