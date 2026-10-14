"""Bounded provider profile qualification using synthetic cookies only.

Runs in an isolated SQLite store, never the production database. Does not change
production readiness flags. Real portal authentication is a separate release gate.
"""
from __future__ import annotations
import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4


BACKEND = Path(__file__).resolve().parents[1]

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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-synthetic-profile-probe', action='store_true')
    args = parser.parse_args()
    if not args.allow_synthetic_profile_probe:
        parser.error('Explicit synthetic profile probe authorization is required')
    load_browserbase_key()
    configure_bounded_test()
    os.environ.pop('DATABASE_URL', None)
    os.environ['OPENLEARN_MIGRATE_ON_START'] = 'true'
    # Probe-only override: the process has an isolated store and synthetic cookies.
    os.environ['OPENLEARN_BROWSER_PRIVATE_VERIFIED'] = 'true'
    from backend.app.usage.policy import Policy
    try:
        Policy.load()
    except RuntimeError as exc:
        print(json.dumps({'preflightPolicyError':str(exc)}))
        raise
    from fastapi import HTTPException
    from playwright.sync_api import sync_playwright
    from sqlalchemy import text
    from backend.app.storage import Store
    from backend.app.identity import Principal, principal_context
    from backend.app.usage.context import usage_scope
    from backend.app.browser_assistant.connections import Connections
    from backend.app.browser_assistant.contracts import ConnectionCreate
    from backend.app.browser_assistant.executors.cloud import BrowserbaseProvider, stop_and_settle
    from backend.app.browser_assistant.workers import AssistantWorker

    owner = 'profile-probe-' + uuid4().hex
    path = Path('backend/work') / (owner + '.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    token = principal_context.set(Principal(owner, 'local'))
    connections = Connections(store)
    import backend.app.browser_assistant.executors.cloud as cloud_module
    class DiagnosticProvider(BrowserbaseProvider):
        def request(self, method, path, data=None):
            try:
                result=super().request(method, path, data)
                from urllib.parse import urlsplit
                print(json.dumps({'providerOperation':method+' '+path.split('/')[0],'responseKeys':sorted(result) if isinstance(result,dict) else [],'liveViewHost':urlsplit(result.get('debuggerFullscreenUrl','')).hostname if isinstance(result,dict) else None}))
                return result
            except Exception as exc:
                import httpx
                if isinstance(exc, httpx.HTTPStatusError):
                    print(json.dumps({'providerOperation':method+' '+path.split('/')[0],
                                      'httpStatus':exc.response.status_code}))
                print(json.dumps({'providerErrorType':type(exc).__name__}))
                raise
    cloud_module.BrowserbaseProvider = DiagnosticProvider
    provider = DiagnosticProvider()
    context_ids = set()
    sessions = []
    checks = {}
    successful = False
    try:
        connection = connections.create(owner, ConnectionCreate(
            label='Synthetic profile qualification', origin='https://example.com',
            executor='cloud', cloud_login=True))
        # Cross-owner attempts must fail before any provider request.
        try:
            connections.cloud_login('other-' + owner, connection['id'], connection['revision'])
        except HTTPException as exc:
            checks['crossOwnerDenied'] = exc.status_code in (403, 404)
        else:
            raise AssertionError('Cross-owner profile access was accepted')
        if not checks['crossOwnerDenied']:
            raise AssertionError('Cross-owner access did not fail closed')
        with sync_playwright() as playwright:
            for index in range(3):
                with usage_scope(store, owner, 'profile-probe-' + str(index)):
                    started = connections.cloud_login(owner, connection['id'], connection['revision'])
                connection = started['connection']
                if index == 0:
                    # Validate actual provider expiry, not merely the requested TTL.
                    from urllib.parse import urlsplit, parse_qs
                    import base64
                    link_parts = urlsplit(started['liveViewUrl'])
                    claims = None
                    candidates=[value for values in parse_qs(link_parts.query).values() for value in values]
                    for value in list(candidates):
                        candidates.extend(v for values in parse_qs(urlsplit(value).query).values() for v in values)
                    for value in candidates:
                        pieces=value.split('.')
                        if len(pieces)==3:
                            try:
                                claims=json.loads(base64.urlsafe_b64decode(pieces[1]+'='*(-len(pieces[1])%4)))
                            except (ValueError,UnicodeDecodeError):
                                continue
                    checks['liveViewExpiryClaimBounded'] = bool(claims and isinstance(claims.get('exp'),(float,int)) and 0 < claims['exp']-time.time() <= 65)
                    print(json.dumps({'liveViewQueryKeys':sorted(parse_qs(link_parts.query)), 'liveViewExpiryClaimBounded':checks['liveViewExpiryClaimBounded']}))
                    if not checks['liveViewExpiryClaimBounded']:
                        raise AssertionError('Provider Live View expiry cannot be established from issued link')
                with store.engine.connect() as conn:
                    raw = connections.repo.read('site_connections', owner, connection['id'])
                    lease = conn.execute(text('SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run'),
                        {'owner':owner, 'run':'login:' + connection['id']}).mappings().one()
                context_ids.add(raw['providerContextId'])
                sessions.append(lease['provider_session'])
                endpoint = json.loads(lease['payload'])['connectUrl']
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=20_000)
                try:
                    context = browser.contexts[0]
                    cookie = next((c for c in context.cookies('https://example.com') if c['name']=='openlearn_synthetic_probe'), None)
                    if index == 0:
                        context.add_cookies([{'name':'openlearn_synthetic_probe','value':'synthetic-only',
                            'url':'https://example.com','expires':time.time()+600,'secure':True,'httpOnly':True}])
                    elif index == 1:
                        checks['profilePersistsAcrossSessions'] = bool(cookie and cookie['value']=='synthetic-only')
                        if not checks['profilePersistsAcrossSessions']:
                            raise AssertionError('Synthetic profile cookie was not restored')
                        context.clear_cookies()
                    else:
                        checks['clearedAuthenticationStaysCleared'] = cookie is None
                        if cookie is not None:
                            raise AssertionError('Cleared synthetic authentication reappeared')
                finally:
                    browser.close()
                with usage_scope(store, owner, 'profile-probe-' + str(index)):
                    connection = connections.cloud_login(owner, connection['id'], connection['revision'], finish=True)
        connections.revoke(owner, connection['id'])
        AssistantWorker(store).recover()
        for context_id in context_ids:
            try:
                provider.request('GET', 'contexts/' + context_id)
            except Exception as exc:
                import httpx
                if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code not in (404, 410):
                    raise RuntimeError('Provider profile deletion could not be confirmed') from None
            else:
                raise AssertionError('Provider profile remains after connection revocation')
        with store.engine.connect() as conn:
            checks['providerSessionsClosed'] = conn.execute(text("SELECT count(*) FROM browser_session_leases WHERE status<>'closed'" )).scalar_one()==0
            checks['usageSettled'] = conn.execute(text("SELECT count(*) FROM usage_reservations WHERE component='browser' AND state<>'settled'" )).scalar_one()==0
            cost = conn.execute(text("SELECT coalesce(sum(cost_nano),0) FROM usage_events WHERE owner_id=:owner"), {'owner':owner}).scalar_one()
        checks['providerProfileDeleted'] = True
        if not all(checks.values()):
            raise AssertionError('One or more lifecycle checks failed')
        successful = True
        print(json.dumps({'result':'passed','kind':'synthetic_private_profile_lifecycle',
            'checks':checks,'sessions':len(sessions),'costUsd':cost/1_000_000_000,
            'maximumReservedUsd':0.06,'productionFlagsChanged':False,
            'authenticatedPortalQualified':False,'liveViewExpiryQualified':False}))
    finally:
        with store.engine.connect() as conn:
            leases = conn.execute(text("SELECT * FROM browser_session_leases WHERE status<>'closed'")).mappings().all()
        for lease in leases:
            stop_and_settle(store, provider, lease)
        for context_id in context_ids:
            try:
                provider.delete_context(context_id)
            except Exception:
                successful = False
        AssistantWorker(store).cleanup()
        principal_context.reset(token)
        store.close()
        if successful:
            for suffix in ('','-wal','-shm'):
                Path(str(path)+suffix).unlink(missing_ok=True)
        else:
            print('Profile probe incomplete; isolated reconciliation ledger retained at ' + str(path))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'result':'failed','errorType':type(exc).__name__,'errorCode':getattr(exc,'detail',{}).get('code') if isinstance(getattr(exc,'detail',None),dict) else None,'message':getattr(exc,'detail',{}).get('message') if isinstance(getattr(exc,'detail',None),dict) else None,'productionFlagsChanged':False}))
        raise SystemExit(1) from None
