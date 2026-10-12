"""Recover pending ingestion: python -m backend.app.material_worker --once."""
import argparse
import time
from .database import database_url
from .storage import Store
from .material_service import MaterialService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    store = Store(database_url())
    try:
        service = MaterialService(store)
        while True:
            service.process_object_cleanup()
            processed = service.process_one()
            if args.once:
                break
            if not processed:
                time.sleep(2)
    finally:
        store.close()


if __name__ == "__main__":
    main()
