"""Server-owned sandbox policy; credentials never enter tasks or remote env."""
import importlib.util
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxPolicy:
    enabled: bool = False
    snapshot: str = ''
    timeout_seconds: int = 60
    lifetime_seconds: int = 900
    max_output_bytes: int = 5_000_000
    max_owner_resources: int = 2
    max_owner_creations_day: int = 10
    max_global_creations_day: int = 100

    def __post_init__(self):
        if not 5 <= self.timeout_seconds <= 90: raise ValueError('Sandbox timeout must be 5–90 seconds.')
        if not 120 <= self.lifetime_seconds <= 1800: raise ValueError('Sandbox lifetime must be 120–1800 seconds.')
        if not 10000 <= self.max_output_bytes <= 5_000_000: raise ValueError('Sandbox output limit must be 10000–5000000 bytes.')
        if not 1 <= self.max_owner_resources <= 2: raise ValueError('Sandbox resource limit must be 1–2.')
        if not 1 <= self.max_owner_creations_day <= 100:raise ValueError('Invalid sandbox owner daily creation limit.')
        if not 1 <= self.max_global_creations_day <= 1000:raise ValueError('Invalid sandbox global daily creation limit.')

    @classmethod
    def configured(cls):
        return cls(enabled=os.getenv('OPENLEARN_SANDBOX_ENABLED','false').lower()=='true',
            snapshot=os.getenv('OPENLEARN_DAYTONA_SNAPSHOT',''),
            timeout_seconds=int(os.getenv('OPENLEARN_SANDBOX_TIMEOUT_SECONDS','60')),
            lifetime_seconds=int(os.getenv('OPENLEARN_SANDBOX_LIFETIME_SECONDS','900')),
            max_owner_creations_day=int(os.getenv('OPENLEARN_SANDBOX_OWNER_CREATIONS_DAY','10')),
            max_global_creations_day=int(os.getenv('OPENLEARN_SANDBOX_GLOBAL_CREATIONS_DAY','100')))


def readiness():
    policy=SandboxPolicy.configured()
    if not policy.enabled:return {'state':'disabled','reasonCode':'sandbox_disabled'}
    if not policy.snapshot:return {'state':'setup_required','reasonCode':'snapshot_required'}
    if not os.getenv('DAYTONA_API_KEY'):return {'state':'setup_required','reasonCode':'credential_required'}
    if not importlib.util.find_spec('daytona'):return {'state':'setup_required','reasonCode':'sdk_required'}
    try:
        from ..usage.policy import Policy
        usage=Policy.load()
        if usage.mode!='enforce' or not usage.paid:
            return {'state':'setup_required','reasonCode':'paid_usage_policy_required'}
    except Exception:
        return {'state':'setup_required','reasonCode':'paid_usage_policy_required'}
    # An SDK sandbox TTL alone does not bound billable CPU/RAM/disk allocation,
    # stop latency or delayed provider adjustments. Never advertise this route
    # as available until the adapter enforces those limits and settles receipts.
    return {'state':'setup_required','reasonCode':'sandbox_lifecycle_metering_unavailable'}
