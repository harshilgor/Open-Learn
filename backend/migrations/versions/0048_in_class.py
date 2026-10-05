"""Owner-scoped live class envelopes and versioned output references."""
import sqlalchemy as sa
from alembic import op
revision = '0048_in_class'
down_revision = '0047_agent_connected_actions'
branch_labels = depends_on = None

def upgrade():
    op.create_table('class_sessions', sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('recording_id',sa.String(160),sa.ForeignKey('lecture_recordings.id',ondelete='CASCADE'),nullable=False,unique=True),sa.Column('session_id',sa.String(160),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
    for name in ['class_input_windows','class_output_versions','class_session_events']:
        op.create_table(name,sa.Column('id',sa.String(160),primary_key=True),sa.Column('owner_id',sa.String(160),nullable=False),sa.Column('class_id',sa.String(160),sa.ForeignKey('class_sessions.id',ondelete='CASCADE'),nullable=False),sa.Column('kind',sa.String(40),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.Float(),nullable=False))
        op.create_index('ix_'+name+'_owner_class',name,['owner_id','class_id'])
    op.create_index('ix_class_sessions_owner', 'class_sessions',['owner_id'])

def downgrade():
    for name in ['class_session_events','class_output_versions','class_input_windows','class_sessions']:op.drop_table(name)
