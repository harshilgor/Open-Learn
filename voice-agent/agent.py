"""Media-only Buddy agent. All reasoning and effects stay in Open Learn."""
import asyncio
import json
import logging
import os
import time
from uuid import uuid4
import httpx
from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import deepgram, elevenlabs, silero

log = logging.getLogger('openlearn.voice')
server = AgentServer(num_idle_processes=1, drain_timeout=1900)


class Backend:
    def __init__(self, sid, capability):
        origin = os.environ['OPENLEARN_API_URL'].rstrip('/')
        if not origin.startswith('https://') and os.getenv('OPENLEARN_VOICE_LOCAL_DEV') != 'true':
            raise ValueError('Voice agent requires an HTTPS API origin.')
        self.sid = sid
        self.client = httpx.AsyncClient(base_url=origin, headers={'Authorization': 'Bearer '+capability}, timeout=15)

    async def call(self, method, path, body=None, *, timeout=None):
        request = {'json': body}
        if timeout is not None:
            request['timeout'] = timeout
        response = await self.client.request(method, '/internal/voice/'+self.sid+path, **request)
        response.raise_for_status()
        return response.json()


class Buddy(Agent):
    def __init__(self, backend):
        super().__init__(instructions='Media adapter only. Backend owns all tutoring and actions.', llm=None)
        self.backend = backend

    async def on_user_turn_completed(self, turn_ctx, new_message):
        value = (new_message.text_content or '').strip()
        if value:
            # No retries with fresh IDs: preserve the same identity on transport retry.
            body = {'utterance_id': new_message.id or uuid4().hex, 'text': value[:4000]}
            for attempt in range(2):
                try:
                    await self.backend.call('POST', '/turns', body)
                    return
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt:
                        log.warning('Voice turn transport failed for session %s', self.backend.sid)
                        return
                    await asyncio.sleep(.3)
                except httpx.HTTPStatusError:
                    log.warning('Voice turn rejected for session %s', self.backend.sid)
                    return

    async def llm_node(self, chat_ctx, tools, model_settings):
        # Prevent an independent vendor reasoning loop or unapproved speech.
        if False:
            yield ''


