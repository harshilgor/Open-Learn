from dataclasses import dataclass
from decimal import Decimal
import os


@dataclass(frozen=True)
class Policy:
    mode: str = 'enforce'
    grant: int = 100_000_000
    seconds: int = 18_000
    version: str = 'free-v1'
    rates: str = 'reference-v1'
    daily: int = 10_000_000_000
    monthly: int = 100_000_000_000
    paid: bool = False
    provider_rate_version: str = ''

    @classmethod
    def load(cls):
        production = os.getenv('AI_TUTOR_ENV', '').lower() in {'production', 'deployed'}
        mode = os.getenv('OPENLEARN_USAGE_MODE', 'enforce')
        paid = os.getenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED', 'false') == 'true'
        # Shadow accounting is intentionally rejected until non-blocking ledger
        # writes have a separate schema. Treating it as enforce would silently
        # block requests during a supposedly observational rollout.
        if mode not in {'off', 'enforce'} or (production and mode != 'enforce'):
            raise RuntimeError('Hosted usage must enforce account allowances.')
        if production and paid and not all(os.getenv(k) for k in ('OPENLEARN_PLATFORM_DAILY_BUDGET_USD', 'OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD')):
            raise RuntimeError('Paid routing requires explicit platform budgets.')
        provider_rate_version=os.getenv('OPENLEARN_PROVIDER_RATE_VERSION','').strip()
        value = cls(mode, int(os.getenv('OPENLEARN_FREE_CREDITS_MICRO', '100000000')),
                    int(os.getenv('OPENLEARN_USAGE_WINDOW_SECONDS', '18000')),
                    os.getenv('OPENLEARN_USAGE_POLICY_VERSION', 'free-v1'),
                    os.getenv('OPENLEARN_USAGE_RATE_VERSION', 'reference-v1'),
                    int(Decimal(os.getenv('OPENLEARN_PLATFORM_DAILY_BUDGET_USD', '10')) * 10**9),
                    int(Decimal(os.getenv('OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD', '100')) * 10**9), paid,
                    provider_rate_version)
        if min(value.grant, value.seconds, value.daily, value.monthly) <= 0:
            raise RuntimeError('Usage limits must be positive.')
        if value.rates != 'reference-v1':
            raise RuntimeError('Unsupported usage rate card.')
        if paid:
            if not value.provider_rate_version or len(value.provider_rate_version)>80:
                raise RuntimeError('Paid routing requires a pinned OPENLEARN_PROVIDER_RATE_VERSION.')
            # Daytona's API currently gives this application a TTL but not a
            # provider-enforced CPU/RAM/disk ceiling or terminal cost receipt.
            # Do not let presence of manually typed rates imply a safe bound.
            if os.getenv('OPENLEARN_SANDBOX_ENABLED')=='true':
                raise RuntimeError('Daytona cannot be enabled until allocation limits and delayed resource billing are metered.')
            enabled=[]
            if os.getenv('OPENLEARN_DICTATION_ENABLED')=='true':
                enabled.append('OPENLEARN_DICTATION_USD_PER_MINUTE')
            if os.getenv('OPENLEARN_VOICE_ENABLED')=='true':
                enabled.extend(('OPENLEARN_DEEPGRAM_USD_PER_MINUTE','OPENLEARN_ELEVENLABS_USD_PER_1000_CHARACTERS','OPENLEARN_LIVEKIT_AGENT_USD_PER_MINUTE'))
            if os.getenv('OPENLEARN_CLOUD_BROWSER_ENABLED')=='true':
                enabled.append('OPENLEARN_BROWSERBASE_USD_PER_MINUTE')
            if os.getenv('OPENLEARN_SANDBOX_ENABLED')=='true':
                enabled.extend(('OPENLEARN_DAYTONA_USD_PER_CPU_MINUTE','OPENLEARN_DAYTONA_USD_PER_MEMORY_GIB_MINUTE','OPENLEARN_DAYTONA_USD_PER_DISK_GIB_HOUR'))
            for name in enabled:
                try:
                    if Decimal(os.getenv(name,''))<=0:raise ValueError()
                except Exception:
                    raise RuntimeError(f'Paid usage route requires an explicit positive tariff: {name}.') from None
            optional_rates=[]
            if os.getenv('AI_TUTOR_MODE_CLASSIFICATION','rules').lower()=='jev':
                optional_rates.append('OPENLEARN_JEV_USD_PER_REQUEST')
            if os.getenv('AI_TUTOR_WEB_EVIDENCE','false').strip().lower() in {'1','true','yes','on'}:
                optional_rates.extend(('OPENLEARN_EXA_USD_PER_SEARCH','OPENLEARN_EXA_USD_PER_CONTENT_PAGE'))
            if os.getenv('AI_TUTOR_EMBEDDING_MODEL','').strip().lower() not in {'','off','disabled','none'}:
                optional_rates.append('OPENLEARN_EMBEDDING_USD_PER_MILLION_TOKENS')
            for name in optional_rates:
                try:
                    if Decimal(os.getenv(name,''))<=0:raise ValueError()
                except Exception:
                    raise RuntimeError(f'Enabled paid provider route requires an explicit positive tariff: {name}.') from None
        return value
