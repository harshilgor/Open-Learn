"""Dedicated notification process and leased action / transport jobs."""
import json
import os
import time
from sqlalchemy import text
from .workflow_store import WorkflowStore, encoded
from .execution import LeaseHeartbeat, job_scope
from .identity import assert_owner_active
from .reminder_service import ReminderService
from .reminder_actions import ReminderActionRunner


class NotificationsWorker:
    def __init__(self,store,provider_getter=lambda:None):self.store=store;self.provider_getter=provider_getter
    def tick(self):
        from .calendar.google_writes import tick_google_writes
        tick_google_writes(self.store)
        from .calendar.google import tick_google_calendars
        tick_google_calendars(self.store)
        from .calendar.reminders import prepare_calendar_reminders
        prepare_calendar_reminders(self.store)
        from .browser_assistant.reminders import tick_reminders
        tick_reminders(self.store)
        counts=ReminderService(self.store).tick()
        jobs=WorkflowStore(self.store)
        for identifier in jobs.ready_ids('interactive',{'reminder_actions','general_reminder_dispatch','reminder_dispatch'},30):
            job=jobs.claim(identifier,lease_seconds=180)
            if not job:continue
            heartbeat=LeaseHeartbeat(self.store,job)
            try:
                with job_scope(job):
                    if job['kind']=='reminder_actions':ReminderActionRunner(self.store,provider=self.provider_getter()).execute(job)
                    elif job['kind']=='reminder_dispatch':
                        from .browser_assistant.reminders import dispatch_push
                        dispatch_push(self.store,job)
                    else:self.dispatch(job)
            except Exception:jobs.fail(job,'worker_failed',retryable=True)
            finally:heartbeat.close()
        if os.getenv('OPENLEARN_EXPO_PUSH_ENABLED')=='true':
            from .agent_execution.responsibilities import Responsibilities
            Responsibilities(self.store).receipts(time.time())
        return counts
    def run(self,stop,once=False):
        while not stop.is_set():
            try:self.tick()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('Notification tick failed (%s)',type(exc).__name__)
            if once:return
            stop.wait(5)
    def dispatch(self,job):
        jobs=WorkflowStore(self.store)
        with self.store.transaction() as conn:
            jobs.validate_lease(conn,job)
            row=conn.execute(text('SELECT n.*,r.status AS reminder_status FROM notification_deliveries n JOIN reminders r ON r.id=n.reminder_id AND r.owner_id=n.owner_id WHERE n.id=:id AND n.owner_id=:owner'),{'id':job['target_id'],'owner':job['owner_id']}).mappings().one()
            assert_owner_active(conn,row['owner_id'])
            if row['status']!='pending':jobs.finish(conn,job,{'status':row['status']});return
            if row['reminder_status']=='cancelled' or time.time()-row['created_at']>86400:
                conn.execute(text("UPDATE notification_deliveries SET status='expired' WHERE id=:id"),{'id':row['id']});jobs.finish(conn,job,{'status':'expired'});return
            # Fence ambiguous external sends: retrying after an unknown outcome
            # must not duplicate a push. Inbox remains the durable guarantee.
            conn.execute(text("UPDATE notification_deliveries SET status='outcome_unknown' WHERE id=:id AND status='pending'"),{'id':row['id']})
            targets=conn.execute(text('SELECT id,payload FROM notification_subscriptions WHERE owner_id=:owner AND active=true'),{'owner':row['owner_id']}).mappings().all()
        payload=json.loads(row['payload']);status='unconfigured'
        if row['channel']=='push' and os.getenv('OPENLEARN_VAPID_PRIVATE_KEY'):
            from pywebpush import webpush,WebPushException
            targets=[t for t in targets if json.loads(t['payload']).get('kind')!='expo']
            status='no_subscription' if not targets else 'sent_unconfirmed'
            for target in targets:
                try:webpush(json.loads(target['payload']),encoded(payload),vapid_private_key=os.environ['OPENLEARN_VAPID_PRIVATE_KEY'],vapid_claims={'sub':os.environ['OPENLEARN_VAPID_SUBJECT']},ttl=300,timeout=10)
                except WebPushException as exc:
                    status='outcome_unknown'
                    if exc.response is not None and exc.response.status_code in {404,410}:
                        with self.store.transaction() as conn:conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE id=:id AND owner_id=:owner'),{'id':target['id'],'owner':row['owner_id']})
        elif row['channel']=='expo' and os.getenv('OPENLEARN_EXPO_PUSH_ENABLED')=='true':
            import httpx
            targets=[t for t in targets if json.loads(t['payload']).get('kind')=='expo']
            status='no_subscription' if not targets else 'ticket_accepted'
            tickets=[]
            for target in targets:
                response=httpx.post('https://exp.host/--/api/v2/push/send',json={'to':json.loads(target['payload'])['token'],'title':payload['title'],'body':payload['body'][:500],'data':{'url':payload['url']}},timeout=10,trust_env=False)
                response.raise_for_status()
                ticket=response.json().get('data',{})
                if ticket.get('id'):tickets.append({'id':ticket['id'],'subscriptionId':target['id']})
                if ticket.get('status')!='ok':status='failed'
                if ticket.get('details',{}).get('error')=='DeviceNotRegistered':
                    with self.store.transaction() as conn:conn.execute(text('UPDATE notification_subscriptions SET active=false WHERE id=:id'),{'id':target['id']})
            payload['tickets']=tickets
        elif row['channel']=='email' and os.getenv('OPENLEARN_REMINDER_EMAIL_ENABLED')=='true':
            # Recipient is provisioned server-side, never taken from routine args.
            import httpx
            prefs=ReminderService(self.store).preferences(row['owner_id'])
            recipients=json.loads(os.getenv('OPENLEARN_REMINDER_EMAIL_RECIPIENTS','{}'))
            recipient=recipients.get(row['owner_id'])
            if prefs.get('emailOptIn') and recipient and os.getenv('RESEND_API_KEY'):
                response=httpx.post('https://api.resend.com/emails',headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],'Idempotency-Key':row['id']},json={'from':os.environ['OPENLEARN_REMINDER_EMAIL_FROM'],'to':[recipient],'subject':payload['title'],'text':payload['body']+'\n'+os.environ['FORMA_WEB_ORIGIN']+payload['url']},timeout=10,trust_env=False)
                response.raise_for_status();status='provider_handoff_confirmed'
        with self.store.transaction() as conn:
            jobs.validate_lease(conn,job)
            conn.execute(text('UPDATE notification_deliveries SET status=:status,payload=:payload WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':row['owner_id'],'status':status,'payload':encoded(payload)})
            jobs.finish(conn,job,{'status':status})
