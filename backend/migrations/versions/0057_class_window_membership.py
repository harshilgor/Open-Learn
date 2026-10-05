"""Move active class window membership out of growing session JSON."""
import sqlalchemy as sa
from alembic import op


revision = '0057_class_window_membership'
down_revision = '0056_class_output_page_index'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'class_session_window_membership',
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('class_id', sa.String(160), sa.ForeignKey('class_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('set_id', sa.String(160), nullable=False),
        sa.Column('purpose', sa.String(24), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('window_id', sa.String(160), sa.ForeignKey('class_input_windows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_ms', sa.BigInteger()),
        sa.Column('end_ms', sa.BigInteger()),
        sa.PrimaryKeyConstraint('owner_id', 'class_id', 'set_id', 'purpose', 'ordinal',
                                name='pk_class_session_window_membership'),
        sa.UniqueConstraint('owner_id', 'class_id', 'set_id', 'purpose', 'window_id',
                            name='uq_class_session_window_membership_window'),
        sa.CheckConstraint("purpose IN ('transcript','notes')", name='ck_class_session_window_membership_purpose'),
    )
    op.create_index(
        'ix_class_session_window_membership_window',
        'class_session_window_membership',
        ['owner_id', 'class_id', 'set_id', 'window_id'],
    )
    op.create_index(
        'ix_class_session_window_membership_range',
        'class_session_window_membership',
        ['owner_id', 'class_id', 'set_id', 'purpose', 'start_ms', 'end_ms'],
    )


def downgrade():
    op.drop_index('ix_class_session_window_membership_range', table_name='class_session_window_membership')
    op.drop_index('ix_class_session_window_membership_window', table_name='class_session_window_membership')
    op.drop_table('class_session_window_membership')
