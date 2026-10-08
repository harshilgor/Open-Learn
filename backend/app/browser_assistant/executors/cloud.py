"""Temporary Browserbase sessions with deterministic Playwright actions."""
import base64
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from sqlalchemy import text
from ..contracts import Observation
from ..policy import check_url, origin
from ...identity import fail
from ...workflow_store import uid, encoded

SESSION_TTL_SECONDS = 600
RECONCILIATION_GRACE_SECONDS = 120
SESSION_TTL_MILLISECONDS = SESSION_TTL_SECONDS * 1000
PROFILE_RETENTION_SECONDS = 30 * 24 * 60 * 60
TERMINAL_SESSION_STATES = {'COMPLETED', 'TIMED_OUT', 'ERROR', 'RELEASED', 'STOPPED'}

OBSERVER = Path(__file__).resolve().parents[1] / 'observer.js'


def readiness():
    import importlib.util
    try:
        from ...usage.policy import Policy
        policy = Policy.load()
        paid_routes = policy.mode == 'enforce' and policy.paid
    except Exception:
        paid_routes = False
    try:
        from ...usage.operations import configured_rate
        configured_rate('OPENLEARN_BROWSERBASE_USD_PER_MINUTE')
        tariff_configured = True
    except Exception:
        tariff_configured = False
    return {'enabled': os.getenv('OPENLEARN_CLOUD_BROWSER_ENABLED') == 'true',
            'paidRoutesEnabled': paid_routes,
            'tariffConfigured': tariff_configured,
            # Browserbase infers the project from the API key. Do not require
            # or persist a separate project ID in application configuration.
            'credentialsConfigured': bool(os.getenv('BROWSERBASE_API_KEY')),
            'runtimeInstalled': importlib.util.find_spec('playwright') is not None,
            'egressVerified': os.getenv('OPENLEARN_BROWSER_EGRESS_VERIFIED') == 'true',
            'lifecycleVerified': os.getenv('OPENLEARN_BROWSER_LIFECYCLE_VERIFIED') == 'true',
            # Set only after dated acceptance proves owner isolation, short-lived
            # live-view control, provider termination, and profile deletion.
            'privateLoginVerified': os.getenv('OPENLEARN_BROWSER_PRIVATE_VERIFIED') == 'true'}


def require_cloud_ready():
    report = readiness()
    required = ('enabled', 'paidRoutesEnabled', 'tariffConfigured', 'credentialsConfigured',
                'runtimeInstalled', 'egressVerified', 'lifecycleVerified')
    if not all(report[key] for key in required):
        fail('capability_unavailable',
             'Cloud browser service is not configured with enforced usage limits and verified network controls.', 503)
    return report


def _actual_browser_usage(started_at, ended_at, rate_nano_per_minute):
    elapsed_ms = max(0, math.ceil((ended_at - started_at) * 1000))
    billable_ms = min(SESSION_TTL_MILLISECONDS, max(60_000, elapsed_ms))
    billable_minutes = min(10, max(1, math.ceil(billable_ms / 60_000)))
    return {'milliseconds': billable_ms}, rate_nano_per_minute * billable_minutes


def _settle_ticket(ticket, started_at, ended_at, rate_nano_per_minute):
    if ticket is None:
        raise RuntimeError('Browser session has no usage reservation.')
    from ...usage.operations import finish_external
    quantities, cost_nano = _actual_browser_usage(started_at, ended_at, rate_nano_per_minute)
    finish_external(ticket, quantities=quantities, cost_nano=cost_nano, source='exact')


def guard_browser_request(request_route, connection, blocked_navigation=None):
    """Enforce Open Learn's read-only and public-URL rules on every request."""
    request = request_route.request
    url = request.url
    try:
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            request_route.abort()
            return False
        from ...url_ingestion import validate_public_url
        validate_public_url(url)
        if request.is_navigation_request():
            check_url(url, connection)
        request_route.continue_()
        return True
    except Exception:
        if request.is_navigation_request() and blocked_navigation is not None:
            blocked_navigation.append(url)
        request_route.abort()
        return False


