"""Add transactional PostgreSQL wakeups for durable generations."""
from alembic import op
import sqlalchemy as sa

revision = "0084_generation_shared_wakeups"
down_revision = "0083_live_branching_observability"
branch_labels = depends_on = None


def upgrade():
    op.add_column("generation_records", sa.Column(
        "owner_capacity_reserved", sa.Boolean(), nullable=False, server_default=sa.false()))
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION openlearn_notify_generation_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('openlearn_generation_events', NEW.generation_id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER openlearn_generation_event_notify
        AFTER INSERT ON generation_events
        FOR EACH ROW EXECUTE FUNCTION openlearn_notify_generation_event()
    """)
    op.execute("""
        CREATE FUNCTION openlearn_notify_generation_record() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.status = 'queued' THEN
                PERFORM pg_notify('openlearn_generation_queue', NEW.id);
            ELSIF TG_OP = 'UPDATE' THEN
                IF NEW.cancellation_requested AND NOT OLD.cancellation_requested THEN
                    PERFORM pg_notify('openlearn_generation_cancel', NEW.id);
                END IF;
                IF OLD.status IN ('queued','preparing','streaming','finalizing','cancel_requested')
                   AND NEW.status IN ('completed','cancelled','failed','interrupted') THEN
                    PERFORM pg_notify('openlearn_generation_queue', NEW.id);
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER openlearn_generation_record_insert_notify
        AFTER INSERT ON generation_records
        FOR EACH ROW EXECUTE FUNCTION openlearn_notify_generation_record()
    """)
    op.execute("""
        CREATE TRIGGER openlearn_generation_record_update_notify
        AFTER UPDATE OF status, cancellation_requested ON generation_records
        FOR EACH ROW EXECUTE FUNCTION openlearn_notify_generation_record()
    """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS openlearn_generation_record_update_notify ON generation_records")
        op.execute("DROP TRIGGER IF EXISTS openlearn_generation_record_insert_notify ON generation_records")
        op.execute("DROP FUNCTION IF EXISTS openlearn_notify_generation_record()")
        op.execute("DROP TRIGGER IF EXISTS openlearn_generation_event_notify ON generation_events")
        op.execute("DROP FUNCTION IF EXISTS openlearn_notify_generation_event()")
    op.drop_column("generation_records", "owner_capacity_reserved")
