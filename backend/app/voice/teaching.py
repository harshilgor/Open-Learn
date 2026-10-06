"""Shared Journey compilation/commit with bounded streaming and visual planning."""
import asyncio
from ..assessment_models import JourneyCommand
from ..journey_service import JourneyService
from ..visualization_planner import plan_visualizations
from ..identity import fail


def prepare(store, provider, owner, chat_id, payload):
    command = JourneyCommand.model_validate(payload['command'])
    service = JourneyService(store, provider)
    prepared = service.prepare_stream(owner, chat_id, command)
    provider_input = prepared['generationContext'] if getattr(provider, 'supports_generation_context', False) else prepared['prompt']

    async def collect():
        chunks = []
        size = 0
        async for value in provider.stream_text(provider_input, max_tokens=2400):
            size += len(value)
            if size > 20000:
                fail('voice_output_limit', 'Please ask for a shorter explanation.', 422)
            chunks.append(value)
        return ''.join(chunks)

    body = asyncio.run(asyncio.wait_for(collect(), timeout=90))
    if not body.strip():
        fail('voice_empty_lesson', 'Buddy returned no explanation.', 503)
    visuals = plan_visualizations(provider, prepared, command.message) if payload.get('visual') else []
    if payload.get('visual') and not visuals:
        fail('voice_visual_unavailable', 'Buddy could not produce a valid diagram. Please try a more specific request.', 422)
    return service, prepared, command, body, visuals


def commit(conn, owner, prepared):
    service, context, command, body, visuals = prepared
    artifact, _ = service.commit_stream(conn, owner, context, command, body, visuals)
    return {'sessionId': artifact.session_id, 'lessonId': artifact.id}
