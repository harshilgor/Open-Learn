"""Shared metering boundary for model transports, including cancellation."""
import json
import os
import uuid
from decimal import Decimal, ROUND_CEILING
from types import SimpleNamespace
from functools import lru_cache
from ..identity import principal_context
from ..database import database_url, create_database_engine
from .ledger import Ledger, UsageError
from .policy import Policy
from .pricing import dollars_to_nano


@lru_cache(maxsize=4)
def storage(url):
    return SimpleNamespace(engine=create_database_engine(url))


def haiku55_rates():
    try:
        rates={
            'usd_per_million_input':Decimal(os.environ['OPENLEARN_HAIKU55_INPUT_USD_PER_MILLION']),
            'usd_per_million_output':Decimal(os.environ['OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION']),
            'usd_per_million_cache_read':Decimal(os.environ['OPENLEARN_HAIKU55_CACHE_READ_USD_PER_MILLION']),
        }
        if any(rate<=0 for rate in rates.values()):raise ValueError()
        return rates
    except Exception:
        raise UsageError('usage_provider_unavailable','Haiku 5.5 has no verified provider rate configured.',503) from None


def _liability_nano(input_tokens, output_tokens, input_rate, output_rate):
    raw=(Decimal(input_tokens)*input_rate+Decimal(output_tokens)*output_rate)*1000
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


def begin_model(payload, store=None):
    from .context import current_store, current_root
    policy=Policy.load()
    if policy.mode=='off':return None
    principal=principal_context.get()
    if not principal:
        if os.getenv('AI_TUTOR_ENV','development') in {'production','deployed'}:
            raise UsageError('usage_accounting_unavailable','Model work requires an authenticated account.',503)
        return None
    model=str(payload.get('model',''))
    free_model = model=='openrouter/free' or model.endswith(':free')
    configured_model=os.getenv('OPENROUTER_MODEL','openrouter/free').strip()
    if not free_model and (not policy.paid or model!=configured_model or model!='anthropic/claude-haiku-5.5'):
        raise UsageError('usage_provider_unavailable','This model has no approved usage tariff.',503)
    maximum=payload.get('max_output_tokens',payload.get('max_tokens',2000))
    if not isinstance(maximum,int) or maximum<1 or maximum>16000:raise UsageError('usage_input_limit','The response limit is unsupported.',422)
    # UTF-8 bytes is a conservative bound for supported text tokenizers.
    # Images/audio require an audited multimodal bound; do not estimate from base64.
    encoded=json.dumps({k:v for k,v in payload.items() if k not in {'model','stream','stream_options'}},ensure_ascii=False)
    if any(marker in encoded for marker in ('input_image','image_url','input_audio','data:')):
        raise UsageError('usage_provider_unavailable','Multimodal billing needs a configured bounded tariff.',503)
    tokens=len(encoded.encode('utf-8'))
    if tokens>48000:raise UsageError('usage_input_limit','Narrow this request or its supporting material.',422)
    ledger=Ledger(store or current_store.get() or storage(database_url()),policy)
    from ..execution import active_job
    job=active_job.get()
    root=current_root.get() or (job['target_id'] if job else uuid.uuid4().hex)
    liability=0
    rates=None
    if not free_model:
        configured=haiku55_rates()
        input_rate=configured['usd_per_million_input']
        output_rate=configured['usd_per_million_output']
        # Reserve at four times the serialized byte count to cover tokenizer
        # expansion, plus the full configured output limit. The supported
        # request bound and disabled multimodal inputs keep this finite.
        input_bound=tokens*4
        liability=_liability_nano(input_bound,maximum,input_rate,output_rate)
        rates={**{key:str(value) for key,value in configured.items()},'input_token_bound_multiplier':4,
               'serialized_byte_limit':48000,'provider':'openrouter','model':model}
    row=ledger.reserve(principal.owner_id,uuid.uuid4().hex,'model',{'input_tokens':tokens,'output_tokens':maximum},
                       liability=liability,root=root,provider='openrouter',model=model,provider_rates=rates)
    ledger.dispatch(principal.owner_id,row['id'])
    return ledger,principal.owner_id,row


def finish_model(ticket,raw=None):
    if not ticket:return
    ledger,owner,row=ticket
    if raw and isinstance(raw,dict):
        prompt=raw.get('prompt_tokens',raw.get('input_tokens'))
        output=raw.get('completion_tokens',raw.get('output_tokens'))
        if isinstance(prompt,int) and isinstance(output,int) and prompt>=0 and output>=0:
            details=raw.get('prompt_tokens_details',raw.get('input_tokens_details',{})) or {}
            cached=details.get('cached_tokens',0)
            cost=raw.get('cost')
            if cost is not None:
                liability=dollars_to_nano(cost)
            elif row.get('liability_nano'):
                # OpenRouter usage receipts may omit cost on some routed
                # endpoints. Charge a conservative estimate at the pinned rate.
                rates=json.loads(row['payload']).get('providerRates',{})
                input_rate=Decimal(rates.get('usd_per_million_input','0'))
                output_rate=Decimal(rates.get('usd_per_million_output','0'))
                liability=_liability_nano(prompt,output,input_rate,output_rate)
            else:
                liability=0
            ledger.settle(owner,row['id'],{'input_tokens':prompt,'output_tokens':output,'cached_tokens':cached if isinstance(cached,int) else 0},cost=liability,
                          provider='openrouter',model=raw.get('model') if isinstance(raw.get('model'),str) else row['model'],receipt_id=raw.get('id') if isinstance(raw.get('id'),str) else None)
            return
    # Missing terminal receipt / cancelled stream retains conservative metering.
    ledger.settle(owner,row['id'],cost=row.get('liability_nano',0),source='estimated')
