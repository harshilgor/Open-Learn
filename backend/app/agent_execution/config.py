import os


def admission_enabled():
    return os.getenv('OPENLEARN_AGENT_ADMISSION_ENABLED', 'false').lower() == 'true'


def responsibility_enabled(owner=None):
    """Independent responsibility rollout gate, optionally constrained by owner ids."""
    if os.getenv('OPENLEARN_RESPONSIBILITY_ENABLED', 'false').lower() != 'true':
        return False
    raw = os.getenv('OPENLEARN_RESPONSIBILITY_OWNER_ALLOWLIST', '').strip()
    if not raw:
        return True
    owners = {item.strip() for item in raw.split(',') if item.strip()}
    return owner in owners if owner is not None else bool(owners)


def worker_mode():
    mode = os.getenv('OPENLEARN_WORKER_MODE', 'external' if os.getenv('AI_TUTOR_ENV', 'development').lower() in {'production', 'deployed'} else 'embedded')
    if mode not in {'embedded', 'external'}: raise ValueError('Invalid OPENLEARN_WORKER_MODE')
    return mode


def capabilities(store=None):
    from .sandbox_config import readiness
    sandbox=readiness()
    external_state='setup_required'
    if store is not None:
        from ..web_evidence.service import build_web_evidence_service
        service=build_web_evidence_service(store)
        try:
            if service.config.enabled and bool(getattr(service.provider,'available',False)) and not service.config.kill_global: external_state='available'
            if os.getenv('AI_TUTOR_ENV','development').lower() in {'production','deployed'} and service.config.provider_name=='fake':external_state='setup_required'
        finally:
            close=getattr(service.provider,'close',None)
            if close:close()
    responsibility_rollout = responsibility_enabled()
    return {'schemaVersion': 2, 'admissionEnabled': admission_enabled(),
        'responsibilityEnabled': responsibility_rollout,
        'responsibilityRolloutScope': 'owner_allowlist' if os.getenv('OPENLEARN_RESPONSIBILITY_OWNER_ALLOWLIST', '').strip() else 'all', 'capabilities': [
        {'name': 'lab_analysis', 'state': 'available' if admission_enabled() else 'disabled', 'runtime': 'deterministic', 'paidCalls': False},
        {'name': 'sandbox_lab', **sandbox, 'runtime':sandbox.get('runtime','daytona'),'paidCalls':sandbox.get('runtime')!='offline_sandbox_fixture'},
        {'name':'flashcards','state':'available' if admission_enabled() else 'disabled','runtime':'bounded_source_generation'},
        {'name':'responsibilities','state':'available' if admission_enabled() and responsibility_rollout else 'disabled','runtime':'scheduled_and_event_triggers'},
        {'name': 'research', 'state': 'available' if admission_enabled() else 'disabled', 'runtime':'bounded_evidence', 'externalState':external_state},
    ]}
