"""Durable voice sessions, action receipts, replay, and metering."""
from alembic import op
import sqlalchemy as sa

revision = '0072_voice'
down_revision = '0071_class_metadata'
branch_labels = depends_on = None


def upgrade():
    op.create_table('voice_sessions',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('chat_id', sa.String(160), nullable=False),
        sa.Column('command_key', sa.String(160), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('epoch', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('last_seen', sa.Float(), nullable=False),
        sa.Column('capability_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.UniqueConstraint('owner_id', 'command_key'))
    op.create_index('ix_voice_active', 'voice_sessions', ['owner_id', 'status', 'expires_at'])
    op.create_index('uq_voice_owner_active', 'voice_sessions', ['owner_id'], unique=True,
                    sqlite_where=sa.text("status IN ('active','connecting')"),
                    postgresql_where=sa.text("status IN ('active','connecting')"))
    for name in ('turns', 'actions', 'speech_segments'):
        op.create_table('voice_' + name,
            sa.Column('id', sa.String(160), primary_key=True),
            sa.Column('owner_id', sa.String(160), nullable=False),
            sa.Column('session_id', sa.String(160), sa.ForeignKey('voice_sessions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('command_key', sa.String(160), nullable=False),
            sa.Column('request_hash', sa.String(64), nullable=False),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.Column('payload', sa.Text(), nullable=False),
            sa.UniqueConstraint('session_id', 'command_key'))
        op.create_index('ix_voice_' + name + '_owner', 'voice_' + name, ['owner_id', 'session_id', 'status'])
    op.create_table('voice_events',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('session_id', sa.String(160), sa.ForeignKey('voice_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.UniqueConstraint('session_id', 'sequence'))
    op.create_table('voice_usage',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('owner_id', sa.String(160), nullable=False),
        sa.Column('session_id', sa.String(160), sa.ForeignKey('voice_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('reserved_seconds', sa.Integer(), nullable=False),
        sa.Column('settled_seconds', sa.Integer()),
        sa.Column('tts_characters', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_voice_usage_owner', 'voice_usage', ['owner_id', 'created_at'])


def downgrade():
    for name in ('usage', 'events', 'speech_segments', 'actions', 'turns', 'sessions'):
        op.drop_table('voice_' + name)
