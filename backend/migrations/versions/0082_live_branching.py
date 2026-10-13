"""Add durable conversation events and response branches for parallel answers."""
from alembic import op
import sqlalchemy as sa

revision = "0082_live_branching"
down_revision = "0081_student_calendar"
branch_labels = depends_on = None


def upgrade():
    # Conversation events are the durable inbox and audit log. The per-session
    # counter makes sequence allocation atomic across concurrent requests.
    op.create_table(
        "conversation_event_counters",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("session_id", sa.String(160), sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "conversation_events",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("session_id", sa.String(160), sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("client_message_id", sa.String(160)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("owner_id", "session_id", "sequence", name="uq_conversation_event_sequence"),
        sa.UniqueConstraint("owner_id", "session_id", "client_message_id", name="uq_conversation_client_message"),
    )
    op.create_index(
        "ix_conversation_events_session_created",
        "conversation_events",
        ["owner_id", "session_id", "created_at"],
    )
    op.create_table(
        "response_branches",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("session_id", sa.String(160), sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_branch_id", sa.String(160), sa.ForeignKey("response_branches.id", ondelete="SET NULL")),
        sa.Column("trigger_event_id", sa.String(160), sa.ForeignKey("conversation_events.id"), nullable=False),
        sa.Column("relation", sa.String(24), nullable=False, server_default="uncertain"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_response_branches_session_created",
        "response_branches",
        ["owner_id", "session_id", "created_at"],
    )
    op.create_index(
        "ix_response_branches_trigger",
        "response_branches",
        ["trigger_event_id"],
    )
    op.create_table(
        "conversation_branch_heads",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("session_id", sa.String(160), sa.ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("selected_branch_id", sa.String(160), sa.ForeignKey("response_branches.id")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "generation_context_snapshots",
        sa.Column("generation_id", sa.String(160), sa.ForeignKey("generation_records.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("context_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "generation_capacity",
        sa.Column("scope_type", sa.String(24), primary_key=True),
        sa.Column("scope_id", sa.String(200), primary_key=True),
        sa.Column("active_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.add_column("generation_records", sa.Column("message_event_id", sa.String(160)))
    op.add_column("generation_records", sa.Column("branch_id", sa.String(160)))
    op.add_column("generation_records", sa.Column("context_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generation_records", sa.Column("parent_generation_id", sa.String(160)))
    op.add_column("generation_records", sa.Column("relation", sa.String(24), nullable=False, server_default="uncertain"))
    op.add_column("generation_records", sa.Column("owner_token", sa.String(160)))
    op.add_column("generation_records", sa.Column("owner_fence", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generation_records", sa.Column("lease_expires_at", sa.Float()))
    op.add_column("generation_records", sa.Column("capacity_reserved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("generation_records", sa.Column("partial_output", sa.Text(), nullable=False, server_default=""))
    op.add_column("generation_records", sa.Column("output_seq", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("generation_records") as batch:
        batch.create_foreign_key("fk_generation_message_event", "conversation_events", ["message_event_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_generation_response_branch", "response_branches", ["branch_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_generation_parent", "generation_records", ["parent_generation_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_generation_branch_created", "generation_records", ["branch_id", "created_at"])
    # The existing one-active constraint encoded the old serial contract.
    # Bounded admission is enforced transactionally by generation_capacity.
    op.drop_index("uq_generation_active_conversation", table_name="generation_records")


def downgrade():
    op.create_index(
        "uq_generation_active_conversation",
        "generation_records",
        ["owner_id", "session_id"],
        unique=True,
        sqlite_where=sa.column("status").in_(("queued", "preparing", "streaming", "finalizing", "cancel_requested")),
        postgresql_where=sa.column("status").in_(("queued", "preparing", "streaming", "finalizing", "cancel_requested")),
    )
    op.drop_index("ix_generation_branch_created", table_name="generation_records")
    with op.batch_alter_table("generation_records") as batch:
        batch.drop_constraint("fk_generation_parent", type_="foreignkey")
        batch.drop_constraint("fk_generation_response_branch", type_="foreignkey")
        batch.drop_constraint("fk_generation_message_event", type_="foreignkey")
    for name in (
        "message_event_id", "branch_id", "context_revision", "parent_generation_id", "relation",
        "owner_token", "owner_fence", "lease_expires_at", "capacity_reserved", "partial_output", "output_seq",
    ):
        op.drop_column("generation_records", name)
    op.drop_table("generation_capacity")
    op.drop_table("generation_context_snapshots")
    op.drop_table("conversation_branch_heads")
    op.drop_index("ix_response_branches_trigger", table_name="response_branches")
    op.drop_index("ix_response_branches_session_created", table_name="response_branches")
    op.drop_table("response_branches")
    op.drop_index("ix_conversation_events_session_created", table_name="conversation_events")
    op.drop_table("conversation_events")
    op.drop_table("conversation_event_counters")
