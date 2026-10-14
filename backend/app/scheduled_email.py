"""Resend delivery retries are independent of scheduled task execution."""
import json
import os
import time
import httpx
from sqlalchemy import text
from .identity import assert_owner_active
from .workflow_store import WorkflowStore, encoded


def dispatch_email(store, job, sender=None):
    jobs=WorkflowStore(store)
    now=time.time()
    with store.transaction() as conn:
        jobs.validate_lease(conn,job)
        row=conn.execute(text('SELECT n.*,r.status AS reminder_status FROM notification_deliveries n JOIN reminders r ON r.id=n.reminder_id AND r.owner_id=n.owner_id WHERE n.id=:id AND n.owner_id=:owner'),{'id':job['target_id'],'owner':job['owner_id']}).mappings().one()
        assert_owner_active(conn,row['owner_id'])
        payload=json.loads(row['payload'])
        frozen=payload.get('emailRequest')
        if row['status'] not in {'pending','outcome_unknown'} or (row['status']=='outcome_unknown' and not frozen):
            jobs.finish(conn,job,{'status':row['status']});return
        if row['reminder_status']=='cancelled' or now-row['created_at']>86400:
            status='outcome_unknown' if frozen else 'expired'
            conn.execute(text('UPDATE notification_deliveries SET status=:status WHERE id=:id'),{'id':row['id'],'status':status})
            jobs.finish(conn,job,{'status':status});return
        from .reminder_service import ReminderService
        prefs=ReminderService(store).preferences(row['owner_id'])
        if not prefs.get('emailOptIn') or os.getenv('OPENLEARN_REMINDER_EMAIL_ENABLED')!='true' or not os.getenv('RESEND_API_KEY'):
            jobs.finish(conn,job,{'status':'unconfigured'});return
        if frozen and now-payload['emailFirstAttemptAt']>=23*3600:
            jobs.finish(conn,job,{'status':'outcome_unknown'});return
        if not frozen:
            recipient=json.loads(os.getenv('OPENLEARN_REMINDER_EMAIL_RECIPIENTS','{}')).get(row['owner_id'])
            if not recipient:
                jobs.finish(conn,job,{'status':'unconfigured'});return
            # Email only announces availability; private portal details stay in the app.
            frozen={'from':os.environ['OPENLEARN_REMINDER_EMAIL_FROM'],'to':[recipient],
                    'subject':'Your Open Learn activity is ready',
                    'text':'Open Open Learn to review your scheduled activity.\n'+os.environ['FORMA_WEB_ORIGIN']+payload['url']}
            payload.update(emailRequest=frozen,emailFirstAttemptAt=now)
        conn.execute(text("UPDATE notification_deliveries SET status='outcome_unknown',payload=:payload WHERE id=:id AND owner_id=:owner"),{'id':row['id'],'owner':row['owner_id'],'payload':encoded(payload)})
    sender=sender or httpx.post
    try:
        response=sender('https://api.resend.com/emails',headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY'],'Idempotency-Key':row['id']},json=frozen,timeout=10,trust_env=False)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code==429 or exc.response.status_code>=500:
            jobs.fail(job,'provider_transport',retryable=True);return
        with store.transaction() as conn:
            jobs.validate_lease(conn,job)
            conn.execute(text("UPDATE notification_deliveries SET status='failed' WHERE id=:id AND owner_id=:owner"),{'id':row['id'],'owner':row['owner_id']})
            jobs.finish(conn,job,{'status':'failed'})
        return
    except httpx.TransportError:
        jobs.fail(job,'provider_transport',retryable=True);return
    with store.transaction() as conn:
        jobs.validate_lease(conn,job)
        payload['emailProviderId']=response.json().get('id')
        conn.execute(text("UPDATE notification_deliveries SET status='provider_handoff_confirmed',payload=:payload WHERE id=:id AND owner_id=:owner"),{'id':row['id'],'owner':row['owner_id'],'payload':encoded(payload)})
        jobs.finish(conn,job,{'status':'provider_handoff_confirmed'})
