"""Metered, bounded Browserbase smoke test for the Open Learn cloud executor.

This opens one temporary, read-only session to example.com, exercises the same
request guard used by CloudExecutor against private-network subresources, then
confirms provider termination and usage settlement before deleting its local DB.
It never prints the Browserbase API key and never creates a remembered profile.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))


def load_browserbase_key() -> None:
    if os.getenv("BROWSERBASE_API_KEY"):
        return
    env_file = BACKEND / ".env"
    if not env_file.exists():
        raise RuntimeError("Set BROWSERBASE_API_KEY in the environment or backend/.env first.")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "BROWSERBASE_API_KEY":
            os.environ["BROWSERBASE_API_KEY"] = value.strip().strip("\"'")
            break
    if not os.getenv("BROWSERBASE_API_KEY"):
        raise RuntimeError("BROWSERBASE_API_KEY is missing from the environment and backend/.env.")


def configure_bounded_test() -> None:
    # Isolate this smoke test from deploy flags and other optional paid providers.
    os.environ.update({
        "AI_TUTOR_ENV": "development",
        "OPENLEARN_USAGE_MODE": "enforce",
        "OPENLEARN_USAGE_PAID_ROUTES_ENABLED": "true",
        "OPENLEARN_USAGE_POLICY_VERSION": "browserbase-live-smoke-v1",
        "OPENLEARN_USAGE_RATE_VERSION": "reference-v1",
        "OPENLEARN_PROVIDER_RATE_VERSION": "browserbase-live-smoke-2026-10-08-v1",
        "OPENLEARN_PLATFORM_DAILY_BUDGET_USD": "1",
        "OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD": "10",
        "OPENLEARN_CLOUD_BROWSER_ENABLED": "true",
        "OPENLEARN_BROWSERBASE_USD_PER_MINUTE": "0.002",
        "OPENLEARN_BROWSER_EGRESS_VERIFIED": "true",
        "OPENLEARN_BROWSER_LIFECYCLE_VERIFIED": "true",
        "OPENLEARN_BROWSER_PRIVATE_VERIFIED": "false",
        "OPENROUTER_MODEL": "openrouter/free",
        "AI_TUTOR_MODE_CLASSIFICATION": "rules",
        "AI_TUTOR_WEB_EVIDENCE": "false",
        "AI_TUTOR_EMBEDDING_MODEL": "off",
        "OPENLEARN_DICTATION_ENABLED": "false",
        "OPENLEARN_VOICE_ENABLED": "false",
        "OPENLEARN_SANDBOX_ENABLED": "false",
    })


def main() -> None:
    load_browserbase_key()
    configure_bounded_test()

    from sqlalchemy import text
    from playwright.sync_api import sync_playwright
    from backend.app.browser_assistant.connections import Connections
    from backend.app.browser_assistant.contracts import BrowserAction, ConnectionCreate, TaskCreate
    from backend.app.browser_assistant.executors.cloud import (
        BrowserbaseProvider,
        CloudExecutor,
        guard_browser_request,
    )
    from backend.app.browser_assistant.service import AssistantService
    from backend.app.identity import Principal, principal_context
    from backend.app.storage import Store
    from backend.app.usage.context import usage_scope

    work = BACKEND / "work"
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / f"browserbase-live-{uuid4().hex}.sqlite3"
    owner = f"browserbase-live-{uuid4().hex}"
    store = Store(db_path)
    principal_token = principal_context.set(Principal(owner, "local"))
    provider = BrowserbaseProvider()
    executor = CloudExecutor(store, provider)
    run = None
    connection = None
    browser = None
    session_id = None
    blocked_urls: list[str] = []
    successful = False
    try:
        connection = Connections(store).create(owner, ConnectionCreate(
            label="Temporary Browserbase release check",
            origin="https://example.com",
            executor="cloud",
        ))
        run = AssistantService(store).create(owner, TaskCreate(
            message="Confirm the public example page opens using the temporary cloud browser.",
            connection_id=connection["id"],
            max_actions=1,
            max_pages=1,
        ))
        run = {**run, "owner_id": owner}

        with usage_scope(store, owner, run["id"]):
            session_id, endpoint = executor.session(connection, run)
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=20_000)
                context = browser.contexts[0]

                def route(request_route):
                    if request_route.request.url.startswith((
                        "http://127.0.0.1/", "http://169.254.169.254/"
                    )):
                        blocked_urls.append(request_route.request.url)
                    guard_browser_request(request_route, connection)

                context.route("**/*", route)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://example.com", wait_until="domcontentloaded", timeout=20_000)
                if page.title() != "Example Domain":
                    raise AssertionError("Public example page did not finish loading as expected.")

                # These are intercepted and aborted before they reach the cloud
                # network. Error events synchronize on route completion.
                for url in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/"):
                    page.evaluate("""url => new Promise(resolve => {
                        const image = new Image();
                        image.addEventListener('error', () => resolve('blocked'), {once: true});
                        image.addEventListener('load', () => resolve('unexpectedly-loaded'), {once: true});
                        image.src = url;
                        document.body.appendChild(image);
                    })""", url)
                if len(blocked_urls) != 2:
                    raise AssertionError("The browser request guard did not block both private subresource probes.")

                browser.close()
                browser = None

        executor.close(owner, run["id"])
        with store.engine.connect() as conn:
            lease = conn.execute(text("SELECT status FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run"),
                                 {"owner": owner, "run": run["id"]}).mappings().one()
            reservation = conn.execute(text("""SELECT r.id,r.state,r.liability_nano,e.cost_nano
                FROM usage_reservations r JOIN usage_events e ON e.reservation_id=r.id
                WHERE r.owner_id=:owner AND r.component='browser'"""), {"owner": owner}).mappings().one()
        if lease["status"] != "closed" or reservation["state"] != "settled":
            raise AssertionError("Open Learn did not confirm provider termination and usage settlement.")
        successful = True
        dollars = Decimal(reservation["cost_nano"]) / Decimal(1_000_000_000)
        print(json.dumps({
            "result": "passed",
            "provider": "Browserbase",
            "publicPage": "https://example.com",
            "privateSubresourcesBlocked": len(blocked_urls),
            "leaseStatus": lease["status"],
            "reservationState": reservation["state"],
            "measuredCostUsd": str(dollars),
            "maximumReservedUsd": str(Decimal(reservation["liability_nano"]) / Decimal(1_000_000_000)),
            "sessionUrl": f"https://www.browserbase.com/sessions/{session_id}",
        }, indent=2))
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if run and session_id:
            try:
                executor.close(owner, run["id"])
            except Exception:
                pass
        principal_context.reset(principal_token)
        store.close()
        if successful:
            for suffix in ("", "-shm", "-wal"):
                (Path(str(db_path) + suffix)).unlink(missing_ok=True)
        else:
            print(f"Acceptance failed; retained local ledger for reconciliation at {db_path}")


if __name__ == "__main__":
    main()
