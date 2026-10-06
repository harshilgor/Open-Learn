from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from sqlalchemy import text
from ..identity import Principal, principal_context

current_store = ContextVar('usage_store',default=None)
current_root = ContextVar('usage_root',default=None)


@contextmanager
def usage_scope(store, owner, root):
    """Bind an authenticated owner and task to provider work in a worker."""
    st=current_store.set(store)
    rt=current_root.set(root)
    pt=principal_context.set(Principal(owner,'usage_worker'))
    try:
        yield
    finally:
        principal_context.reset(pt)
        current_root.reset(rt)
        current_store.reset(st)


def usage_job(function):
    @wraps(function)
    def wrapped(store,provider,job_id,*args,**kwargs):
        with store.engine.connect() as conn:
            row=conn.execute(text('SELECT owner_id,target_id FROM learning_jobs WHERE id=:id'),{'id':job_id}).mappings().first()
        if not row:return
        with usage_scope(store,row['owner_id'],row['target_id']):
            return function(store,provider,job_id,*args,**kwargs)
    return wrapped
