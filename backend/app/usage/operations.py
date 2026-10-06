"""Admission helpers for external, non-model provider calls."""
import os
import uuid
from .ledger import Ledger, UsageError
from .policy import Policy
from .pricing import dollars_to_nano
from .transport import storage
from .context import current_root, current_store
from ..identity import principal_context
from ..database import database_url


def configured_rate(env_name):
    """Read an operator-supplied USD rate; never guess paid provider prices."""
    value=os.getenv(env_name)
    if not value:
        raise UsageError('usage_provider_unavailable','This paid capability has no verified usage rate configured.',503)
    try:
        rate=dollars_to_nano(value)
    except Exception:
        raise UsageError('usage_provider_unavailable','This paid capability has no verified usage rate configured.',503) from None
    if rate<=0:
        raise UsageError('usage_provider_unavailable','This paid capability has no verified usage rate configured.',503)
    return rate


def rate_liability(env_name, quantity, units_per_rate):
    """Return a ceiling-rounded liability for quantity / units_per_rate."""
    if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<0 or units_per_rate<=0:
        raise ValueError('Invalid metering quantity.')
    rate=configured_rate(env_name)
    units=(quantity+units_per_rate-1)//units_per_rate
    return rate*units


def begin_external(component, quantities, liability_nano, *, key=None, root=None, seconds=240,provider=None,model=None,provider_rates=None):
    """Reserve and dispatch one bounded paid-provider attempt before its HTTP call."""
    policy=Policy.load()
    if policy.mode!='enforce' or not policy.paid:
        raise UsageError('usage_provider_unavailable','This paid provider capability is disabled until enforced usage accounting is enabled.',503)
    if not policy.provider_rate_version:
        raise UsageError('usage_provider_unavailable','This paid capability has no pinned provider rate version.',503)
    if not isinstance(provider_rates,dict) or not provider_rates:
        raise UsageError('usage_provider_unavailable','This paid capability has no immutable provider rate snapshot.',503)
    principal=principal_context.get()
    if not principal:
        if os.getenv('AI_TUTOR_ENV','development').lower() in {'production','deployed'}:
            raise UsageError('usage_accounting_unavailable','Paid provider work requires an authenticated account.',503)
        return None
    if liability_nano<=0:
        raise UsageError('usage_provider_unavailable','This paid capability has no bounded provider liability.',503)
    from ..execution import active_job
    job=active_job.get()
    task_root=root or current_root.get() or (job['target_id'] if job else uuid.uuid4().hex)
    ledger=Ledger(current_store.get() or storage(database_url()),policy)
    reservation=ledger.reserve(principal.owner_id,key or uuid.uuid4().hex,component,quantities,
                               liability=liability_nano,root=task_root,seconds=seconds,provider=provider,model=model,
                               provider_rates=provider_rates)
    ledger.dispatch(principal.owner_id,reservation['id'])
    return ledger,principal.owner_id,reservation


def finish_external(ticket, *, quantities=None, cost_nano=None, source='exact', release=False,provider=None,model=None,receipt_id=None):
    """Settle a metered provider receipt or conservatively retain its bound."""
    if ticket is None:
        return
    ledger,owner,reservation=ticket
    cost=reservation['liability_nano'] if cost_nano is None and not release else (cost_nano or 0)
    ledger.settle(owner,reservation['id'],quantities,cost=cost,
                  source='estimated' if cost_nano is None and not release else source,release=release,
                  provider=provider,model=model,receipt_id=receipt_id)