@server.rtc_session(agent_name='openlearn-voice')
async def entrypoint(ctx: JobContext):
    metadata = json.loads(ctx.job.metadata)
    sid = metadata['sessionId']
    expires_at = float(metadata.get('expiresAt', 0))
    if sid != ctx.room.name:
        raise ValueError('Room/session mismatch')
    backend = Backend(sid, metadata['capability'])
    # Voice/STT are not started until Open Learn has admitted the first shared-
    # allowance interval. Session creation already holds slice zero; this call
    # safely replays that authorization and establishes its server deadline.
    try:
        first_slice = await backend.call('POST', '/slice', {'slice_index': 0})
    except Exception:
        await backend.client.aclose()
        raise
    await ctx.connect()
    voice = AgentSession(
        stt=deepgram.STTv2(model='flux-general-en', api_key=os.environ['DEEPGRAM_API_KEY'],
                          eot_threshold=.8, eot_timeout_ms=3000, mip_opt_out=True),
        vad=silero.VAD.load(),
        tts=elevenlabs.TTS(api_key=os.environ['ELEVENLABS_API_KEY'], voice_id=os.environ['ELEVENLABS_VOICE_ID'],
                          model=os.getenv('ELEVENLABS_MODEL', 'eleven_flash_v2_5'), enable_logging=False),
        turn_handling={'turn_detection': 'stt', 'preemptive_generation': {'enabled': False}, 'interruption': {'enabled': True}},
    )
    stopped = asyncio.Event()
    tasks = set()
    last_activity = time.monotonic()
    epoch = 0
    warned = False
    queue = asyncio.Queue(maxsize=30)
    disconnect_watch = None
    tts_attempt_id = uuid4().hex

    def spawn(coroutine):
        task = asyncio.create_task(coroutine); tasks.add(task); task.add_done_callback(tasks.discard)
        return task

    async def usage_slices():
        index = 1
        current = first_slice
        while not stopped.is_set():
            lead = float(current.get('renewalLeadSeconds', 5))
            await asyncio.sleep(max(0, float(current['nextAt']) - lead - time.time()))
            if stopped.is_set():
                return
            try:
                # The slice number is stable across transport retries. The API
                # rejects out-of-order reservations. Renew inside the server's
                # server-authorized overlap; all overlap is reserved and metered.
                current = await backend.call('POST', '/slice', {'slice_index': index}, timeout=max(1, lead - 2))
                index += 1
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                log.warning('Voice interval renewal stopped session %s at slice %s: %s', sid, index, status)
                # A denied interval is a hard stop: keep the agent from making
                # more STT calls while the screen preserves the typed workflow.
                # Slice admission is retried only by runtime restart with the
                # same persisted index; do not leave the microphone live during
                # a long series of billing-service retries.
                stopped.set()
                try:
                    voice.interrupt(force=True)
                except Exception:
                    pass
                return

    @ctx.room.on('data_received')
    def controls(packet: rtc.DataPacket):
        if packet.topic != 'openlearn-control' or not packet.participant or packet.participant.identity != 'learner_'+sid:
            return
        try:
            command = json.loads(packet.data)
        except (ValueError, UnicodeError):
            return
        if command.get('type') == 'interrupt':
            voice.interrupt(force=True)
        elif command.get('type') == 'done':
            voice.commit_user_turn()
        elif command.get('type') == 'mode':
            voice.update_options(turn_detection='manual' if command.get('manual') else 'stt')

    @voice.on('user_state_changed')
    def activity(event):
        nonlocal last_activity, warned
        if event.new_state == 'speaking':
            last_activity = time.monotonic()
            warned = False
            spawn(backend.call('POST', '/interrupt'))

    @ctx.room.on('participant_disconnected')
    def disconnected(participant):
        nonlocal disconnect_watch
        if participant.identity == 'learner_'+sid and not stopped.is_set():
            if disconnect_watch:
                disconnect_watch.cancel()
            async def end_if_not_rejoined():
                await asyncio.sleep(60)
                if not any(p.identity == 'learner_'+sid for p in ctx.room.remote_participants.values()):
                    stopped.set()
            disconnect_watch = spawn(end_if_not_rejoined())

    @ctx.room.on('participant_connected')
    def reconnected(participant):
        nonlocal disconnect_watch
        if participant.identity == 'learner_'+sid and disconnect_watch:
            disconnect_watch.cancel()
            disconnect_watch = None

    async def poll():
        nonlocal epoch, warned
        cursor = 0
        failures = 0
        while not stopped.is_set():
            if expires_at and time.time() >= expires_at:
                stopped.set(); break
            try:
                state = await backend.call('GET', '/poll?after='+str(cursor))
                failures = 0
                epoch = state['epoch']
                if time.monotonic()-last_activity > 120 and not warned:
                    await backend.call('POST', '/idle-warning')
                    warned = True
                if state['status'] != 'active' or state['expiresAt'] <= time.time() or time.monotonic()-last_activity > 180:
                    stopped.set(); break
                for event in state['events']:
                    cursor = max(cursor, event['sequence'])
                    if event['type'] == 'speech.interrupted':
                        voice.interrupt(force=True)
                    elif event['type'] == 'speech.ready':
                        await queue.put(event)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403, 404, 409}:
                    stopped.set(); break
                failures = min(failures + 1, 5)
            except (httpx.TimeoutException, httpx.NetworkError):
                failures = min(failures + 1, 5)
            await asyncio.sleep(min(1+failures, 5))

    async def speak():
        while not stopped.is_set():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            if event['epoch'] != epoch:
                continue
            while voice.user_state == 'speaking' and not stopped.is_set():
                await asyncio.sleep(.1)
            authorization = None
            try:
                request = {'attempt_id': tts_attempt_id, 'characters': len(event['text'])}
                for attempt in range(2):
                    try:
                        authorization = await backend.call(
                            'POST', f"/speech/{event['segmentId']}/tts-preflight", request, timeout=3.0)
                        break
                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt:
                            raise
                last_activity_before_speech = time.monotonic()
                handle = voice.say(event['text'], allow_interruptions=True)
                await handle
                await backend.call('POST', f"/speech/{event['segmentId']}/tts-complete", {'reservation_id': authorization['reservationId']})
                await backend.call('POST', '/playback', {'segment_id': event['segmentId'], 'epoch': event['epoch'], 'status': 'interrupted' if handle.interrupted else 'played'})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {429, 503}:
                    stopped.set()
                    try:
                        voice.interrupt(force=True)
                    except Exception:
                        pass
                log.warning('Speech request failed for session %s: HTTP %s', sid, exc.response.status_code)
            except Exception as exc:
                log.warning('Speech failed for session %s: %s', sid, type(exc).__name__)  # No learner text or credentials.
            finally:
                if authorization:
                    try:
                        await backend.call('POST', f"/speech/{event['segmentId']}/tts-complete", {'reservation_id': authorization['reservationId']})
                    except Exception:
                        # The durable reservation reconciler retains the full
                        # provider estimate if delivery ended ambiguously.
                        pass

    await voice.start(agent=Buddy(backend), room=ctx.room, record=False)
    log.info('Voice media ready for session %s', sid)
    spawn(poll()); spawn(speak()); spawn(usage_slices())
    try:
        await stopped.wait()
    finally:
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await voice.aclose()
        try:
            await backend.call('POST', '/end')
        except Exception:
            pass  # Backend janitor settles orphaned sessions.
        await backend.client.aclose()
        await ctx.room.disconnect()
        log.info('Voice media stopped for session %s', sid)


if __name__ == '__main__':
    cli.run_app(server)