def stop_and_settle(store, provider, row):
    """Stop a session, confirm provider termination, then settle its stored hold."""
    try:
        provider.stop(row['provider_session'])
        state = provider.request('GET', 'sessions/' + row['provider_session']).get('status', '')
        if str(state).upper() not in TERMINAL_SESSION_STATES:
            return False
        payload = json.loads(row['payload'] or '{}')
        reservation_id = payload.get('usageReservationId')
        if reservation_id:
            started_at = payload.get('usageStartedAt')
            rate = payload.get('usageRateNanoPerMinute')
            if not isinstance(started_at, (int, float)) or not isinstance(rate, int) or rate <= 0:
                # Keep the funded reservation for conservative reconciliation.
                return False
            from ...usage.ledger import Ledger
            from ...usage.policy import Policy
            quantities, cost_nano = _actual_browser_usage(started_at, time.time(), rate)
            Ledger(store, Policy()).settle(row['owner_id'], reservation_id, quantities,
                                           cost=cost_nano, source='exact')
        with store.engine.begin() as conn:
            conn.execute(text("UPDATE browser_session_leases SET status='closed',payload='{}' WHERE id=:id"),
                         {'id': row['id']})
        return True
    except Exception:
        # The provider outcome or settlement is uncertain. Keep the lease and
        # reservation intact so the durable reconciler charges the funded bound.
        return False


