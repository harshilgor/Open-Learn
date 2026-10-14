"""Content-free operational heartbeats for separate cloud worker processes."""
import os
import time
from sqlalchemy import text
from .workflow_store import encoded


def heartbeat(store, role, status='running'):
    if role not in {'browser','notifications'}:
        raise ValueError('Unknown cloud worker role')
    with store.transaction() as conn:
        conn.execute(text('INSERT INTO reminder_runtime(id,last_tick,payload) VALUES(:id,:now,:payload) ON CONFLICT(id) DO UPDATE SET last_tick=excluded.last_tick,payload=excluded.payload'),
                     {'id':'worker_'+role,'now':time.time(),'payload':encoded({'role':role,'status':status,'processId':os.getpid()})})
