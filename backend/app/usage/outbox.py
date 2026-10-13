"""Owner-scoped, replayable reads from the transactional usage change log.

The outbox is an invalidation feed, not a second usage ledger. Consumers use
the stable event id/revision as an idempotency key and fetch an authoritative
allowance snapshot when they observe a newer revision.
"""

from sqlalchemy import text

from .ledger import UsageError


class UsageOutbox:
    def __init__(self, store):
        self.store = store

    def after(self, owner: str, after_revision: int = 0, limit: int = 50) -> dict:
        """Read one bounded page for the authenticated owner.

        Repeating a request returns the same event ids. If a future retention
        policy removes a required revision, consumers are told to resnapshot
        instead of silently skipping the gap.
        """
        if not isinstance(after_revision, int) or isinstance(after_revision, bool) or after_revision < 0:
            raise UsageError("usage_cursor_invalid", "Refresh your usage status and try again.", 422)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise UsageError("usage_page_invalid", "Choose a smaller usage event page.", 422)

        with self.store.engine.connect() as conn:
            # Read account revision and its event page in one statement. Under
            # PostgreSQL READ COMMITTED, separate SELECTs could otherwise see
            # different commits and return a cursor ahead of latestRevision.
            rows = conn.execute(
                text("""WITH state AS (
                        SELECT COALESCE((SELECT revision FROM usage_accounts WHERE owner_id=:owner),0)
                            AS latest_revision
                    )
                    SELECT state.latest_revision,event.id,event.revision,event.kind,event.created_at
                    FROM state LEFT JOIN usage_outbox AS event
                      ON event.owner_id=:owner AND event.revision>:after
                    ORDER BY event.revision ASC LIMIT :limit"""),
                {"owner": owner, "after": after_revision, "limit": limit + 1},
            ).mappings().all()
            latest_revision = int(rows[0]["latest_revision"] if rows else 0)
            if after_revision > latest_revision:
                raise UsageError("usage_cursor_invalid", "Refresh your usage status and try again.", 422)
            rows = [row for row in rows if row["id"] is not None]

        # Each ledger revision emits exactly one invalidation event in the same
        # transaction. A gap means the caller's cursor cannot be replayed (for
        # example after an operator applies a future retention policy).
        expected_revision = after_revision + 1
        if after_revision < latest_revision and not rows:
            return {
                "events": [],
                "nextRevision": latest_revision,
                "latestRevision": latest_revision,
                "hasMore": False,
                "resnapshotRequired": True,
            }
        for row in rows[:limit]:
            if row["revision"] != expected_revision:
                return {
                    "events": [],
                    "nextRevision": latest_revision,
                    "latestRevision": latest_revision,
                    "hasMore": False,
                    "resnapshotRequired": True,
                }
            expected_revision += 1

        has_more = len(rows) > limit
        rows = rows[:limit]
        events = [
            {
                "id": row["id"],
                "revision": int(row["revision"]),
                "kind": row["kind"],
                "createdAt": float(row["created_at"]),
            }
            for row in rows
        ]
        next_revision = events[-1]["revision"] if events else after_revision
        return {
            "events": events,
            "nextRevision": next_revision,
            "latestRevision": latest_revision,
            "hasMore": has_more,
            "resnapshotRequired": False,
        }
