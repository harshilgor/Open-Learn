"""Dedicated bounded worker for in-class coordination and specialist outputs."""
import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from .database import database_url
from .storage import Store
from .in_class_service import InClassService
from .material_orchestrator import MaterialOrchestrator
from .model_provider import configured_lesson_provider

log = logging.getLogger(__name__)


class InClassWorker:
    def __init__(self, store, provider_getter=configured_lesson_provider):
        self.service = InClassService(store, provider_getter())
        self.materials = MaterialOrchestrator(store)
        self.intake_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='class-material-intake')

    def tick(self, limit=4):
        # Keep note/specialist work on its existing bounded path. URL fetching
        # and material indexing are submitted afterward to separate workers.
        worked = self.service.tick(limit)
        return worked + self.materials.tick(self.intake_pool)

    def run(self, stop, once=False):
        if once:
            self.tick()
            self.intake_pool.shutdown(wait=False, cancel_futures=True)
            return
        try:
            while not stop.is_set():
                try:
                    worked = self.tick()
                except Exception:
                    log.exception("In-Class worker iteration failed")
                    worked = 0
                stop.wait(0.1 if worked else 0.5)
        finally:
            self.intake_pool.shutdown(wait=False, cancel_futures=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    store = Store(database_url())
    stop = threading.Event()
    try:
        InClassWorker(store).run(stop, args.once)
    finally:
        store.close()


if __name__ == "__main__":
    main()
