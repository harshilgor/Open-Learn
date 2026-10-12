"""Add-only learner memory facts, episodes, embeddings, and settings.

See docs/LEARNER_MEMORY_IMPLEMENTATION.md §6. Explicit and tentative
preferences already in memory_derived are backfilled as memory_facts; the
memory_derived rows stay in place until Phase F removes that dependency.
"""
import hashlib
import json
import re
import time

import sqlalchemy as sa
from alembic import op

revision = "0086_learner_memory"
down_revision = "0085_object_cleanup_queue"
branch_labels = depends_on = None

# Kept in step with backend/app/learner_memory/store.py. Copied rather than
# imported so this migration stays fixed when application code changes.
PREFERENCE_IMPORTANCE = 0.6


def _fact_id_for_derived(owner, derived_id):
    return "fact_" + hashlib.sha256(f"{owner}:{derived_id}".encode()).hexdigest()[:32]


def _normalized(statement):
    return re.sub(r"\s+", " ", statement.strip().lower())


def upgrade():
    op.create_table(
        "memory_facts",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.String(200), nullable=False),
        sa.Column("course_id", sa.String(160), nullable=True),
        sa.Column("concept_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("event_date", sa.String(32), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("learned_at", sa.Float(), nullable=False),
        sa.Column("valid_from", sa.Float(), nullable=False),
        sa.Column("invalid_at", sa.Float(), nullable=True),
        sa.Column("superseded_by", sa.String(160), nullable=True),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.Float(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.Float(), nullable=True),
        sa.Column("stability_days", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_memory_facts_owner_status_kind", "memory_facts", ["owner_id", "status", "kind"])
    op.create_index("ix_memory_facts_owner_course_status", "memory_facts", ["owner_id", "course_id", "status"])
    op.create_index("ix_memory_facts_owner_subject_status", "memory_facts", ["owner_id", "subject_key", "status"])
    op.create_index("ix_memory_facts_owner_event_date", "memory_facts", ["owner_id", "event_date"])
    # At most one active fact per subject and scope, even under concurrent
    # extraction jobs. Both SQLite and PostgreSQL support this partial
    # expression index.
    op.execute("CREATE UNIQUE INDEX uq_memory_facts_active_subject ON memory_facts "
               "(owner_id, subject_key, COALESCE(course_id, '')) WHERE status = 'active'")
    if op.get_bind().dialect.name == "postgresql":
        # Lexical retrieval (Phase D). An expression index rather than a
        # generated column: account import inserts every reflected column,
        # which PostgreSQL rejects for generated columns.
        op.execute("CREATE INDEX ix_memory_facts_statement_fts ON memory_facts "
                   "USING GIN (to_tsvector('english', statement))")

    op.create_table(
        "memory_episodes",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("session_id", sa.String(160), nullable=False),
        sa.Column("course_id", sa.String(160), nullable=True),
        sa.Column("period_start", sa.Float(), nullable=False),
        sa.Column("period_end", sa.Float(), nullable=False),
        sa.Column("turn_range", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topics", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_memory_episodes_owner_course_period", "memory_episodes", ["owner_id", "course_id", "period_end"])
    op.create_index("ix_memory_episodes_owner_session", "memory_episodes", ["owner_id", "session_id"])

    op.create_table(
        "memory_embeddings",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("item_type", sa.String(20), primary_key=True),
        sa.Column("item_id", sa.String(160), primary_key=True),
        sa.Column("model", sa.String(160), primary_key=True),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column("vector", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "memory_settings",
        sa.Column("owner_id", sa.String(160), primary_key=True),
        sa.Column("learning_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )

    _backfill_preferences(op.get_bind())


def _backfill_preferences(conn):
    rows = conn.execute(sa.text("SELECT owner_id,id,payload FROM memory_derived WHERE kind='preference' AND valid=:valid ORDER BY owner_id,id"),
                        {"valid": True}).mappings().all()
    kept = {}
    for row in rows:
        try:
            value = json.loads(row["payload"])
        except ValueError:
            continue
        explicit = bool(value.get("explicit"))
        inner = value.get("value")
        if not explicit and isinstance(inner, dict) and inner.get("tentative"):
            inner = inner.get("value")
        statement = inner.get("statement") if isinstance(inner, dict) else inner
        if not isinstance(statement, str) or not statement.strip():
            continue
        scope = value.get("scope")
        course_id = scope.get("courseId") if isinstance(scope, dict) else scope if isinstance(scope, str) else None
        basis = [{"type": "memory_source", "sourceId": ref.get("sourceId"), "revision": ref.get("revision"), "derivedId": row["id"]}
                 for ref in value.get("basis", []) if isinstance(ref, dict) and ref.get("sourceId")]
        learned_at = None
        for ref in basis:
            updated = conn.execute(sa.text("SELECT updated_at FROM memory_sources WHERE owner_id=:owner AND id=:id"),
                                   {"owner": row["owner_id"], "id": ref["sourceId"]}).scalar_one_or_none()
            if updated is not None:
                learned_at = max(learned_at or 0.0, float(updated))
        learned_at = learned_at or time.time()
        subject_key = "preference:freeform-" + hashlib.sha256(_normalized(statement).encode()).hexdigest()[:8]
        status = "active" if explicit else "tentative"
        key = (row["owner_id"], subject_key, course_id or "", status)
        if key in kept:
            # The same statement saved twice in one scope stays one fact.
            fact = kept[key]
            fact["basis"] = fact["basis"] + basis
            fact["learned_at"] = max(fact["learned_at"], learned_at)
            continue
        kept[key] = {
            "owner": row["owner_id"], "id": _fact_id_for_derived(row["owner_id"], row["id"]), "statement": statement.strip()[:2000],
            "subject_key": subject_key, "course_id": course_id, "origin": "user_stated" if explicit else "inferred",
            "status": status, "confidence": 1.0 if explicit else 0.5, "learned_at": learned_at, "basis": basis,
            "confirmed": explicit,
        }
    for fact in kept.values():
        conn.execute(sa.text("""
            INSERT INTO memory_facts(owner_id,id,kind,statement,subject_key,course_id,concept_ids,event_date,origin,status,
                sensitive,confidence,importance,learned_at,valid_from,invalid_at,superseded_by,basis,last_used_at,use_count,
                confirmed_at,stability_days,needs_review,policy_version,revision)
            VALUES(:owner,:id,'preference',:statement,:subject_key,:course_id,'[]',NULL,:origin,:status,
                :false,:confidence,:importance,:learned_at,:learned_at,NULL,NULL,:basis,NULL,0,
                :confirmed_at,:stability,:false,'backfill-0086',1)
        """), {**fact, "basis": json.dumps(fact["basis"]), "importance": PREFERENCE_IMPORTANCE, "false": False,
               "confirmed_at": fact["learned_at"] if fact["confirmed"] else None,
               "stability": 365.0 if fact["confirmed"] else 30 * (1 + 2 * PREFERENCE_IMPORTANCE)})


def downgrade():
    op.drop_table("memory_settings")
    op.drop_table("memory_embeddings")
    op.drop_index("ix_memory_episodes_owner_session", table_name="memory_episodes")
    op.drop_index("ix_memory_episodes_owner_course_period", table_name="memory_episodes")
    op.drop_table("memory_episodes")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_memory_facts_statement_fts")
    op.execute("DROP INDEX IF EXISTS uq_memory_facts_active_subject")
    for name in ("ix_memory_facts_owner_event_date", "ix_memory_facts_owner_subject_status",
                 "ix_memory_facts_owner_course_status", "ix_memory_facts_owner_status_kind"):
        op.drop_index(name, table_name="memory_facts")
    op.drop_table("memory_facts")
