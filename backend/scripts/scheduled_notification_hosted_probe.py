"""Explicit, zero-provider-cost probe of the live notification worker.

Creates only uniquely owned synthetic fixtures. Does not call tick/claim/execute:
the deployed worker must dispatch and publish the result while no app is open.
Fixtures are retained for inspection; no real learner records are modified.
"""
import argparse
import json
import time
from uuid import uuid4
from sqlalchemy import text
from backend.app.database import database_url
from backend.app.storage import Store
from backend.app.identity import Principal, principal_context
from backend.app.models import TopicScope, utc_now
from backend.app.session_models import LearningSession
from backend.app.graph_generator import GraphGenerator
from backend.app.reminder_service import ReminderService, ReminderCreate
from backend.app.workflow_store import WorkflowStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-hosted-probe',action='store_true',required=True)
    parser.parse_args()
    suffix=uuid4().hex
    owner='scheduled_probe_'+suffix
    session_id='scheduled_probe_session_'+suffix
    store=Store(database_url())
    token=principal_context.set(Principal(owner,'local'))
    try:
        scope=TopicScope(id='scheduled_probe_scope_'+suffix,topic='Synthetic notification qualification',
            resolved_meaning='Synthetic worker test',objective='Verify durable scheduled delivery',
            depth='introductory',created_at=utc_now())
        store.save_scope(scope)
        graph=GraphGenerator().generate(scope);store.save_graph(graph)
        store.save_session(LearningSession(id=session_id,learner_id=owner,graph_id=graph.id,
            created_at=utc_now(),updated_at=utc_now()))
        fire=ReminderService(store).create(owner,ReminderCreate(when='in 1 minute',
            message='Synthetic scheduled worker qualification',sessionId=session_id,
            channels=['inbox'],quietStart=0,quietEnd=0,
            actions=[{'type':'buddy_message','bodyTemplate':'Synthetic worker result ready.'}]),suffix)
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            with store.engine.connect() as conn:
                row=conn.execute(text('SELECT status FROM reminders WHERE id=:id AND owner_id=:owner'),
                    {'id':fire['id'],'owner':owner}).mappings().one()
                inbox_rows=conn.execute(text("SELECT created_at FROM notification_deliveries WHERE owner_id=:owner AND reminder_id=:id AND channel='inbox'"),
                    {'owner':owner,'id':fire['id']}).scalars().all()
                inbox=len(inbox_rows)
            messages=WorkflowStore(store).listing_by_parent(owner,'reminder_message',session_id)
            if row['status']=='delivered':
                assert inbox==1 and len(messages)==1, 'Duplicate or missing durable result'
                with store.engine.connect() as conn:
                    usage=conn.execute(text('SELECT count(*) FROM usage_events WHERE owner_id=:owner'),{'owner':owner}).scalar_one()
                assert usage==0, 'The no-provider probe unexpectedly used a provider'
                print(json.dumps({'result':'passed','kind':'live_notification_worker','owner':owner,
                    'fireId':fire['id'],'sessionId':session_id,'inboxCount':inbox,'conversationResultCount':len(messages),
                    'dueToPersistedInboxSeconds':round(max(inbox_rows)-fire['dueAt'],3),
                    'dueToObservedDeliveredSeconds':round(time.time()-fire['dueAt'],3),
                    'providerUsageEvents':usage,'fixturesRetained':True},indent=2));return
            if row['status'] in {'failed','cancelled','expired'}:
                raise RuntimeError('Synthetic scheduled probe ended with '+row['status'])
            time.sleep(2)
        raise TimeoutError('Live worker did not deliver the synthetic result within 150 seconds')
    finally:
        principal_context.reset(token);store.close()

if __name__=='__main__':main()
