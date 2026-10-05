"""Temporary Browserbase sessions with deterministic Playwright actions."""
import base64
import json
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

OBSERVER = Path(__file__).resolve().parents[1] / 'observer.js'


def readiness():
    import importlib.util
    return {'enabled': os.getenv('OPENLEARN_CLOUD_BROWSER_ENABLED') == 'true',
            'credentialsConfigured': bool(os.getenv('BROWSERBASE_API_KEY') and os.getenv('BROWSERBASE_PROJECT_ID')),
            'runtimeInstalled': importlib.util.find_spec('playwright') is not None,
            'egressVerified': os.getenv('OPENLEARN_BROWSER_EGRESS_VERIFIED') == 'true',
            'privateLoginVerified': os.getenv('OPENLEARN_BROWSER_PRIVATE_VERIFIED') == 'true'}


class BrowserbaseProvider:
    def request(self, method, path, data=None):
        response = httpx.request(method, 'https://api.browserbase.com/v1/' + path,
            headers={'X-BB-API-Key': os.environ['BROWSERBASE_API_KEY']}, json=data, timeout=20)
        if response.status_code == 404 and (method == 'DELETE' or method == 'POST' and (data or {}).get('status') == 'REQUEST_RELEASE'):
            return {}
        response.raise_for_status()
        return response.json() if response.content else {}

    def create(self, connection):
        settings = {'recordSession': False, 'logSession': False, 'solveCaptchas': False,
                    'allowedDomains': [urlsplit(u).hostname for u in [connection['origin'], *connection.get('approvedOrigins', [])]],
                    'viewport': {'width': 1280, 'height': 900}}
        if connection.get('providerContextId'):
            settings['context'] = {'id': connection['providerContextId'], 'persist': True}
        return self.request('POST', 'sessions', {'projectId': os.environ['BROWSERBASE_PROJECT_ID'],
                             'browserSettings': settings, 'timeout': 600, 'keepAlive': True})

    def stop(self, identifier):
        self.request('POST', f'sessions/{identifier}', {'projectId': os.environ['BROWSERBASE_PROJECT_ID'], 'status': 'REQUEST_RELEASE'})

    def create_context(self):
        return self.request('POST', 'contexts', {'projectId': os.environ['BROWSERBASE_PROJECT_ID']})['id']

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
        report = readiness()
        if not all(report[k] for k in ('enabled', 'credentialsConfigured', 'runtimeInstalled', 'egressVerified')):
            fail('capability_unavailable', 'Cloud browser setup and egress verification are required. Use the browser companion.', 503)
        if connection.get('cloudLogin') and not report['privateLoginVerified']:
            fail('capability_unavailable', 'Private cloud login has not been verified for this deployment.', 503)
        with self.store.transaction() as conn:
            row = conn.execute(text("SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status='active' AND expires_at>:now"),
                               {'owner': run['owner_id'], 'run': run['id'], 'now': time.time()}).mappings().first()
        if row:
            return row['provider_session'], json.loads(row['payload'])['connectUrl']
        session = self.provider.create(connection)
        try:
            with self.store.transaction() as conn:
                conn.execute(text('''INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload)
                    VALUES(:id,:owner,:run,:connection,:session,'active',:expires,:payload)
                    ON CONFLICT(run_id) DO UPDATE SET provider_session=excluded.provider_session,status='active',expires_at=excluded.expires_at,payload=excluded.payload'''),
                    {'id': uid('bs'), 'owner': run['owner_id'], 'run': run['id'], 'connection': connection['id'], 'session': session['id'],
                     'expires': time.time()+600, 'payload': encoded({'connectUrl': session['connectUrl']})})
        except Exception:
            self.provider.stop(session['id']); raise
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
                    url = request_route.request.url
                    try:
                        if request_route.request.method not in {'GET','HEAD','OPTIONS'}:
                            request_route.abort(); return
                        from ...url_ingestion import validate_public_url
                        validate_public_url(url)
                        if request_route.request.is_navigation_request(): check_url(url, connection)
                        request_route.continue_()
                    except Exception:
                        if request_route.request.is_navigation_request(): blocked_navigation.append(url)
                        request_route.abort()
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
            sessions = conn.execute(text("SELECT id,provider_session FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status IN ('active','login')"), {'owner': owner, 'run': run_id}).mappings().all()
        for row in sessions:
            try: self.provider.stop(row['provider_session'])
            except Exception: continue
            with self.store.engine.begin() as conn:
                conn.execute(text("UPDATE browser_session_leases SET status='closed',payload='{}' WHERE id=:id"), {'id': row['id']})

    def release_control(self, owner, run_id):
        """Revoke all issued human links by confirming session termination."""
        with self.store.engine.connect() as conn:
            rows=conn.execute(text("SELECT id,provider_session FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status IN ('active','login')"),{'owner':owner,'run':run_id}).mappings().all()
        for row in rows:
            try:
                self.provider.stop(row['provider_session'])
                result=self.provider.request('GET','sessions/'+row['provider_session'])
                if result.get('status') not in {'COMPLETED','TIMED_OUT','ERROR'}:return False
            except Exception:return False
            with self.store.transaction() as conn:
                conn.execute(text("UPDATE browser_session_leases SET status='closed',payload='{}' WHERE id=:id"),{'id':row['id']})
        return True