class BrowserbaseProvider:
    def request(self, method, path, data=None):
        response = httpx.request(method, 'https://api.browserbase.com/v1/' + path,
            headers={'X-BB-API-Key': os.environ['BROWSERBASE_API_KEY']}, json=data, timeout=20)
        if response.status_code == 404 and (method == 'DELETE' or method == 'POST' and (data or {}).get('status') == 'REQUEST_RELEASE'):
            return {}
        response.raise_for_status()
        return response.json() if response.content else {}

    def create(self, connection, usage_ticket=None, *, persist_context=False):
        require_cloud_ready()
        if (not usage_ticket or len(usage_ticket) != 3 or
                usage_ticket[2].get('component') != 'browser' or
                usage_ticket[2].get('liability_nano', 0) <= 0):
            fail('usage_accounting_unavailable', 'Cloud browser work requires a funded usage reservation.', 503)
        settings = {'recordSession': False, 'logSession': False, 'solveCaptchas': False,
                    'allowedDomains': [urlsplit(u).hostname for u in [connection['origin'], *connection.get('approvedOrigins', [])]],
                    'viewport': {'width': 1280, 'height': 900}}
        context_id = connection.get('providerContextId')
        if context_id and connection.get('cloudLogin'):
            if not readiness()['privateLoginVerified']:
                fail('capability_unavailable', 'Saved browser profiles are unavailable until their isolation and deletion checks pass.', 503)
            # Ordinary tasks may read a remembered profile but cannot rewrite
            # it. Only the learner-controlled sign-in handoff persists updates.
            settings['context'] = {'id': context_id, 'persist': bool(persist_context)}
        # Ordinary read sessions should end when the controller disconnects.
        # Only the interactive sign-in handoff needs to remain alive for the
        # student to use Browserbase's short-lived Live View.
        payload = {'browserSettings': settings, 'timeout': SESSION_TTL_SECONDS,
                   'keepAlive': bool(persist_context)}
        return self.request('POST', 'sessions', payload)

    def stop(self, identifier):
        self.request('POST', f'sessions/{identifier}', {'status': 'REQUEST_RELEASE'})

    def create_context(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('A private browser profile name is required.')
        # Browserbase resolves the project from the API key. Keep the context
        # name opaque; never include an email, domain, or learner label.
        return self.request('POST', 'contexts', {'name': name[:128]})

    def delete_context(self, identifier):
        self.request('DELETE', 'contexts/' + identifier)

    def live_view(self, identifier):
        return self.request('GET', f'sessions/{identifier}/debug?expiresIn=60')['debuggerFullscreenUrl']


def queue_context_cleanup(store, owner, connection):
    if not connection.get('providerContextId'): return
    # Cleanup metadata must survive owner erasure, unlike content records.
    with store.engine.begin() as conn:
        conn.execute(text('INSERT INTO browser_provider_cleanup(id,owner_id,context_id,session_id,created_at) VALUES(:id,:owner,:context,NULL,:now) ON CONFLICT DO NOTHING'),
                     {'id': 'context:' + connection['providerContextId'], 'owner': owner, 'context': connection['providerContextId'], 'now': time.time()})


class CloudExecutor:
    def __init__(self, store, provider=None):
        self.store = store; self.provider = provider or BrowserbaseProvider()

    def session(self, connection, run):
        require_cloud_ready()
        context_id = connection.get('providerContextId')
        if context_id and connection.get('cloudLogin') and not readiness()['privateLoginVerified']:
            fail('capability_unavailable', 'Saved browser profiles are unavailable until their isolation and deletion checks pass.', 503)
        context_expiry = connection.get('browserContextExpiresAt')
        if context_id and (not connection.get('cloudLogin') or
                           not isinstance(context_expiry, (int, float)) or context_expiry <= time.time()):
            queue_context_cleanup(self.store, run['owner_id'], connection)
            with self.store.engine.begin() as conn:
                row = conn.execute(text('SELECT payload,revision FROM site_connections WHERE id=:id AND owner_id=:owner'),
                                   {'id': connection['id'], 'owner': run['owner_id']}).mappings().first()
                if row:
                    saved = json.loads(row['payload'])
                    if saved.get('providerContextId') == context_id:
                        for key in ('providerContextId', 'browserContextExpiresAt', 'browserContextLastUsedAt', 'loginSessionId'):
                            saved.pop(key, None)
                        conn.execute(text('UPDATE site_connections SET payload=:payload,revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                                     {'payload': encoded(saved), 'now': time.time(), 'id': connection['id'], 'owner': run['owner_id']})
            fail('capability_unavailable', 'The saved sign-in expired. Sign in again from Connected websites, then retry this task.', 409)
        with self.store.transaction() as conn:
            row = conn.execute(text("SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status='active'"),
                               {'owner': run['owner_id'], 'run': run['id'], 'now': time.time()}).mappings().first()
        if row:
            payload = json.loads(row['payload'] or '{}')
            if row['expires_at'] > time.time() and payload.get('usageReservationId') and payload.get('connectUrl'):
                return row['provider_session'], payload['connectUrl']
            if not stop_and_settle(self.store, self.provider, row):
                fail('capability_unavailable', 'The previous cloud browser session is still being safely closed. Retry shortly.', 503)

        from ...usage.operations import begin_external, configured_rate, rate_liability
        rate = configured_rate('OPENLEARN_BROWSERBASE_USD_PER_MINUTE')
        liability = rate_liability('OPENLEARN_BROWSERBASE_USD_PER_MINUTE', 10, 1)
        ticket = begin_external('browser', {'milliseconds': SESSION_TTL_MILLISECONDS}, liability,
                                root=run['id'], seconds=SESSION_TTL_SECONDS + RECONCILIATION_GRACE_SECONDS,
                                provider='browserbase',model='chromium',
                                provider_rates={'usd_nano_per_minute':rate})
        if ticket is None:
            fail('usage_accounting_unavailable', 'Cloud browser work requires an active usage account.', 503)
        started_at = time.time()
        try:
            session = self.provider.create(connection, usage_ticket=ticket)
            if (not isinstance(session, dict) or not session.get('id') or
                    not isinstance(session.get('connectUrl'), str) or not session['connectUrl']):
                raise ValueError('Browser provider returned an incomplete session.')
        except Exception:
            # Creation may have succeeded even if its response was lost. Keep
            # the dispatched maximum hold for reconciliation.
            fail('capability_unavailable', 'Cloud browser could not be started. The provider outcome is being safely reconciled.', 503)
        payload = {'connectUrl': session['connectUrl'], 'usageReservationId': ticket[2]['id'],
                   'usageStartedAt': started_at, 'usageRateNanoPerMinute': rate}
        try:
            with self.store.transaction() as conn:
                conn.execute(text('''INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload)
                    VALUES(:id,:owner,:run,:connection,:session,'active',:expires,:payload)
                    ON CONFLICT(run_id) DO UPDATE SET connection_id=excluded.connection_id,provider_session=excluded.provider_session,status='active',expires_at=excluded.expires_at,payload=excluded.payload'''),
                    {'id': uid('bs'), 'owner': run['owner_id'], 'run': run['id'], 'connection': connection['id'], 'session': session['id'],
                     'expires': started_at + SESSION_TTL_SECONDS, 'payload': encoded(payload)})
        except Exception:
            # Do not discard a hold on a storage failure. The session is stopped
            # and settled only if the provider confirms termination.
            try:
                self.provider.stop(session['id'])
                state = self.provider.request('GET', 'sessions/' + session['id']).get('status', '')
                if str(state).upper() in TERMINAL_SESSION_STATES:
                    _settle_ticket(ticket, started_at, time.time(), rate)
            except Exception:
                pass
            fail('capability_unavailable', 'Cloud browser state could not be saved. The provider session is being safely reconciled.', 503)
        if connection.get('providerContextId') and connection.get('cloudLogin'):
            # Successful allocation counts as a use for the application's
            # inactivity-retention window. The provider profile itself has no
            # expiry, so Open Learn owns and enforces this boundary.
            now = time.time()
            with self.store.engine.begin() as conn:
                row = conn.execute(text('SELECT payload FROM site_connections WHERE id=:id AND owner_id=:owner'),
                                   {'id': connection['id'], 'owner': run['owner_id']}).first()
                if row:
                    saved = json.loads(row[0])
                    if saved.get('providerContextId') == connection['providerContextId']:
                        saved['browserContextLastUsedAt'] = now
                        saved['browserContextExpiresAt'] = now + PROFILE_RETENTION_SECONDS
                        conn.execute(text('UPDATE site_connections SET payload=:payload,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                                     {'payload': encoded(saved), 'now': now, 'id': connection['id'], 'owner': run['owner_id']})
        return session['id'], session['connectUrl']

    def execute(self, action, connection, run, previous=None):
        identifier, endpoint = self.session(connection, run)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint, timeout=20000)
            try:
                context = browser.contexts[0]
                blocked_navigation = []
                # Requests are checked in addition to the provider/network egress boundary.
                def route(request_route):
                    guard_browser_request(request_route, connection, blocked_navigation)
                context.route('**/*', route)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(12000)
                try:
                    if action.tool == 'navigate': page.goto(action.url, wait_until='domcontentloaded')
                    elif page.url == 'about:blank': page.goto(connection['origin'], wait_until='domcontentloaded')
                    else: check_url(page.url, connection, resolve=True)
                except Exception:
                    if blocked_navigation:
                        return Observation(url=connection['origin'],document_revision='login-handoff',status='login_required')
                    fail('capability_unavailable','The website did not finish opening. Check the connection and continue.',503)
                if action.tool in {'click', 'fill', 'press_key', 'scroll'}:
                    fresh = page.evaluate(OBSERVER.read_text(encoding='utf-8') + '\nopenLearnObserve()')
                    if previous and action.snapshot_id and fresh['documentRevision'] != previous['documentRevision']:
                        fail('stale_reference', 'The page changed. Read it again.', 409)
                    element = page.locator('[data-openlearn-ref="' + (action.element_ref or '') + '"]')
                    if action.tool == 'click': element.click()
                    elif action.tool == 'fill': element.fill(action.value or '')
                    elif action.tool == 'press_key': element.press(action.value or 'Enter')
                    elif action.element_ref: element.evaluate('(el,dy)=>el.scrollBy(0,dy)', action.amount if action.direction == 'down' else -action.amount)
                    else: page.mouse.wheel(0, action.amount if action.direction == 'down' else -action.amount)
                if action.tool == 'read_platform_resource':
                    from ..adapters.canvas import platform_script, resource_url
                    data = page.evaluate(platform_script(), {'url': resource_url(connection, action), 'origin': connection['origin']})
                elif action.tool == 'read_document':
                    url = action.url or next((c['href'] for c in previous['controls'] if c['ref'] == action.element_ref), None)
                    check_url(url, connection, resolve=True)
                    response = context.request.get(url, max_redirects=0)
                    if not response.ok or len(response.body()) > 8_000_000: fail('unsupported_file', 'Document unavailable or too large.', 422)
                    from ..adapters.documents import document_observation
                    return document_observation(url, response.body(), response.headers.get('content-type', ''))
                else:
                    query = action.query if action.tool == 'find' else None
                    data = page.evaluate(OBSERVER.read_text(encoding='utf-8') + '\nopenLearnObserve(' + json.dumps(query) + ')')
                if action.tool == 'capture_screenshot':
                    if data.get('status') != 'login_required':
                        image=page.screenshot(type='png',mask=[page.locator('input,textarea,[contenteditable="true"]')])
                        fresh=page.evaluate(OBSERVER.read_text(encoding='utf-8') + '\nopenLearnObserve()')
                        data=fresh
                        if fresh.get('status')!='login_required':data['screenshot']=base64.b64encode(image).decode()
                check_url(data['url'], connection, resolve=True)
                return Observation.model_validate(data)
            finally:
                browser.close()

    def close(self, owner, run_id):
        with self.store.engine.connect() as conn:
            sessions = conn.execute(text("SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status IN ('active','login')"), {'owner': owner, 'run': run_id}).mappings().all()
        for row in sessions:
            stop_and_settle(self.store, self.provider, row)

    def release_control(self, owner, run_id):
        """Revoke all issued human links by confirming session termination."""
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status IN ('active','login')"),{'owner':owner,'run':run_id}).mappings().all()
        for row in rows:
            if not stop_and_settle(self.store, self.provider, row):
                return False
        return True
