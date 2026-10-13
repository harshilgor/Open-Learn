import json
import hashlib
import os
import time
from fastapi import HTTPException
from sqlalchemy import text
from .store import AssistantStore, public_connection
from .policy import origin, timezone, TERMINAL
from ..identity import issue_device_grant, fail, current_principal
from ..workflow_store import encoded, uid


class Connections:
    def __init__(self, store):
        self.store = store
        self.repo = AssistantStore(store)

    @staticmethod
    def serialize(conn):
        if conn.dialect.name == 'sqlite': conn.exec_driver_sql('BEGIN IMMEDIATE')

    def create(self, owner, command):
        data = command.model_dump(by_alias=True)
        data['origin'] = origin(data['origin'])
        data['approvedOrigins'] = sorted({origin(u) for u in data['approvedOrigins']} - {data['origin']})
        timezone(data['timezone'])
        if data['cloudLogin'] and data['executor'] != 'cloud': fail('invalid_input', 'Cloud login requires a cloud connection.', 422)
        if data['cloudLogin']: data['browserProfileConsentAt'] = time.time()
        data.update(id=uid('site'), revision=1, status='connected' if data['executor'] == 'public_fetch' else 'unpaired',
                    createdAt=time.time(), lastSuccessfulSync=None, deviceId=None)
        with self.store.transaction() as conn:
            conn.execute(text('INSERT INTO site_connections(id,owner_id,revision,status,origin,payload,created_at,updated_at) VALUES(:id,:owner,1,:status,:origin,:payload,:now,:now)'),
                         {'id': data['id'], 'owner': owner, 'status': data['status'], 'origin': data['origin'], 'payload': encoded(data), 'now': time.time()})
            if data['preferred']: self._clear_preferences(conn, owner, data['id'], data['category'])
        return public_connection(data)

    def _clear_preferences(self, conn, owner, identifier, category):
        for r in conn.execute(text('SELECT id,payload FROM site_connections WHERE owner_id=:owner AND id<>:id'), {'owner': owner, 'id': identifier}).mappings():
            p = json.loads(r['payload'])
            if p.get('preferred') and p.get('category') == category:
                p['preferred'] = False
                conn.execute(text('UPDATE site_connections SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner'), {'payload': encoded(p), 'id': r['id'], 'owner': owner})

    def cloud_login(self, owner, identifier, revision, finish=False):
        from .executors.cloud import (BrowserbaseProvider, TERMINAL_SESSION_STATES,
                                      PROFILE_RETENTION_SECONDS, SESSION_TTL_SECONDS,
                                      RECONCILIATION_GRACE_SECONDS, queue_context_cleanup,
                                      readiness, require_cloud_ready, stop_and_settle)
        item = self.repo.read('site_connections', owner, identifier)
        if item['revision'] != revision: fail('revision_conflict', 'Refresh this connection.', 409)
        if item['executor'] != 'cloud' or item['status'] == 'revoked': fail('invalid_input', 'Select a connected cloud browser.', 422)
        provider = BrowserbaseProvider()
        if finish:
            if not item.get('loginSessionId'): fail('invalid_input', 'Start a sign-in session first.', 422)
            run_id = 'login:' + identifier
            with self.store.engine.connect() as conn:
                lease = conn.execute(text('SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run'),
                                     {'owner': owner, 'run': run_id}).mappings().first()
            if lease:
                if lease['status'] != 'closed' and not stop_and_settle(self.store, provider, lease):
                    fail('capability_unavailable', 'The sign-in browser is still being safely closed. Retry shortly.', 503)
            else:
                try:
                    provider.stop(item['loginSessionId'])
                    state = provider.request('GET', 'sessions/' + item['loginSessionId']).get('status', '')
                    if str(state).upper() not in TERMINAL_SESSION_STATES:
                        fail('capability_unavailable', 'The sign-in browser is still being safely closed. Retry shortly.', 503)
                except Exception:
                    fail('capability_unavailable', 'The sign-in browser is still being safely closed. Retry shortly.', 503)

            context_id = item.get('providerContextId')
            if not item.get('cloudLogin') or not context_id:
                fail('privacy_consent_required', 'Enable remembered sign-in before saving this browser session.', 403)
            if not readiness()['privateLoginVerified']:
                # A deployment may have closed the private-profile gate while
                # a sign-in handoff was open. Never persist that profile;
                # enqueue deletion durably before removing its connection pointer.
                try:
                    queue_context_cleanup(self.store, owner, {'providerContextId':context_id})
                except Exception:
                    fail('capability_unavailable', 'The private browser session closed, but its saved profile could not be queued for deletion. Retry shortly.', 503)
                with self.store.transaction() as conn:
                    fresh = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
                    if fresh['revision'] != revision: fail('revision_conflict', 'The connection changed.', 409)
                    for key in ('loginSessionId', 'loginExpiresAt', 'providerContextId',
                                'browserContextExpiresAt', 'browserContextLastUsedAt',
                                'browserProfileConsentAt'):
                        fresh.pop(key, None)
                    fresh.update(status='connected', cloudLogin=False, revision=revision+1)
                    conn.execute(text('UPDATE site_connections SET status=:status,revision=:revision,payload=:payload,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                                 {'status':fresh['status'],'revision':fresh['revision'],'payload':encoded(self.clean(fresh)),
                                  'now':time.time(),'id':identifier,'owner':owner})
                try:
                    provider.delete_context(context_id)
                    with self.store.engine.begin() as conn:
                        conn.execute(text('DELETE FROM browser_provider_cleanup WHERE id=:id'), {'id':'context:'+context_id})
                except Exception:
                    # The durable cleanup row will retry provider deletion.
                    pass
                return public_connection(fresh)
            # Browserbase persists the encrypted user-data directory as the
            # session closes. Its docs recommend a short sync window before
            # reusing the context in another session.
            time.sleep(3)
            with self.store.transaction() as conn:
                fresh = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
                if fresh['revision'] != revision: fail('revision_conflict', 'The connection changed.', 409)
                fresh.pop('loginSessionId', None)
                fresh.pop('loginExpiresAt', None)
                fresh.update(status='connected', cloudLogin=True,
                             browserContextLastUsedAt=time.time(),
                             browserContextExpiresAt=time.time() + PROFILE_RETENTION_SECONDS,
                             revision=revision+1)
                conn.execute(text('UPDATE site_connections SET status=:status,revision=:revision,payload=:payload WHERE id=:id AND owner_id=:owner'), {'status':fresh['status'],'revision':fresh['revision'],'payload':encoded(self.clean(fresh)),'id':identifier,'owner':owner})
            return public_connection(fresh)
        require_cloud_ready()
        if not readiness()['privateLoginVerified']:
            fail('capability_unavailable', 'Private browser handoff is unavailable until its isolation, link-expiry, and deletion acceptance checks pass.', 503)
        if not item.get('cloudLogin'):
            fail('privacy_consent_required', 'Turn on “Remember sign-in” before saving a login in this private browser.', 403)
        if item.get('loginSessionId'):
            run_id = 'login:' + identifier
            with self.store.engine.connect() as conn:
                lease = conn.execute(text("SELECT status,provider_session,expires_at FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run"),
                                     {'owner':owner,'run':run_id}).mappings().first()
            if lease and lease['status']=='login' and lease['expires_at'] > time.time():
                return {'connection':public_connection(item), 'liveViewUrl':provider.live_view(lease['provider_session'])}
            fail('login_in_progress', 'The sign-in browser is closing. Wait for cleanup, then retry.', 409)

        with self.store.engine.connect() as conn:
            active = conn.execute(text("SELECT 1 FROM browser_session_leases WHERE owner_id=:owner AND connection_id=:connection AND status IN ('active','login') LIMIT 1"),
                                  {'owner':owner,'connection':identifier}).first()
        if active:
            fail('login_in_progress', 'Finish or wait for the current browser task before starting sign-in.', 409)

        context_id = item.get('providerContextId')
        context_expires = item.get('browserContextExpiresAt')
        if context_id and (not isinstance(context_expires, (int, float)) or context_expires <= time.time()):
            queue_context_cleanup(self.store, owner, item)
            try:
                provider.delete_context(context_id)
                with self.store.engine.begin() as conn:
                    conn.execute(text('DELETE FROM browser_provider_cleanup WHERE id=:id'), {'id':'context:'+context_id})
            except Exception:
                pass
            context_id = None

        created_context = False
        if not context_id:
            opaque_name = 'openlearn-' + hashlib.sha256(f'{owner}:{identifier}'.encode()).hexdigest()[:24]
            try:
                context = provider.create_context(opaque_name)
                context_id = context.get('id') if isinstance(context, dict) else None
                if not isinstance(context_id, str) or not context_id:
                    raise ValueError('Browserbase returned no context identifier.')
                created_context = True
            except Exception:
                fail('capability_unavailable', 'A private browser profile could not be created. No sign-in session was opened.', 503)

        from ..usage.operations import begin_external, configured_rate, rate_liability
        from ..usage.ledger import UsageError
        try:
            rate = configured_rate('OPENLEARN_BROWSERBASE_USD_PER_MINUTE')
            liability = rate_liability('OPENLEARN_BROWSERBASE_USD_PER_MINUTE', 10, 1)
            started_at = time.time()
            ticket = begin_external('browser', {'milliseconds': SESSION_TTL_SECONDS * 1000}, liability,
                key=f'browser-login:{owner}:{identifier}:{revision}', root=f'browser-login:{owner}:{identifier}',
                seconds=SESSION_TTL_SECONDS + RECONCILIATION_GRACE_SECONDS, provider='browserbase', model='chromium',
                provider_rates={'usd_nano_per_minute':rate})
        except UsageError as exc:
            if created_context:
                queue_context_cleanup(self.store, owner, {'providerContextId':context_id})
            fail(exc.detail.get('code','usage_provider_unavailable'),
                 exc.detail.get('message','Cloud browser usage is unavailable.'), exc.status_code)
        if ticket is None:
            if created_context:
                queue_context_cleanup(self.store, owner, {'providerContextId':context_id})
            fail('usage_accounting_unavailable', 'Cloud sign-in requires an authenticated usage account.', 503)

        session_connection = {**item, 'providerContextId':context_id}
        session = None
        payload = {'usageReservationId':ticket[2]['id'], 'usageStartedAt':started_at,
                   'usageRateNanoPerMinute':rate}
        try:
            session = provider.create(session_connection, usage_ticket=ticket, persist_context=True)
            if not isinstance(session, dict) or not session.get('id') or not session.get('connectUrl'):
                raise ValueError('Browserbase returned an incomplete sign-in session.')
            link = provider.live_view(session['id'])
            from urllib.parse import urlsplit
            parsed = urlsplit(link)
            if parsed.scheme != 'https' or parsed.hostname != 'debug.browserbase.com' or parsed.username or parsed.password:
                raise ValueError('Browserbase returned an unsupported private browser link.')
            expires_at = started_at + SESSION_TTL_SECONDS
            payload['connectUrl'] = session['connectUrl']
            with self.store.transaction() as conn:
                fresh = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
                if fresh['revision'] != revision:
                    fail('revision_conflict', 'The connection changed while the sign-in session was starting.', 409)
                fresh.update(providerContextId=context_id, loginSessionId=session['id'],
                             loginExpiresAt=expires_at, browserContextLastUsedAt=started_at,
                             browserContextExpiresAt=started_at + PROFILE_RETENTION_SECONDS,
                             status='logging_in', revision=revision+1)
                conn.execute(text('UPDATE site_connections SET status=:status,revision=:revision,payload=:payload,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                             {'status':fresh['status'],'revision':fresh['revision'],'payload':encoded(self.clean(fresh)),
                              'now':started_at,'id':identifier,'owner':owner})
                conn.execute(text('''INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload)
                    VALUES(:id,:owner,:run,:connection,:session,'login',:expires,:payload)
                    ON CONFLICT(run_id) DO UPDATE SET connection_id=excluded.connection_id,provider_session=excluded.provider_session,
                      status='login',expires_at=excluded.expires_at,payload=excluded.payload'''),
                    {'id':'login_'+identifier,'owner':owner,'run':'login:'+identifier,'connection':identifier,
                     'session':session['id'],'expires':expires_at,'payload':encoded(payload)})
            return {'connection':public_connection(fresh), 'liveViewUrl':link}
        except Exception as exc:
            # A provider session may already exist even when persisting its
            # connection state or issuing the private Live View URL fails.
            # Make a durable lease before reconciling it so shutdown and usage
            # settlement survive a process restart.
            session_id = session.get('id') if isinstance(session, dict) else None
            stopped = False
            durable_lease = False
            if isinstance(session_id, str) and session_id:
                expires_at = locals().get('expires_at', started_at + SESSION_TTL_SECONDS)
                try:
                    with self.store.engine.begin() as conn:
                        conn.execute(text('''INSERT INTO browser_session_leases(id,owner_id,run_id,connection_id,provider_session,status,expires_at,payload)
                            VALUES(:id,:owner,:run,:connection,:session,'login',:expires,:payload)
                            ON CONFLICT(run_id) DO UPDATE SET connection_id=excluded.connection_id,provider_session=excluded.provider_session,
                              status='login',expires_at=excluded.expires_at,payload=excluded.payload'''),
                            {'id':'login_'+identifier,'owner':owner,'run':'login:'+identifier,'connection':identifier,
                             'session':session_id,'expires':expires_at,'payload':encoded(payload)})
                    durable_lease = True
                    with self.store.engine.connect() as conn:
                        lease = conn.execute(text('SELECT * FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run'),
                                             {'owner':owner,'run':'login:'+identifier}).mappings().first()
                    if lease:
                        stopped = stop_and_settle(self.store, provider, lease)
                except Exception:
                    stopped = False
                if stopped:
                    try:
                        with self.store.engine.begin() as conn:
                            fresh = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
                            if fresh.get('loginSessionId') == session_id:
                                fresh.pop('loginSessionId', None)
                                fresh.pop('loginExpiresAt', None)
                                if created_context:
                                    for key in ('providerContextId','browserContextExpiresAt','browserContextLastUsedAt'):
                                        fresh.pop(key, None)
                                fresh['status'] = 'connected'
                                fresh['revision'] += 1
                                conn.execute(text('UPDATE site_connections SET payload=:payload,status=:status,revision=:revision,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                                             {'payload':encoded(self.clean(fresh)),'status':fresh['status'],'revision':fresh['revision'],
                                              'now':time.time(),'id':identifier,'owner':owner})
                    except HTTPException:
                        pass  # The connection may have been revoked concurrently.
                # The cleanup worker waits for all provider leases to close
                # before deleting this context, so it is safe to queue even if
                # the immediate stop is still being reconciled.
                if created_context and durable_lease:
                    queue_context_cleanup(self.store, owner, {'providerContextId':context_id})
            # A failed create response is ambiguous: leave the profile alone so
            # cleanup cannot remove it while an unreported session is still
            # using it. The provider-side 10-minute session timeout bounds it.
            if isinstance(exc, HTTPException):
                raise
            fail('capability_unavailable', 'The private sign-in browser could not be opened. Any provider session is being safely reconciled.', 503)

    def patch(self, owner, identifier, command):
        cleanup_profile = None
        with self.store.transaction() as conn:
            self.serialize(conn)
            item = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
            if item['revision'] != command.expected_revision: fail('revision_conflict', 'Refresh this connection.', 409)
            changes = command.model_dump(by_alias=True, exclude_none=True)
            changes.pop('expectedRevision', None)
            if 'timezone' in changes: timezone(changes['timezone'])
            if 'approvedOrigins' in changes: changes['approvedOrigins'] = [origin(u) for u in changes['approvedOrigins']]
            if changes.get('cloudLogin') is True:
                if item['executor'] != 'cloud': fail('invalid_input', 'Remembered sign-in requires a cloud browser connection.', 422)
                item['browserProfileConsentAt'] = time.time()
            elif changes.get('cloudLogin') is False:
                if item.get('loginSessionId'):
                    fail('login_in_progress', 'Finish or wait for the private sign-in session before turning off remembered sign-in.', 409)
                active = conn.execute(text("SELECT 1 FROM browser_session_leases WHERE owner_id=:owner AND connection_id=:connection AND status IN ('active','login') LIMIT 1"),
                                      {'owner':owner,'connection':identifier}).first()
                if active:
                    fail('login_in_progress', 'Wait for the current browser task to finish before forgetting this sign-in.', 409)
                if item.get('providerContextId'): cleanup_profile = dict(item)
                for key in ('providerContextId', 'browserContextExpiresAt', 'browserContextLastUsedAt', 'browserProfileConsentAt'):
                    item.pop(key, None)
            item.update(changes)
            item['revision'] += 1
            conn.execute(text('UPDATE site_connections SET payload=:payload, revision=:rev,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                         {'payload': encoded(self.clean(item)), 'rev': item['revision'], 'now': time.time(), 'id': identifier, 'owner': owner})
            if item.get('preferred'): self._clear_preferences(conn, owner, identifier, item['category'])
        if cleanup_profile:
            from .executors.cloud import queue_context_cleanup
            queue_context_cleanup(self.store, owner, cleanup_profile)
        return public_connection(item)

    @staticmethod
    def clean(item):
        return {k: v for k, v in item.items() if k not in {'payload', 'owner_id', 'device_id', 'created_at', 'updated_at'}}

    def pair(self, owner, identifier):
        with self.store.transaction() as conn:
            self.serialize(conn)
            item = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
            if item['executor'] != 'local': fail('invalid_input', 'Only local-browser connections use device pairing.', 422)
            if item.get('deviceId'):
                conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE id=:id AND owner_id=:owner'), {'now': time.time(), 'id': item['deviceId'], 'owner': owner})
            grant = issue_device_grant(conn, owner, item['label'], 'browser')
            item.update(deviceId=grant['id'], status='connected', revision=item['revision']+1)
            conn.execute(text('UPDATE site_connections SET payload=:payload,device_id=:device,revision=:rev,status=:status WHERE id=:id AND owner_id=:owner'),
                         {'payload': encoded(self.clean(item)), 'device': grant['id'], 'rev': item['revision'], 'status': item['status'], 'id': identifier, 'owner': owner})
        return {'connectionId': identifier, 'deviceId': grant['id'], 'authToken': grant['token'], 'expiresAt': grant['expiresAt'],
                'origin': item['origin'], 'approvedOrigins': item.get('approvedOrigins', []), 'kind': 'browser'}

    def revoke(self, owner, identifier, delete_imports=False):
        with self.store.transaction() as conn:
            self.serialize(conn)
            item = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
            item.update(status='revoked', revision=item['revision']+1)
            conn.execute(text('UPDATE site_connections SET status=:status,revision=:rev,payload=:payload WHERE id=:id AND owner_id=:owner'),
                         {'status': item['status'], 'rev': item['revision'], 'payload': encoded(self.clean(item)), 'id': identifier, 'owner': owner})
            if item.get('deviceId'):
                conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE id=:id AND owner_id=:owner'), {'now': time.time(), 'id': item['deviceId'], 'owner': owner})
            runs = conn.execute(text('SELECT id FROM assistant_runs WHERE connection_id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).scalars().all()
            for run_id in runs:
                run = self.repo.run(conn, owner, run_id)
                if run['status'] not in TERMINAL:
                    run = self.repo.update_run(conn, run, status='cancelled', error='connection_revoked')
                    self.repo.event(conn, run, 'task.cancelled', 'Connection revoked; browser reading stopped.')
                    conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,cancel_requested=true,lease=NULL,expires=NULL WHERE owner_id=:owner AND target_id=:id AND status IN ('queued','running','retry_wait')"), {'owner': owner, 'id': run_id})
                conn.execute(text("UPDATE assistant_steps SET status='cancelled' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','dispatched')"), {'owner': owner, 'run': run_id})
            conn.execute(text('UPDATE connection_refresh_schedules SET active=false WHERE owner_id=:owner AND connection_id=:id'), {'owner': owner, 'id': identifier})
            if delete_imports:
                self._delete_imports(conn, owner, identifier)
        # Durable cleanup survives provider downtime.
        from .executors.cloud import queue_context_cleanup
        queue_context_cleanup(self.store, owner, item)
        return {'status': 'revoked', 'importedFactsDeleted': delete_imports}

    def _delete_imports(self, conn, owner, connection_id):
        from ..academic_planning import AcademicPlanningService
        svc = AcademicPlanningService(self.store)
        observations = svc.rows(conn, 'academic_observations', owner)
        removed = [o for o in observations if o.get('source',{}).get('connectionId') == connection_id and not o.get('override')]
        removed_ids = {o['id'] for o in removed}
        remaining = [o for o in observations if o['id'] not in removed_ids]
        for obs in removed:
            conn.execute(text('DELETE FROM academic_observations WHERE id=:id AND owner_id=:owner'), {'id':obs['id'],'owner':owner})
        affected = {o['entityId'] for o in removed}
        for entity in svc.rows(conn, 'academic_entities', owner):
            if entity['id'] not in affected: continue
            for field in list(entity['facts']):
                fact = svc.select_fact(remaining, entity['id'], field)
                if fact['observationId']: entity['facts'][field] = fact
                else: entity['facts'].pop(field)
            entity = svc.put(conn, 'academic_entities', owner, entity)
            from .reminders import schedule_entity
            schedule_entity(self.store,conn,owner,entity)
            conn.execute(text("UPDATE reminders SET status='cancelled' WHERE owner_id=:owner AND entity_id=:id"), {'owner':owner,'id':entity['id']})
        conn.execute(text('DELETE FROM browser_snapshots WHERE owner_id=:owner AND connection_id=:id'), {'owner':owner,'id':connection_id})

    def resolve(self, owner, run, intent):
        connections = [c for c in self.repo.list('site_connections', owner) if c['status'] != 'revoked']
        selected = run.get('connectionId')
        if selected:
            return next((c for c in connections if c['id'] == selected), None)
        if intent.source_url:
            selected_origin = origin(intent.source_url)
            found = [c for c in connections if c['origin'] == selected_origin]
            if len(found) == 1: return found[0]
            if not found:
                from .contracts import ConnectionCreate
                academic = 'canvas' in run['message'].lower() or 'discover_courses' in intent.operations
                executor = os.getenv('OPENLEARN_BROWSER_DEFAULT_EXECUTOR', '').strip()
                if executor and executor not in {'local', 'cloud', 'public_fetch'}:
                    fail('capability_unavailable', 'The default browser executor is misconfigured.', 503)
                if not executor:
                    executor = 'local' if academic else 'cloud' if os.getenv('OPENLEARN_CLOUD_BROWSER_ENABLED') == 'true' else 'public_fetch'
                self.create(owner, ConnectionCreate(label=selected_origin, origin=selected_origin, category='university_lms' if academic else 'public_web',
                            platform='canvas' if 'canvas' in run['message'].lower() else 'generic',
                            executor=executor))
                return self.resolve(owner, run, intent)
        alias = (intent.source_alias or '').lower()
        if alias:
            found = [c for c in connections if alias in [c['label'].lower(), c.get('platform','').lower(), *[a.lower() for a in c.get('aliases', [])]]]
            if len(found) == 1: return found[0]
            return None  # An explicit unknown destination must not select an unrelated preferred login.
        message = run['message'].lower()
        explicit = [c for c in connections if any(a.lower() in message for a in [c['label'], *c.get('aliases', [])] if len(a) > 2)]
        if len(explicit) == 1: return explicit[0]
        category = [c for c in connections if c.get('category') == 'university_lms'] if any(w in message for w in ('university', 'canvas', 'classes', 'midterm', 'courses')) else connections
        preferred = [c for c in category if c.get('preferred')]
        if len(preferred) == 1: return preferred[0]
        return category[0] if len(category) == 1 else None
