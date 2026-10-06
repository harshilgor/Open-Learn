import json
import os
import time
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
                                      queue_context_cleanup, require_cloud_ready, stop_and_settle)
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
            if context_id:
                # Old deployments may have left a persistent context behind.
                # Queue its deletion first so a transient provider failure does
                # not make the unmetered context unreachable to cleanup.
                try:
                    queue_context_cleanup(self.store, owner, {'providerContextId': context_id})
                except Exception:
                    fail('capability_unavailable', 'The sign-in browser closed, but saved browser data could not be queued for cleanup. Retry shortly.', 503)
                try:
                    provider.delete_context(context_id)
                    with self.store.engine.begin() as conn:
                        conn.execute(text('DELETE FROM browser_provider_cleanup WHERE id=:id'),
                                     {'id': 'context:' + context_id})
                except Exception:
                    pass
            with self.store.transaction() as conn:
                fresh = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
                if fresh['revision'] != revision: fail('revision_conflict', 'The connection changed.', 409)
                fresh.pop('loginSessionId', None)
                fresh.pop('providerContextId', None)
                fresh.update(status='unpaired', cloudLogin=False, revision=revision+1)
                conn.execute(text('UPDATE site_connections SET status=:status,revision=:revision,payload=:payload WHERE id=:id AND owner_id=:owner'), {'status':fresh['status'],'revision':fresh['revision'],'payload':encoded(self.clean(fresh)),'id':identifier,'owner':owner})
            return public_connection(fresh)
        require_cloud_ready()
        fail('capability_unavailable',
             'Cloud sign-in is unavailable until persistent browser contexts have a bounded, metered lifecycle.', 503)

    def patch(self, owner, identifier, command):
        with self.store.transaction() as conn:
            self.serialize(conn)
            item = self.repo.row(conn, 'site_connections', owner, identifier, lock=True)
            if item['revision'] != command.expected_revision: fail('revision_conflict', 'Refresh this connection.', 409)
            changes = command.model_dump(by_alias=True, exclude_none=True)
            changes.pop('expectedRevision', None)
            if 'timezone' in changes: timezone(changes['timezone'])
            if 'approvedOrigins' in changes: changes['approvedOrigins'] = [origin(u) for u in changes['approvedOrigins']]
            item.update(changes)
            item['revision'] += 1
            conn.execute(text('UPDATE site_connections SET payload=:payload, revision=:rev,updated_at=:now WHERE id=:id AND owner_id=:owner'),
                         {'payload': encoded(self.clean(item)), 'rev': item['revision'], 'now': time.time(), 'id': identifier, 'owner': owner})
            if item.get('preferred'): self._clear_preferences(conn, owner, identifier, item['category'])
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
                self.create(owner, ConnectionCreate(label=selected_origin, origin=selected_origin, category='university_lms' if academic else 'public_web',
                            platform='canvas' if 'canvas' in run['message'].lower() else 'generic',
                            executor='local' if academic else 'cloud' if os.getenv('OPENLEARN_CLOUD_BROWSER_ENABLED') == 'true' else 'public_fetch'))
                return self.resolve(owner, run, intent)
        alias = (intent.source_alias or '').lower()
        if alias:
            found = [c for c in connections if alias in [c['label'].lower(), *[a.lower() for a in c.get('aliases', [])]]]
            if len(found) == 1: return found[0]
        message = run['message'].lower()
        explicit = [c for c in connections if any(a.lower() in message for a in [c['label'], *c.get('aliases', [])] if len(a) > 2)]
        if len(explicit) == 1: return explicit[0]
        category = [c for c in connections if c.get('category') == 'university_lms'] if any(w in message for w in ('university', 'canvas', 'classes', 'midterm', 'courses')) else connections
        preferred = [c for c in category if c.get('preferred')]
        if len(preferred) == 1: return preferred[0]
        return category[0] if len(category) == 1 else None
