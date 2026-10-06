"""Shared Journey compilation/commit with bounded streaming and visual planning."""
import asyncio
import logging
import time
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
        started = time.monotonic()
        options = {'prefer_fast_response': True} if getattr(provider, 'supports_fast_voice_stream', False) else {}
        try:
            async for value in provider.stream_text(provider_input, max_tokens=2400, **options):
                if not chunks:
                    logging.getLogger(__name__).info('Voice lesson first text after %.1fs', time.monotonic()-started)
                size += len(value)
                if size > 20000:
                    fail('voice_output_limit', 'Please ask for a shorter explanation.', 422)
                chunks.append(value)
        finally:
            # Counts and timing only: never record prompts, transcripts or provider payloads.
            logging.getLogger(__name__).info('Voice lesson stream ended after %.1fs; characters=%d', time.monotonic()-started, size)
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
