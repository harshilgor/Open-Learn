"""Explicit reviewed tariffs for a separately selected visual model."""
import json
import os
from decimal import Decimal,InvalidOperation


def approved_visual_tariff(model):
    if model != os.getenv('OPENLEARN_VISUAL_MODEL','').strip():
        raise ValueError('Visual model does not match the configured role')
    if not os.getenv('OPENLEARN_VISUAL_RATE_VERSION','').strip():
        raise ValueError('Visual tariff review version is required')
    tariffs=json.loads(os.getenv('OPENLEARN_VISUAL_MODEL_TARIFFS','{}'))
    if not isinstance(tariffs,dict):raise ValueError('Invalid visual tariff registry')
    entry=tariffs.get(model)
    if not isinstance(entry,dict) or entry.get('provider')!='openrouter':
        raise ValueError('Visual model requires an explicit reviewed OpenRouter tariff')
    names=('usd_per_million_input','usd_per_million_output','usd_per_million_cache_read')
    try:rates={name:Decimal(str(entry[name])) for name in names}
    except (InvalidOperation, KeyError, TypeError):
        raise ValueError('Invalid visual model tariff') from None
    if any(not rate.is_finite() or rate<=0 or rate>10000 for rate in rates.values()):
        raise ValueError('Invalid visual model tariff')
    if 'usd_per_million_cache_write' in entry:
        try:rates['usd_per_million_cache_write']=Decimal(str(entry['usd_per_million_cache_write']))
        except InvalidOperation:raise ValueError('Invalid visual cache write tariff') from None
        if not rates['usd_per_million_cache_write'].is_finite() or not 0<rates['usd_per_million_cache_write']<=10000:
            raise ValueError('Invalid visual cache write tariff')
    return rates
