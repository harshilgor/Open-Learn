"""Supervised orphan cleanup and retention; may be run independently as a janitor."""
import asyncio
import time
import logging
from sqlalchemy import text
from .store import VoiceStore
from . import media


def tick(store, *, prune_events=True):
    now = time.time()
    with store.engine.connect() as conn:
        rows = conn.execute(text("""SELECT v.id,v.owner_id,v.room_closed_at FROM voice_sessions v
            WHERE (v.room_closed_at IS NULL OR EXISTS
                (SELECT 1 FROM usage_reservations r WHERE r.root_id=v.id AND r.owner_id=v.owner_id AND r.state='dispatched'))
            AND (v.status='ended' OR (v.status IN ('active','connecting') AND (v.expires_at<=:now OR v.last_seen<:idle)))
            ORDER BY v.created_at LIMIT 100"""), {'now': now, 'idle': now-240}).mappings().all()
    for row in rows:
        try:
            VoiceStore(store).end(row['owner_id'], row['id'], 'expired_or_disconnected')
            from .routes import _settle_voice_session
            from ..usage.ledger import Ledger
            _settle_voice_session(Ledger(store), row['owner_id'], row['id'])
        except Exception as exc:
            # Revoked owners or accounting outages must not keep provider rooms alive.
            logging.getLogger(__name__).warning('Voice accounting cleanup deferred (%s)', type(exc).__name__)
        try:
            if row['room_closed_at'] is not None:
                continue
            if not media.control_configured():
                continue
            asyncio.run(media.close(row['id']))
            with store.engine.begin() as conn:
                conn.execute(text('UPDATE voice_sessions SET room_closed_at=:now WHERE id=:id'), {'now': now, 'id': row['id']})
        except Exception as exc:
            logging.getLogger(__name__).warning('Voice media cleanup deferred (%s)', type(exc).__name__)
    if prune_events:
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
