"""Stable class topic sections and granular block ordering."""
from alembic import op
import sqlalchemy as sa

revision='0090_class_topics'
down_revision='0089_class_experience'
branch_labels=depends_on=None


def upgrade():
    op.create_table('class_document_topics',
        sa.Column('id',sa.String(160),primary_key=True),
        sa.Column('owner_id',sa.String(160),nullable=False),
        sa.Column('class_id',sa.String(160),sa.ForeignKey('class_sessions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('position',sa.Float(),nullable=False),
        sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_class_topics_page','class_document_topics',['owner_id','class_id','position','id'])
    op.add_column('class_document_blocks',sa.Column('topic_id',sa.String(160),nullable=True))
    op.add_column('class_document_blocks',sa.Column('position',sa.Float(),nullable=True))
    op.create_index('ix_class_document_order','class_document_blocks',['owner_id','class_id','topic_id','position','id'])


def downgrade():
    op.drop_index('ix_class_document_order',table_name='class_document_blocks')
    op.drop_column('class_document_blocks','position')
    op.drop_column('class_document_blocks','topic_id')
    op.drop_table('class_document_topics')
