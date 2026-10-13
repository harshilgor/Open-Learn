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
        if os.getenv('OPENLEARN_PROVIDER_PREFIX_CACHE_ENABLED') == 'true':
            rates['usd_per_million_cache_write'] = Decimal(os.environ['OPENLEARN_HAIKU55_CACHE_WRITE_USD_PER_MILLION'])
        if any(not rate.is_finite() or rate<=0 for rate in rates.values()):raise ValueError()
        return rates
    except Exception:
        raise UsageError('usage_provider_unavailable','Haiku 5.5 has no verified provider rate configured.',503) from None


def _liability_nano(input_tokens, output_tokens, input_rate, output_rate):
    raw=(Decimal(input_tokens)*input_rate+Decimal(output_tokens)*output_rate)*1000
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


def has_multimodal_input(payload):
    """Inspect content blocks, not words inside text/tool results or schemas."""
    media_types={'input_image','image_url','image','input_audio','audio','video','video_url','file','input_file'}
    def block(value):
        if not isinstance(value,dict):return False
        if value.get('type') in media_types:return True
        return any(key in value for key in ('image_url','input_audio','image','file_data','video_url')) and value.get('type')!='text'
    for message in payload.get('messages',[]):
        content=message.get('content') if isinstance(message,dict) else None
        if isinstance(content,list) and any(block(value) for value in content):return True
    inputs=payload.get('input',[])
    if isinstance(inputs,list):
        for value in inputs:
            if block(value):return True
            if isinstance(value,dict) and isinstance(value.get('content'),list) and any(block(item) for item in value['content']):return True
    return False


def visual_input_limit():
    """Serialized input bound for the visual producer (repairs and edits carry
    prior artifact source). Reservations still assume four tokens per byte."""
    try:
        value=int(os.getenv('OPENLEARN_VISUAL_MAX_INPUT_BYTES','160000'))
    except ValueError:
        value=160000
    return max(48000,min(256000,value))


def bounded_image_payload(payload, per_image_tokens, maximum_images=2):
    """Serialized size of a payload whose only media are inline data-URL images,
    with each image counted at an explicit token bound instead of base64 bytes."""
    images=0
    def strip(value):
        nonlocal images
        if isinstance(value,dict):
            if value.get('type')=='image_url':
                url=(value.get('image_url') or {}).get('url','')
                if not isinstance(url,str) or not url.startswith('data:image/'):
                    raise UsageError('usage_provider_unavailable','Only inline images have a bounded tariff.',503)
                images+=1
                return {'type':'image_url','image_url':{'url':'bounded-image'}}
            if any(key in value for key in ('input_audio','file_data','video_url')) or value.get('type') in {'input_audio','audio','video','video_url','file','input_file'}:
                raise UsageError('usage_provider_unavailable','Only inline images have a bounded tariff.',503)
            return {key:strip(item) for key,item in value.items()}
        if isinstance(value,list):return [strip(item) for item in value]
        return value
    stripped=strip({k:v for k,v in payload.items() if k not in {'model','stream','stream_options'}})
    if images>maximum_images:raise UsageError('usage_input_limit','Too many images for one request.',422)
    return len(json.dumps(stripped,ensure_ascii=False).encode('utf-8'))+images*per_image_tokens


