"""Room-scoped grants and bounded LiveKit control requests."""
import os
import time
import json
import jwt
import httpx
from ..identity import fail


def configured():
    model=os.getenv('OPENROUTER_MODEL', 'openrouter/free')
    model_ready=model=='openrouter/free' or model.endswith(':free') or (model=='anthropic/claude-haiku-5.5' and os.getenv('OPENLEARN_USAGE_PAID_ROUTES_ENABLED')=='true')
    return model_ready and all(os.getenv(k) for k in ('LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET', 'DEEPGRAM_API_KEY', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID', 'OPENROUTER_API_KEY'))


def control_configured():
    # Cleanup remains available after an inference or speech key is revoked.
    return all(os.getenv(k) for k in ('LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'))


def token(room, identity, *, admin=False, ttl=300):
    grants = {'room': room, 'roomJoin': not admin, 'canPublish': True, 'canSubscribe': True, 'canPublishData': True}
    if admin:
        grants = {'roomCreate': True, 'roomAdmin': True, 'room': room}
    now = int(time.time())
    return jwt.encode({'iss': os.environ['LIVEKIT_API_KEY'], 'sub': identity, 'iat': now, 'nbf': now-5, 'exp': now+ttl, 'video': grants}, os.environ['LIVEKIT_API_SECRET'], algorithm='HS256')


async def rpc(service, method, room, payload):
    origin = os.environ['LIVEKIT_URL'].replace('wss://', 'https://').replace('ws://', 'http://').rstrip('/')
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f'{origin}/twirp/livekit.{service}/{method}', headers={'Authorization': 'Bearer '+token(room, 'openlearn-api', admin=True)}, json=payload)
    if response.is_error:
        if service == 'RoomService' and method == 'DeleteRoom' and response.status_code == 404:
            try:
                if response.json().get('code') == 'not_found':
                    return {}
            except ValueError:
                pass
        fail('voice_media_unavailable', 'Voice could not connect. You can continue typing.', 503)
    return response.json()


async def dispatch(sid, capability, expires_at):
    return await rpc('RoomService', 'CreateRoom', sid, {
        'name': sid,
        'empty_timeout': 60,
        'departure_timeout': 90,
        'max_participants': 2,
        'agents': [{'agent_name': configured_agent_name(), 'metadata': json.dumps({'sessionId': sid, 'capability': capability, 'expiresAt': expires_at})}],
    })


def configured_agent_name():
    return os.getenv('OPENLEARN_VOICE_AGENT_NAME', 'openlearn-voice')


async def close(sid):
    return await rpc('RoomService', 'DeleteRoom', sid, {'room': sid})
