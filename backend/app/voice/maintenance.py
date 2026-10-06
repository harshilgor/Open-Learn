"""Supervised orphan cleanup and retention; may be run independently as a janitor."""
import asyncio
import time
from sqlalchemy import text
from .store import VoiceStore
from . import media


def tick(store):
    now = time.time()
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT id,owner_id FROM voice_sessions WHERE status IN ('active','connecting') AND (expires_at<=:now OR last_seen<:idle) LIMIT 100"), {'now': now, 'idle': now-240}).mappings().all()
    for row in rows:
        try:
            VoiceStore(store).end(row['owner_id'], row['id'], 'expired_or_disconnected')
            if media.configured():
                asyncio.run(media.close(row['id']))
        except Exception:
            # End status still rejects agent callbacks; later cleanup can close the room.
            continue
    with store.engine.begin() as conn:
        conn.execute(text('DELETE FROM voice_events WHERE created_at<:cutoff'), {'cutoff': now-30*86400})
    return len(rows)


if __name__ == '__main__':
    from ..storage import Store
    from ..database import database_url
    store = Store(database_url())
    try:
        tick(store)
    finally:
        store.close()
