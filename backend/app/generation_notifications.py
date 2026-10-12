"""Best-effort PostgreSQL wakeups; durable generation rows remain authoritative."""
from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from typing import Callable


EVENT_CHANNEL = "openlearn_generation_events"
QUEUE_CHANNEL = "openlearn_generation_queue"
CANCEL_CHANNEL = "openlearn_generation_cancel"
CHANNELS = (EVENT_CHANNEL, QUEUE_CHANNEL, CANCEL_CHANNEL)


class GenerationNotificationHub:
    """One pooled PostgreSQL session per process, shared by all local waiters."""

    def __init__(self, store, *, enabled: bool):
        self.store = store
        self.enabled = bool(enabled and store.engine.dialect.name == "postgresql")
        self.fallback_seconds = max(1.0, min(15.0, float(os.getenv("OPENLEARN_GENERATION_NOTIFY_FALLBACK_SECONDS", "5"))))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop = None
        self._callback: Callable[[str, str], None] | None = None
        self._events = OrderedDict()
        self.connected = False

    def event_for(self, generation_id: str):
        import asyncio
        event = self._events.get(generation_id)
        if event is None:
            event = asyncio.Event()
            self._events[generation_id] = event
        self._events.move_to_end(generation_id)
        while len(self._events) > 4096:
            self._events.popitem(last=False)
        return event

    def wake_local(self, generation_id: str) -> None:
        event = self._events.get(generation_id)
        if event is not None:
            event.set()

    def start(self, callback: Callable[[str, str], None]) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        import asyncio
        self._loop = asyncio.get_running_loop()
        self._callback = callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="generation-pg-listener", daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            raw = None
            cursor = None
            connection = None
            try:
                raw = self.store.engine.raw_connection()
                connection = raw.driver_connection
                connection.autocommit = True
                cursor = connection.cursor()
                for channel in CHANNELS:
                    cursor.execute(f"LISTEN {channel}")
                self.connected = True
                delay = 1.0
                while not self._stop.is_set():
                    for notification in connection.notifies(timeout=1.0, stop_after=64):
                        if self._stop.is_set():
                            break
                        loop = self._loop
                        callback = self._callback
                        if loop and callback and not loop.is_closed():
                            loop.call_soon_threadsafe(callback, notification.channel, notification.payload)
            except Exception:
                if not self._stop.is_set():
                    self.connected = False
                    logging.getLogger(__name__).warning("Generation notification listener disconnected; SQL replay remains active", exc_info=True)
                    self._stop.wait(delay)
                    delay = min(15.0, delay * 2)
            finally:
                self.connected = False
                if cursor:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if raw:
                    try:
                        connection = connection or raw.driver_connection
                        if connection.autocommit:
                            cleanup = connection.cursor()
                            cleanup.execute("UNLISTEN *")
                            cleanup.close()
                            connection.autocommit = False
                    except Exception:
                        pass
                    try:
                        raw.close()
                    except Exception:
                        pass

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None
        self._events.clear()
        self._loop = None
        self._callback = None

