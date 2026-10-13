"""Routine probes use one shared connection; schema is checked during startup."""
from __future__ import annotations

import threading
import time
from sqlalchemy import text


class DependencyReadiness:
    def __init__(self, ttl_seconds: float = 3):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._checked_at = float('-inf')
        self._available = False

    def check(self, engine) -> bool:
        # Coalesce concurrent probes, including failed checks. No new pool or
        # provider calls, and no Alembic introspection on this path.
        with self._lock:
            if time.monotonic() - self._checked_at < self.ttl_seconds:
                return self._available
            try:
                with engine.connect() as connection:
                    if connection.dialect.name == 'postgresql':
                        connection.execute(text("SET LOCAL statement_timeout = '1000ms'"))
                    connection.execute(text('SELECT 1'))
                self._available = True
            except Exception:
                self._available = False
            self._checked_at = time.monotonic()
            return self._available
