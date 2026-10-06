"use client";
import { useState, useEffect, useRef } from 'react';
import { AudioLines, Captions, Mic, MicOff, Square, X, ChevronDown } from 'lucide-react';
import { voiceApi, type VoiceEvent, type VoiceSession } from '@/lib/voice/client';
import styles from './voice.module.css';

type Props = {
  session: VoiceSession | null; state: string; error: string; muted: boolean; captions: boolean; interim?: string; events: VoiceEvent[]; setup: boolean;
  devices: MediaDeviceInfo[]; device: string; onDevice: (id: string) => void;
  manual?: boolean; onMode?: () => void; onHold?: (speaking: boolean) => void; onDone?: () => void;
  onStart: () => void; onDismiss: () => void; onEnd: () => void; onMute: () => void; onStop: () => void;
  onCaptions: () => void; onOpen: (event: VoiceEvent) => void; onResume: () => void;
};

function Action({ event, onOpen }: { event: VoiceEvent; onOpen: Props['onOpen'] }) {
  const [handled, setHandled] = useState(false);
  const [error, setError] = useState('');
  const confirm = async (approve: boolean) => {
    if (!event.callId || !event.argumentsHash) return;
    try { await voiceApi.confirm(event.callId, event.argumentsHash, approve); setHandled(true); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Please review the action again.'); }
  };
  return <article className={styles.action}>
    <strong>{event.tool?.replaceAll('_', ' ') || event.artifactRef?.kind || 'Study task'}</strong>
    <span>{event.userMessage || event.status?.replaceAll('_', ' ')}</span>
    {event.result?.dueAt ? <time>{new Date(Number(event.result.dueAt) * 1000).toLocaleString()}</time> : null}
    {event.status === 'awaiting_confirmation' && !handled ? <><p>{event.confirmationMessage || 'Review this action before it is saved.'}</p><button onClick={() => void confirm(true)}>Confirm</button><button onClick={() => void confirm(false)}>Cancel</button></> : null}
    {event.uiIntent ? <button onClick={() => onOpen(event)}>Open in workspace</button> : null}
    {event.status === 'queued' || event.status === 'running' ? <button onClick={() => { if (event.callId) void voiceApi.cancel(event.callId).catch(cause => setError(cause instanceof Error ? cause.message : 'Check the task status.')); }}>Cancel pending work</button> : null}
    {error ? <p role="alert">{error}</p> : null}
  </article>;
}

export function VoiceDock(props: Props) {
  const [minimized, setMinimized] = useState(false);
  const [typed, setTyped] = useState('');
  const [sendError, setSendError] = useState('');
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => { if (window.matchMedia?.('(max-width: 640px)').matches) setMinimized(true); }, []);
  useEffect(() => {
    if (!props.setup) return;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLElement>('button')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); props.onDismiss(); }
      if (event.key === 'Tab') {
        const controls = [...dialog.current!.querySelectorAll<HTMLElement>('button,select,input')].filter(item => !(item as HTMLButtonElement).disabled);
        if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
      }
    };
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); previous?.focus(); };
  }, [props.setup, props.onDismiss]);
  if (props.setup) return <div className={styles.backdrop}><section ref={dialog} className={styles.setup} role="dialog" aria-modal="true" aria-labelledby="voice-title">
    <button className={styles.close} onClick={props.onDismiss} aria-label="Close voice setup"><X size={20} /></button>
    <AudioLines size={30} /><h2 id="voice-title">Talk to Buddy</h2><p>Ask questions, create quizzes and diagrams, or set a reminder while you study.</p>
    <p>Your microphone audio is processed by our voice providers. Conversation text and action receipts are saved with your study account. Open Learn does not record the audio.</p>
    <label>Microphone<select value={props.device} onChange={event => props.onDevice(event.target.value)}><option value="">System default</option>{props.devices.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label || 'Microphone'}</option>)}</select></label>
    <button className={styles.primary} onClick={props.onStart}>Start conversation</button><button onClick={props.onDismiss}>Keep typing</button>
  </section></div>;
  if (!props.session) return props.error ? <aside className={styles.notice} role="status">{props.error}<button onClick={props.onDismiss} aria-label="Dismiss voice message"><X size={16} /></button></aside> : null;
  const latestActions = new Map<string, VoiceEvent>();
  props.events.filter(event => event.type.startsWith('action.')).forEach(event => { if (event.callId) latestActions.set(event.callId, { ...latestActions.get(event.callId), ...event }); });
  return <aside className={`${styles.dock} ${minimized ? styles.minimized : ''}`} aria-label="Voice conversation">
    <div className={styles.controls}><AudioLines size={20} /><div><strong>Buddy</strong><span role="status">{props.state}</span></div>
      <button onClick={props.onMute} aria-label={props.muted ? 'Unmute microphone' : 'Mute microphone'} aria-pressed={props.muted}>{props.muted ? <MicOff size={19} /> : <Mic size={19} />}</button>
      <button onClick={props.onStop} aria-label="Stop Buddy speaking"><Square size={17} /></button>
      <button onClick={props.onCaptions} aria-label="Show conversation transcript" aria-pressed={props.captions}><Captions size={20} /></button>
      <button onClick={() => setMinimized(!minimized)} aria-label={minimized ? 'Expand voice controls' : 'Minimize voice controls'}><ChevronDown size={18} /></button>
      <button className={styles.end} onClick={props.onEnd}>End</button>
    </div>
    {!minimized ? <>
      <label>Microphone <select aria-label="Conversation microphone" value={props.device} onChange={event => props.onDevice(event.target.value)}><option value="">System default</option>{props.devices.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label || 'Microphone'}</option>)}</select></label>
      <div className={styles.controls}><button onClick={props.onMode}>{props.manual ? 'Use hands-free' : 'Use hold-to-talk'}</button>{props.manual ? <button onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); props.onHold?.(true); }} onPointerUp={() => props.onHold?.(false)} onPointerCancel={() => props.onHold?.(false)} onKeyDown={event => { if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) { event.preventDefault(); props.onHold?.(true); } }} onKeyUp={event => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); props.onHold?.(false); } }}>Hold to talk</button> : <button onClick={props.onDone}>Done speaking</button>}</div>
      {props.error ? <p role="alert">{props.error} <button onClick={props.onResume}>Resume audio</button></p> : null}
      {props.captions ? <div className={styles.transcript} aria-label="Conversation transcript">{props.events.filter(event => ['turn.started', 'speech.ready'].includes(event.type)).map(event => <p key={event.sequence}><strong>{event.type === 'turn.started' ? 'You' : 'Buddy'}:</strong> {event.text}</p>)}{props.interim ? <p><strong>You:</strong> {props.interim}</p> : null}</div> : null}
      <div className={styles.actions}>{[...latestActions.values()].slice(-5).map(event => <Action key={event.callId} event={event} onOpen={props.onOpen} />)}</div>
      <form className={styles.typed} onSubmit={event => { event.preventDefault(); if (typed.trim() && props.session) { void voiceApi.turn(props.session.id, typed).then(() => { setTyped(''); setSendError(''); }).catch(cause => setSendError(cause instanceof Error ? cause.message : 'Could not send. Your draft is preserved.')); } }}><input aria-label="Type into voice conversation" value={typed} onChange={event => setTyped(event.target.value)} maxLength={4000} placeholder="You can type here, too…" /><button disabled={!typed.trim()}>Send</button></form>{sendError ? <p role="alert">{sendError}</p> : null}
    </> : null}
  </aside>;
}
