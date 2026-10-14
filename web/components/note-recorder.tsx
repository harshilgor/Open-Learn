"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { Bookmark, Pause, Play, Square, X } from 'lucide-react';
import { Button } from './ui/button';
import styles from './note-recorder.module.css';

/** The server processes one file of up to 24 MB; stop well before it. */
const MAX_BYTES = 22 * 1024 * 1024;
const MAX_MS = 90 * 60 * 1000;
const BITS_PER_SECOND = 32_000;

export type NoteRecording = { blob: Blob; durationMs: number; markersMs: number[] };
type Phase = 'idle' | 'starting' | 'recording' | 'paused';

function preferredType(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported?.(type)) || '';
}

export function recordingSupported(): boolean {
  return typeof window !== 'undefined' && typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

/**
 * Records one audio file for a note: start, pause, mark moments, then stop to
 * get the file. Stops on its own before the processing size or time limit.
 */
export function useNoteRecorder(onFinished: (recording: NoteRecording) => void) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [markers, setMarkers] = useState<number[]>([]);
  const [error, setError] = useState('');
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const bytes = useRef(0);
  const clock = useRef({ startedAt: 0, pausedAt: 0, pausedFor: 0 });
  const markersRef = useRef<number[]>([]);
  const discard = useRef(false);
  const finished = useRef(onFinished);
  useEffect(() => { finished.current = onFinished; }, [onFinished]);

  const now = () => {
    const { startedAt, pausedAt, pausedFor } = clock.current;
    return startedAt ? (pausedAt || Date.now()) - startedAt - pausedFor : 0;
  };
  const release = () => { stream.current?.getTracks().forEach(track => track.stop()); stream.current = null; recorder.current = null; setLevel(0); };

  const stop = useCallback((keep = true) => {
    const active = recorder.current;
    if (!active || active.state === 'inactive') return;
    discard.current = !keep;
    active.stop();
  }, []);

  const start = useCallback(async () => {
    if (recorder.current) return;
    setError('');
    if (!recordingSupported()) { setError('Recording is not supported in this browser.'); return; }
    setPhase('starting');
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const type = preferredType();
      const next = new MediaRecorder(media, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: BITS_PER_SECOND });
      stream.current = media; recorder.current = next;
      chunks.current = []; bytes.current = 0; markersRef.current = []; setMarkers([]); discard.current = false;
      next.ondataavailable = event => {
        if (!event.data.size) return;
        chunks.current.push(event.data); bytes.current += event.data.size;
        if (bytes.current > MAX_BYTES || now() > MAX_MS) { setError('Recording stopped at the length limit. Start another recording to continue.'); stop(true); }
      };
      next.onstop = () => {
        const durationMs = now();
        const blob = new Blob(chunks.current, { type: (next.mimeType || type || 'audio/webm').split(';')[0] });
        const keep = !discard.current && blob.size > 0;
        release(); clock.current = { startedAt: 0, pausedAt: 0, pausedFor: 0 }; setPhase('idle'); setElapsed(0);
        if (keep) finished.current({ blob, durationMs, markersMs: markersRef.current });
      };
      clock.current = { startedAt: Date.now(), pausedAt: 0, pausedFor: 0 };
      next.start(1000);
      setPhase('recording');
    } catch (cause) {
      release(); setPhase('idle');
      setError(cause instanceof DOMException && cause.name === 'NotAllowedError' ? 'Allow microphone access to record into this note.' : 'The microphone could not be started.');
    }
  }, [stop]);

  const pause = useCallback(() => {
    if (recorder.current?.state !== 'recording') return;
    recorder.current.pause(); clock.current.pausedAt = Date.now(); setPhase('paused');
  }, []);
  const resume = useCallback(() => {
    if (recorder.current?.state !== 'paused') return;
    recorder.current.resume(); clock.current.pausedFor += Date.now() - clock.current.pausedAt; clock.current.pausedAt = 0; setPhase('recording');
  }, []);
  const mark = useCallback(() => {
    if (!recorder.current) return;
    markersRef.current = [...markersRef.current, Math.round(now())].slice(0, 500);
    setMarkers(markersRef.current);
  }, []);

  // Timer and a simple input level while recording.
  useEffect(() => {
    if (phase !== 'recording' && phase !== 'paused') return;
    const media = stream.current;
    let context: AudioContext | null = null, frame = 0;
    if (media && phase === 'recording' && typeof AudioContext !== 'undefined') {
      context = new AudioContext();
      const analyser = context.createAnalyser(); analyser.fftSize = 512;
      context.createMediaStreamSource(media).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const tick = () => { analyser.getByteTimeDomainData(data); let peak = 0; for (const value of data) peak = Math.max(peak, Math.abs(value - 128)); setLevel(Math.min(1, peak / 64)); frame = requestAnimationFrame(tick); };
      tick();
    }
    const timer = window.setInterval(() => setElapsed(now()), 500);
    return () => { window.clearInterval(timer); cancelAnimationFrame(frame); void context?.close(); };
  }, [phase]);

  // Leaving the page mid-recording would lose the audio.
  useEffect(() => {
    if (phase === 'idle') return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [phase]);
  useEffect(() => () => { discard.current = true; recorder.current?.stop(); stream.current?.getTracks().forEach(track => track.stop()); }, []);

  return { phase, active: phase !== 'idle', elapsed, level, markers, error, clearError: () => setError(''), start, pause, resume, mark, stop };
}

export const formatElapsed = (ms: number) => {
  const total = Math.floor(ms / 1000), hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), seconds = total % 60;
  return `${hours ? `${hours}:${String(minutes).padStart(2, '0')}` : minutes}:${String(seconds).padStart(2, '0')}`;
};

/** The live recording strip shown at the top of a note while it records. */
export function NoteRecordingBar({ recorder }: { recorder: ReturnType<typeof useNoteRecorder> }) {
  const paused = recorder.phase === 'paused';
  return <div className={styles.bar} role="region" aria-label="Recording">
    <span className={styles.dot} data-paused={paused || undefined} aria-hidden="true"/>
    <span className={styles.time} aria-live="off">{recorder.phase === 'starting' ? 'Starting…' : formatElapsed(recorder.elapsed)}</span>
    <span className={styles.meter} aria-hidden="true"><span style={{ transform: `scaleX(${paused ? 0 : Math.max(0.04, recorder.level)})` }}/></span>
    <span className={styles.label}>{paused ? 'Paused' : 'Recording'}{recorder.markers.length ? ` · ${recorder.markers.length} marked` : ''}</span>
    <span className={styles.actions}>
      <Button type="button" size="icon-sm" variant="ghost" aria-label="Mark this moment" title="Mark this moment" disabled={recorder.phase === 'starting'} onClick={recorder.mark}><Bookmark size={15}/></Button>
      {paused
        ? <Button type="button" size="icon-sm" variant="ghost" aria-label="Resume recording" title="Resume" onClick={recorder.resume}><Play size={15}/></Button>
        : <Button type="button" size="icon-sm" variant="ghost" aria-label="Pause recording" title="Pause" disabled={recorder.phase === 'starting'} onClick={recorder.pause}><Pause size={15}/></Button>}
      <Button type="button" size="sm" className={styles.stop} disabled={recorder.phase === 'starting'} onClick={() => recorder.stop(true)}><Square size={13}/>Stop &amp; make notes</Button>
      <Button type="button" size="icon-sm" variant="ghost" aria-label="Discard recording" title="Discard recording" onClick={() => { if (window.confirm('Discard this recording? The audio will not be saved.')) recorder.stop(false); }}><X size={15}/></Button>
    </span>
  </div>;
}
