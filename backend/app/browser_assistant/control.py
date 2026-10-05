"""Durable human/agent handoffs. Human access waits for executor quiescence."""
import time
import base64
import json
from urllib.parse import urlsplit

from sqlalchemy import text
from .store import AssistantStore, public_run
from .policy import TERMINAL
from ..identity import fail
from ..workflow_store import uid


class BrowserControl:
    def __init__(self, store):
        self.store = store
        self.repo = AssistantStore(store)

    def command(self, owner, identifier, command):
        with self.store.transaction() as conn:
            run = self.repo.run(conn, owner, identifier)
            if run['revision'] != command.expected_revision:
                fail('revision_conflict', 'Refresh the browser task before changing control.', 409)
            if run['status'] in TERMINAL or run.get('runtime_owner') == 'agent_v2':
                fail('control_unavailable', 'This task has no active browser.', 409)
            connection = self.repo.row(conn, 'site_connections', owner, run.get('connectionId'), lock=True)
            if connection['status'] == 'revoked': fail('connection_revoked', 'Reconnect this website.', 409)
            if connection['executor'] == 'public_fetch': fail('control_unavailable', 'This connection reads public files without an interactive browser.', 409)
            control = run.get('browserControl') or {}
            if command.action == 'takeover':
                if control.get('owner') in {'human', 'requesting', 'returning'}:
                    return public_run(run)
                control = {'owner': 'requesting', 'generation': uid('control'),
                           'executor': connection['executor'], 'requestedAt': time.time()}
                if connection['executor'] == 'cloud' and not run.get('browserInputInFlight'):
                    control['owner'] = 'human'
                run = self.repo.update_run(conn, run, status='paused', browserControl=control,
                    pendingCommand=None, question='Waiting for automation to stop.' if control['owner']=='requesting' else 'You control the browser. Return control when ready.')
                conn.execute(text("UPDATE assistant_steps SET status='cancelled' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','dispatched')"), {'owner': owner, 'run': identifier})
                self.repo.event(conn, run, 'browser.takeover_requested', run['question'], generation=control['generation'])
                return public_run(run)
            if control.get('owner') not in {'human','returning'}:
                fail('control_unavailable', 'Request browser control first.', 409)
            # Disable issuance of further human links before releasing compute.
            control = {**control, 'owner': 'returning'}
            run = self.repo.update_run(conn, run, browserControl=control)
        if connection['executor'] == 'cloud':
            from .executors.cloud import CloudExecutor
            if not CloudExecutor(self.store).release_control(owner, identifier):
                fail('control_release_pending', 'The browser is still closing. Retry returning control; automation remains paused.', 503)
        with self.store.transaction() as conn:
            run = self.repo.run(conn, owner, identifier)
            if run['status'] in TERMINAL or run.get('browserControl',{}).get('generation') != control['generation']:
                fail('revision_conflict', 'Browser control changed.', 409)
            connection = self.repo.row(conn, 'site_connections', owner, run['connectionId'], lock=True)
            if connection['status'] == 'revoked': fail('connection_revoked', 'Reconnect this website.', 409)
            run = self.repo.update_run(conn, run, status='queued', browserControl={
                'owner':'agent','generation':uid('control'),'executor':connection['executor']},
                browserInputInFlight=None, pendingCommand=None, reobserve=True,
                lastSnapshot=None, snapshots=[], error=None, question=None, activeSince=time.time())
            self.repo.event(conn, run, 'browser.control_returned', 'Control returned; checking the page before continuing.')
            self.repo.enqueue(conn, run, 'assistant_step' if run.get('intent') else 'assistant_intent')
        return public_run(run)

    def begin(self, owner, identifier, pending):
        with self.store.transaction() as conn:
            run = self.repo.run(conn, owner, identifier)
            if run['status'] != 'running' or run.get('pendingCommand') != pending or run.get('browserControl',{}).get('owner','agent') != 'agent':
                return False
            if run.get('browserInputInFlight'): fail('control_busy', 'Previous browser input has not been reconciled.', 409)
            self.repo.update_run(conn, run, browserInputInFlight=pending)
        return True

    def end(self, owner, identifier, pending):
        with self.store.transaction() as conn:
            run = self.repo.run(conn, owner, identifier)
            if run.get('browserInputInFlight') != pending: return
            changes = {'browserInputInFlight':None}
            control = run.get('browserControl',{})
            if control.get('owner') == 'requesting' and run['status'] not in TERMINAL:
                changes.update(browserControl={**control,'owner':'human'}, question='You control the browser. Return control when ready.')
            run = self.repo.update_run(conn, run, **changes)
            if changes.get('browserControl'):
                self.repo.event(conn, run, 'browser.takeover_ready', run['question'], generation=control['generation'])

    def acknowledge(self, principal, identifier, generation):
        with self.store.transaction() as conn:
            run = self.repo.run(conn, principal.owner_id, identifier)
            connection = self.repo.row(conn,'site_connections',principal.owner_id,run['connectionId'],lock=True)
            control = run.get('browserControl',{})
            if principal.kind != 'browser' or connection.get('deviceId') != principal.device_id:
                fail('device_scope_denied','Use the paired browser device.',403)
            if connection['status']=='revoked' or run['status'] in TERMINAL or control.get('generation') != generation or control.get('owner') not in {'requesting','human'}:
                fail('stale_command','This handoff is no longer active.',409)
            if control['owner']=='human': return {'status':'accepted','duplicate':True}
            run=self.repo.update_run(conn,run,browserControl={**control,'owner':'human'},question='Automation stopped. Use the connected desktop browser, then return control.')
            self.repo.event(conn,run,'browser.takeover_ready',run['question'],generation=generation)
        return {'status':'accepted'}

    def view(self, owner, identifier):
        with self.store.transaction() as conn:
            run=self.repo.run(conn,owner,identifier)
            connection=self.repo.row(conn,'site_connections',owner,run['connectionId'],lock=True)
            control=run.get('browserControl',{})
            if connection['status']=='revoked' or run['status'] in TERMINAL or control.get('owner')!='human':
                fail('control_not_ready','Automation must stop before opening the browser.',409)
            if connection['executor']=='local':return {'kind':'local','generation':control['generation'],'message':'Use the connected desktop browser.'}
            from .executors.cloud import readiness, CloudExecutor
            if not readiness()['privateLoginVerified']:fail('capability_unavailable','Private browser handoff has not been verified.',503)
            row=conn.execute(text("SELECT provider_session,expires_at FROM browser_session_leases WHERE owner_id=:owner AND run_id=:run AND status='active' AND expires_at>:now"),{'owner':owner,'run':identifier,'now':time.time()}).mappings().first()
            if not row:fail('control_unavailable','Browser session expired. Return control to reconnect.',409)
            url=CloudExecutor(self.store).provider.live_view(row['provider_session'])
            parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.hostname!='debug.browserbase.com' or parsed.username or parsed.password:
                fail('capability_unavailable','Provider returned an unsupported browser view.',503)
            return {'kind':'cloud','url':url,'expiresAt':min(time.time()+60,row['expires_at']),'generation':control['generation']}

    def preview(self, owner, identifier):
        """Observation permission exposes retained evidence, never input URLs."""
        with self.store.transaction() as conn:
            run=self.repo.run(conn,owner,identifier)
            connection=self.repo.row(conn,'site_connections',owner,run['connectionId'],lock=True)
            if connection['status']=='revoked' or run['status']=='waiting_for_login' or run.get('browserControl',{}).get('owner','agent')!='agent':
                fail('preview_unavailable','Browser observation is paused during private handoff.',409)
            row=conn.execute(text('SELECT payload,created_at FROM browser_snapshots WHERE id=:id AND owner_id=:owner AND run_id=:run AND expires_at>:now'),{'id':run.get('lastSnapshot'),'owner':owner,'run':identifier,'now':time.time()}).mappings().first()
            if not row:return {'state':'waiting','message':'No verified page observation is available yet.'}
            snapshot=json.loads(row['payload'])
            from .policy import safe_url
            result={'state':'available','title':snapshot.get('title',''),'url':safe_url(snapshot['url']),
                    'observedAt':row['created_at'],'blocks':[{'text':b['text'][:2000]} for b in snapshot.get('blocks',[])[:8]]}
            key=snapshot.get('imageObject')
            if key and conn.execute(text('SELECT 1 FROM assistant_objects WHERE id=:id AND owner_id=:owner AND expires_at>:now'),{'id':key,'owner':owner,'now':time.time()}).first():
                from .evidence import evidence_objects
                result['image']='data:'+snapshot.get('imageMime','image/png')+';base64,'+base64.b64encode(evidence_objects(self.store).read(owner,key)).decode()
            return result
