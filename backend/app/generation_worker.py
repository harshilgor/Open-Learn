"""Independent durable generation consumer for hosted_runtime's generation role."""
from __future__ import annotations

import asyncio
import logging
import os
import threading

from .generation_service import GenerationManager


class GenerationWorker:
    def __init__(self, store, provider_getter):
        self.store = store
        self.provider_getter = provider_getter
        self.manager = GenerationManager(store, provider_getter(), provider_getter)

    def run(self, stop: threading.Event, once: bool = False) -> None:
        asyncio.run(self._run(stop, once))

    async def _run(self, stop: threading.Event, once: bool) -> None:
        manager = self.manager
        manager.runtime_loop = asyncio.get_running_loop()
        manager.notifications.start(manager.handle_notification)
        recovery = asyncio.create_task(manager.recovery_loop(), name="generation-worker-recovery")
        try:
            await asyncio.to_thread(manager.records.expire_stale_queued, manager.queue_deadline_seconds)
            await asyncio.to_thread(manager._schedule_queued)
            if once:
                await asyncio.sleep(0)
                while manager.tasks:
                    await asyncio.sleep(0.1)
                return
            while not stop.is_set():
                # PostgreSQL notifications wake this loop promptly; this timed
                # wait is the recovery path when notification delivery is off.
                try:
                    await asyncio.wait_for(asyncio.to_thread(stop.wait, 1.0), timeout=1.1)
                except asyncio.TimeoutError:
                    pass
                if not stop.is_set() and not manager.notifications.connected and len(manager.tasks) < manager.global_limit:
                    await asyncio.to_thread(manager._schedule_queued)
        finally:
            manager.shutting_down = True
            recovery.cancel()
            await asyncio.gather(recovery, return_exceptions=True)
            active = list(manager.tasks.values())
            drain_seconds = max(0.0, min(25.0, float(os.getenv("GENERATION_WORKER_DRAIN_SECONDS", "20"))))
            if active and drain_seconds:
                _, pending = await asyncio.wait(active, timeout=drain_seconds)
                for task in pending:
                    task.cancel()
                if pending:
                    try:
                        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=8.0)
                    except asyncio.TimeoutError:
                        logging.getLogger(__name__).warning("Generation worker drain deadline elapsed; remaining leases will recover by expiry")
            manager.notifications.close()
