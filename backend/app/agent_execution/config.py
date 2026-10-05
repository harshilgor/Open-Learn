import os


def admission_enabled():
    return os.getenv('OPENLEARN_AGENT_ADMISSION_ENABLED', 'false').lower() == 'true'


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
    return {'schemaVersion': 2, 'admissionEnabled': admission_enabled(), 'capabilities': [
        {'name': 'lab_analysis', 'state': 'available' if admission_enabled() else 'disabled', 'runtime': 'deterministic', 'paidCalls': False},
        {'name': 'sandbox_lab', **sandbox, 'runtime':sandbox.get('runtime','daytona'),'paidCalls':sandbox.get('runtime')!='offline_sandbox_fixture'},
        {'name':'flashcards','state':'available' if admission_enabled() else 'disabled','runtime':'bounded_source_generation'},
        {'name': 'research', 'state': 'available' if admission_enabled() else 'disabled', 'runtime':'bounded_evidence', 'externalState':external_state},
    ]}
