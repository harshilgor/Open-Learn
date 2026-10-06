"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { observeVoice, voiceApi, VOICE_FOCUS, VOICE_REFRESH, type VoiceEvent, type VoiceFocus, type VoiceSession } from '@/lib/voice/client';
import { openWorkspaceNote, openWorkspaceQuiz, openWorkspaceFlashcards } from '@/lib/workspace-events';
import { VoiceDock } from './voice-dock';

type VoiceContext = { start: (chatId: string) => Promise<void>; active: boolean; state: string; error: string };
const Context = createContext<VoiceContext | null>(null);
export const useVoice = () => useContext(Context);

export function VoiceProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [state, setState] = useState('idle');
  const [error, setError] = useState('');
  const [muted, setMuted] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [events, setEvents] = useState<VoiceEvent[]>([]);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [device, setDevice] = useState('');
  const [setup, setSetup] = useState<string | null>(null);
  const [interim, setInterim] = useState('');
  const [manual, setManual] = useState(false);
  const room = useRef<import('livekit-client').Room | null>(null);
  const sessionRef = useRef<VoiceSession | null>(null);
  const abort = useRef<AbortController | null>(null);
  const focus = useRef<VoiceFocus>({ revision: 0 });
  const audio = useRef<HTMLAudioElement[]>([]);
  const generation = useRef(0);
  const focusUpdates = useRef<Promise<unknown>>(Promise.resolve());
  const resuming = useRef<Promise<void> | null>(null);
  const connecting = useRef(false);
  const microphoneWanted = useRef(true);

  const end = useCallback(async () => {
    generation.current++;
    const current = sessionRef.current;
    sessionRef.current = null;
    abort.current?.abort(); abort.current = null;
    audio.current.forEach(element => { element.pause(); element.remove(); }); audio.current = [];
    await room.current?.disconnect(); room.current = null;
    setSession(null); setState('idle'); setMuted(false); setManual(false); setInterim('');
    if (current) window.dispatchEvent(new CustomEvent('openlearn-voice-ended', { detail: current.chatId }));
    if (current) try { await voiceApi.end(current.id); } catch { setError('Voice stopped on this device. Server cleanup will finish when the session expires.'); }
  }, []);

  const intent = useCallback((event: VoiceEvent) => {
    const current = sessionRef.current;
    if (!current || !event.uiIntent) return;
    const { action, targetId } = event.uiIntent;
    if (action === 'open_quiz' && targetId) openWorkspaceQuiz({ sessionId: current.chatId, quizId: targetId, origin: 'ask' });
    else if (action === 'open_note' && targetId) openWorkspaceNote(targetId);
    else if (action === 'open_flashcards' && targetId) openWorkspaceFlashcards({ deckId: targetId, view: 'editor' });
    else if (action === 'open_reminders') window.dispatchEvent(new Event('openlearn-voice-reminders'));
    else if (['refresh_chat', 'refresh_quiz', 'refresh'].includes(action)) window.dispatchEvent(new CustomEvent(VOICE_REFRESH, { detail: current.chatId }));
  }, []);

  const receive = useCallback((event: VoiceEvent) => {
    setEvents(previous => [...previous, event].slice(-200));
    if (event.type === 'session.ready') {
      if (!microphoneWanted.current) { setMuted(true); setState('Muted'); }
      else void room.current?.localParticipant.setMicrophoneEnabled(true).then(() => setState('Listening')).catch(() => { setError('Allow microphone access to talk, or use text.'); void end(); });
    }
    if (event.type === 'turn.started') setState('Thinking');
    if (event.type === 'turn.completed') setState('Listening');
    if (event.type === 'speech.ready') audio.current.forEach(element => { element.volume = 1; void element.play().catch(() => undefined); });
    if (event.type === 'turn.failed') { setState('Listening'); setError(event.message || 'Buddy could not finish that request.'); }
    if (event.type === 'speech.unavailable') setError(event.message || 'Spoken output unavailable. You can continue typing.');
    if (event.type === 'session.idle_warning') setError(event.message || 'Voice will end soon unless you speak.');
    if (event.type === 'session.ended') void end();
    if (event.type === 'action.updated' && event.status === 'succeeded' && event.uiIntent) intent(event);
  }, [end, intent]);

  const reconnect = useCallback((created: VoiceSession, connection: import('livekit-client').Room) => {
    if (resuming.current) return resuming.current;
    const recovery = (async () => {
      const deadline = Date.now() + 60000;
      setState('Reconnecting'); setMuted(true);
      await connection.localParticipant.setMicrophoneEnabled(false).catch(() => undefined);
      while (sessionRef.current?.id === created.id && Date.now() < deadline) {
        try {
          const requestTimeout = new AbortController();
          const timer = setTimeout(() => requestTimeout.abort(), 5000);
          let fresh: Awaited<ReturnType<typeof voiceApi.refreshToken>>;
          try { fresh = await voiceApi.refreshToken(created.id, requestTimeout.signal); }
          finally { clearTimeout(timer); }
          await connection.connect(fresh.url, fresh.token);
          if (sessionRef.current?.id === created.id) {
            setSession(current => current?.id === created.id ? { ...current, url: fresh.url, token: fresh.token } : current);
            setState('Paused — unmute to resume'); setError('');
          } else await connection.disconnect();
          return;
        } catch {
          await connection.disconnect().catch(() => undefined);
          await new Promise(resolve => setTimeout(resolve, 2000));
        }
      }
      if (sessionRef.current?.id === created.id) {
        setError('The network connection could not be restored. Voice has ended.');
        await end();
      }
    })().finally(() => { resuming.current = null; });
    resuming.current = recovery;
    return recovery;
  }, [end]);

  const connect = useCallback(async (chatId: string, startMuted = false) => {
    if (connecting.current || sessionRef.current) return;
    connecting.current = true;
    microphoneWanted.current = !startMuted;
    setMuted(startMuted);
    setSetup(null); setError(''); setState('Connecting');
    const epoch = ++generation.current;
    try {
      const created = await voiceApi.create(chatId, focus.current);
      if (generation.current !== epoch) { await voiceApi.end(created.id); return; }
      sessionRef.current = created; setSession(created); setEvents([]);
      const { Room, RoomEvent, Track } = await import('livekit-client');
      const connection = new Room({ adaptiveStream: true, dynacast: true, audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, ...(device ? { deviceId: device } : {}) } });
      room.current = connection;
      connection.on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
        if (participant.identity === 'learner_'+created.id) return;
        const status = changed['lk.agent.state'];
        if (status === 'speaking') setState('Buddy speaking');
        else if (status === 'listening') setState('Listening');
        else if (status === 'thinking') setState('Thinking');
      });
      connection.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
        if (participant?.identity === 'learner_'+created.id) {
          setInterim(segments.filter(segment => !segment.final).map(segment => segment.text).join(' '));
          if (segments.some(segment => !segment.final)) setState('Listening to you');
        }
      });
      connection.on(RoomEvent.TrackSubscribed, track => {
        if (track.kind === Track.Kind.Audio) { const element = track.attach() as HTMLAudioElement; element.setAttribute('aria-hidden', 'true'); document.body.appendChild(element); audio.current.push(element); void element.play().catch(() => setError('Tap Resume audio to hear Buddy.')); }
      });
      connection.on(RoomEvent.Reconnecting, () => { setState('Reconnecting'); void connection.localParticipant.setMicrophoneEnabled(false); setMuted(true); });
      connection.on(RoomEvent.Reconnected, () => setState('Paused — unmute to resume'));
      connection.on(RoomEvent.Disconnected, () => { if (sessionRef.current?.id === created.id) void reconnect(created, connection); });
      await connection.connect(created.url, created.token);
      if (generation.current !== epoch) { await connection.disconnect(); return; }
      await connection.startAudio();
      setState('Connecting to Buddy');
      const controller = new AbortController(); abort.current = controller;
      void observeVoice(created.id, controller.signal, receive).catch(cause => { setError(cause instanceof Error ? cause.message : 'Voice connection lost.'); void end(); });
      const permitted = await navigator.mediaDevices.enumerateDevices(); setDevices(permitted.filter(item => item.kind === 'audioinput'));
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Voice could not start.'); await end(); }
    finally { connecting.current = false; }
  }, [device, end, receive, reconnect]);

  const start = useCallback(async (chatId: string) => {
    if (sessionRef.current || connecting.current) return;
    try { const capability = await voiceApi.capabilities(); if (!capability.enabled) { setError(capability.message); return; } setSetup(chatId); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Voice unavailable.'); }
  }, []);

  useEffect(() => {
    const changed = () => { void end(); setEvents([]); setSetup(null); };
    const update = (event: Event) => {
      focus.current = { ...focus.current, ...(event as CustomEvent<Omit<VoiceFocus, 'revision'>>).detail, revision: focus.current.revision + 1 };
      const current = sessionRef.current;
      if (current) {
        const next = { ...focus.current };
        focusUpdates.current = focusUpdates.current.catch(() => undefined).then(() => {
          if (sessionRef.current?.id === current.id) return voiceApi.focus(current.id, next);
        }).catch(() => { if (sessionRef.current?.id === current.id) setError('Study focus changed. Please select the current item again.'); });
      }
    };
    const pause = () => { if (document.hidden && room.current) { void room.current.localParticipant.setMicrophoneEnabled(false); setMuted(true); setState('Paused — unmute to resume'); } };
    window.addEventListener(ACCOUNT_CHANGED, changed); window.addEventListener(VOICE_FOCUS, update); document.addEventListener('visibilitychange', pause);
    return () => { window.removeEventListener(ACCOUNT_CHANGED, changed); window.removeEventListener(VOICE_FOCUS, update); document.removeEventListener('visibilitychange', pause); void end(); };
  }, [end]);

  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(() => { setError('Voice session ended at its time limit.'); void end(); }, Math.max(0, session.expiresAt * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [session, end]);

  const stop = async () => {
    audio.current.forEach(element => { element.volume = 0; });
    const current = sessionRef.current;
    if (current) { await room.current?.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({ type: 'interrupt' })), { reliable: true, topic: 'openlearn-control' }); await voiceApi.interrupt(current.id); }
  };
  const mute = async () => { microphoneWanted.current = muted; await room.current?.localParticipant.setMicrophoneEnabled(muted); setMuted(!muted); setState(muted ? 'Listening' : 'Muted'); };
  const control = async (value: Record<string, unknown>) => { await room.current?.localParticipant.publishData(new TextEncoder().encode(JSON.stringify(value)), { reliable: true, topic: 'openlearn-control' }); };
  const changeMode = async () => { await control({ type: 'mode', manual: !manual }); await room.current?.localParticipant.setMicrophoneEnabled(manual); setManual(!manual); setMuted(!manual); };
  const hold = async (speaking: boolean) => { await room.current?.localParticipant.setMicrophoneEnabled(speaking); setMuted(!speaking); if (!speaking) await control({ type: 'done' }); };
  const changeDevice = async (id: string) => { setDevice(id); if (room.current) { try { await room.current.switchActiveDevice('audioinput', id || 'default'); } catch { await room.current.localParticipant.setMicrophoneEnabled(false); setMuted(true); setError('Microphone could not change. Choose an available device.'); } } };

  return <Context.Provider value={{ start, active: Boolean(session), state, error }}>{children}
    <VoiceDock session={session} state={state} error={error} muted={muted} manual={manual} onMode={() => void changeMode().catch(() => setError('Could not change microphone mode.'))} onHold={speaking => void hold(speaking).catch(() => setError('Microphone unavailable.'))} onDone={() => void control({ type: 'done' })} captions={captions} interim={interim} events={events} setup={Boolean(setup)} devices={devices} device={device} onDevice={id => void changeDevice(id)} onStart={() => setup && void connect(setup)} onStartText={() => setup && void connect(setup, true)} onDismiss={() => { setSetup(null); setError(''); }} onEnd={() => void end()} onMute={() => void mute().catch(() => setError('Microphone unavailable.'))} onStop={() => void stop().catch(() => setError('Speech stopped locally.'))} onCaptions={() => setCaptions(!captions)} onOpen={intent} onResume={() => { audio.current.forEach(element => { element.volume = 1; void element.play(); }); }} />
  </Context.Provider>;
}
