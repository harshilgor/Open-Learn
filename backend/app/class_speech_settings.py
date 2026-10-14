"""Independent class speech configuration; credentials are never returned."""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .material_routes import material_owner
from .provider_key_routes import _read_values, _write_values, env_path, _KEY_PATTERN


class SpeechSettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    apiKey: str | None = Field(default=None, min_length=8, max_length=500)
    enabled: bool = False
    liveEnabled: bool = False
    verificationModel: str = 'universal-3-5-pro'
    streamingModel: str = 'universal-3-6-pro'
    features: dict[str,bool] | None = None


def speech_status():
    from .identity import hosted
    values = {**_read_values(env_path()), **os.environ}
    local_management = not hosted() and values.get('OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS', 'false') == 'true'
    from .class_features import status as class_features
    return {'managed': not local_management, 'configured': bool(values.get('ASSEMBLYAI_API_KEY')),'features':class_features(),
            'enabled': values.get('OPENLEARN_CLASS_VERIFICATION_ENABLED') == 'true',
            'liveEnabled': values.get('OPENLEARN_CLASS_STREAMING_ENABLED') == 'true',
            'verificationModel': values.get('OPENLEARN_CLASS_VERIFICATION_MODEL', 'universal-3-5-pro'),
            'streamingModel': values.get('OPENLEARN_CLASS_STREAMING_MODEL', 'universal-3-6-pro'),
            'restartRequired': True}


def build_class_speech_settings_router():
    router = APIRouter(prefix='/v1/class-speech-settings', tags=['class-speech'])

    def require_local():
        if speech_status()['managed']:
            raise HTTPException(403, {'code': 'managed_provider', 'message': 'Class speech credentials are managed by the service.'})

    @router.get('')
    def status(owner=Depends(material_owner)):
        return speech_status()

    @router.put('')
    def update(body: SpeechSettingsInput, owner=Depends(material_owner)):
        require_local()
        from .assemblyai_transcription import AssemblyAITranscriptionAdapter
        if body.verificationModel not in AssemblyAITranscriptionAdapter.SUPPORTED_MODELS or body.streamingModel not in {'universal-3-6-pro', 'universal-3-5-pro'}:
            raise HTTPException(422, {'code': 'unsupported_model', 'message': 'Choose a reviewed class speech model.'})
        values = {'OPENLEARN_CLASS_VERIFICATION_ENABLED': str(body.enabled).lower(), 'OPENLEARN_CLASS_STREAMING_ENABLED': str(body.liveEnabled).lower(),
                  'OPENLEARN_CLASS_VERIFICATION_MODEL': body.verificationModel, 'OPENLEARN_CLASS_STREAMING_MODEL': body.streamingModel}
        if body.features is not None:
            from .class_features import FLAGS
            if not set(body.features)<=set(FLAGS):raise HTTPException(422,{'code':'unsupported_feature','message':'Choose supported class features.'})
            values.update({FLAGS[key]:str(value).lower() for key,value in body.features.items()})
        if body.apiKey is not None:
            if not _KEY_PATTERN.fullmatch(body.apiKey.strip()):
                raise HTTPException(422, {'code': 'invalid_key', 'message': 'The key contains unsupported characters.'})
            values['ASSEMBLYAI_API_KEY'] = body.apiKey.strip()
        _write_values(values)
        return {**speech_status(), 'restartRequired': True}

    @router.delete('/key')
    def remove(owner=Depends(material_owner)):
        require_local()
        _write_values({'ASSEMBLYAI_API_KEY': None, 'OPENLEARN_CLASS_VERIFICATION_ENABLED': 'false', 'OPENLEARN_CLASS_STREAMING_ENABLED': 'false'})
        os.environ.pop('ASSEMBLYAI_API_KEY', None)
        return speech_status()

    return router