def begin_model(payload, store=None, *, assessment_profile=None, visual_profile=False, visual_role='producer', image_token_bound=None):
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
    assessment_rates = None
    visual_rates = None
    if visual_profile and not free_model:
        try:
            from ..visual_pricing import approved_visual_tariff
            visual_rates=approved_visual_tariff(model, visual_role)
        except (ValueError,KeyError,TypeError):
            raise UsageError('usage_provider_unavailable','Visual model has no reviewed pinned tariff.',503) from None
    if assessment_profile:
        try:
            from ..assessment_profiles import approved_tariff
            assessment_rates = approved_tariff(model, assessment_profile)
        except (ValueError, KeyError, TypeError):
            raise UsageError('usage_provider_unavailable','Assessment model has no approved pinned tariff.',503) from None
    # The reviewed Haiku tariff covers the configured chat model and the
    # configured learner-memory extraction model (owner decision 2026-10-12).
    memory_model=os.getenv('OPENLEARN_MEMORY_EXTRACTION_MODEL','').strip()
    haiku_route=model=='anthropic/claude-haiku-5.5' and model in {configured_model,memory_model}
    if not free_model and (not policy.paid or (assessment_rates is None and visual_rates is None and not haiku_route)):
        raise UsageError('usage_provider_unavailable','This model has no approved usage tariff.',503)
    maximum=payload.get('max_output_tokens',payload.get('max_tokens',2000))
    if not isinstance(maximum,int) or maximum<1 or maximum>16000:raise UsageError('usage_input_limit','The response limit is unsupported.',422)
    # UTF-8 bytes is a conservative bound for supported text tokenizers.
    # Images/audio require an audited multimodal bound; do not estimate from base64.
    encoded=json.dumps({k:v for k,v in payload.items() if k not in {'model','stream','stream_options'}},ensure_ascii=False)
    if has_multimodal_input(payload):
        # Only the visual judge may send images, each at an explicit token bound
        # (the screenshot is cropped so the provider charge stays below it).
        if not (visual_profile and visual_role=='judge' and isinstance(image_token_bound,int) and 0<image_token_bound<=4000):
            raise UsageError('usage_provider_unavailable','Multimodal billing needs a configured bounded tariff.',503)
        tokens=bounded_image_payload(payload,image_token_bound)
    else:
        tokens=len(encoded.encode('utf-8'))
    input_limit=visual_input_limit() if visual_profile else 48000
    if tokens>input_limit:raise UsageError('usage_input_limit','Narrow this request or its supporting material.',422)
    ledger=Ledger(store or current_store.get() or storage(database_url()),policy)
    from ..execution import active_job
    job=active_job.get()
    root=current_root.get() or (job['target_id'] if job else uuid.uuid4().hex)
    liability=0
    rates=None
    if not free_model:
        configured=assessment_rates or visual_rates or haiku55_rates()
        input_rate=max(configured['usd_per_million_input'], configured.get('usd_per_million_cache_write',configured['usd_per_million_input']))
        output_rate=configured['usd_per_million_output']
        # Reserve at four times the serialized byte count to cover tokenizer
        # expansion, plus the full configured output limit. The supported
        # request bound and disabled multimodal inputs keep this finite.
        # Reviewed GPT byte-level tokenizer: text token count cannot exceed
        # serialized UTF-8 bytes, plus a fixed allowance for framing tokens.
        # Keep the existing bound for all other model routes.
        sol_assessment = bool(assessment_profile and model in {'openai/gpt-6.1-sol','gpt-6.1-sol'})
        input_bound=tokens + 1024 if sol_assessment else tokens*4
        liability=_liability_nano(input_bound,maximum,input_rate,output_rate)
        rates={**{key:str(value) for key,value in configured.items()},'input_token_bound_multiplier':1 if sol_assessment else 4,
               'serialized_byte_limit':input_limit,'provider':(assessment_profile or {}).get('provider','openrouter'),'model':model}
        if sol_assessment:
            rates['input_framing_reserve']=1024
    row=ledger.reserve(principal.owner_id,uuid.uuid4().hex,'model',{'input_tokens':tokens,'output_tokens':maximum},
                       liability=liability,root=root,provider=(assessment_profile or {}).get('provider','openrouter'),model=model,provider_rates=rates)
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
                input_rate=max(Decimal(rates.get('usd_per_million_input','0')),
                    Decimal(rates.get('usd_per_million_cache_write', rates.get('usd_per_million_input','0'))))
                output_rate=Decimal(rates.get('usd_per_million_output','0'))
                liability=_liability_nano(prompt,output,input_rate,output_rate)
            else:
                liability=0
            ledger.settle(owner,row['id'],{'input_tokens':prompt,'output_tokens':output,'cached_tokens':cached if isinstance(cached,int) else 0},cost=liability,
                          provider=row.get('provider','openrouter'),model=raw.get('model') if isinstance(raw.get('model'),str) else row['model'],receipt_id=raw.get('id') if isinstance(raw.get('id'),str) else None)
            return
    # Missing terminal receipt / cancelled stream retains conservative metering.
    ledger.settle(owner,row['id'],cost=row.get('liability_nano',0),source='estimated')
