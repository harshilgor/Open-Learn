"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { Bookmark, Captions, CaptionsOff, Pause, Play, Square, X } from 'lucide-react';
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
  // Set while the phone has taken the microphone away (screen locked, app switched).
  const [interrupted, setInterrupted] = useState(false);
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
      const [track] = media.getAudioTracks?.() || [];
      if (track) {
        track.onmute = () => setInterrupted(true);
        track.onunmute = () => setInterrupted(false);
        track.onended = () => { setError('The microphone was turned off, so the recording ended. What was captured is being turned into notes.'); stop(true); };
      }
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
        release(); clock.current = { startedAt: 0, pausedAt: 0, pausedFor: 0 }; setPhase('idle'); setElapsed(0); setInterrupted(false);
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

  // Keep the screen awake while recording; phones cut the microphone when they lock.
  const [screenKeptOn, setScreenKeptOn] = useState(false);
  const running = phase !== 'idle';
  useEffect(() => {
    if (!running) return;
    const wake = (navigator as Navigator & { wakeLock?: { request: (type: 'screen') => Promise<{ release: () => Promise<void>; addEventListener: (type: 'release', listener: () => void) => void }> } }).wakeLock;
    if (!wake) return;
    let lock: { release: () => Promise<void> } | null = null, live = true;
    const acquire = () => {
      if (document.visibilityState !== 'visible') return;
      void wake.request('screen').then(sentinel => {
        if (!live) { void sentinel.release(); return; }
        lock = sentinel; setScreenKeptOn(true);
        sentinel.addEventListener('release', () => { if (live) setScreenKeptOn(false); });
      }).catch(() => setScreenKeptOn(false));
    };
    acquire();
    document.addEventListener('visibilitychange', acquire);
    return () => { live = false; document.removeEventListener('visibilitychange', acquire); void lock?.release().catch(() => undefined); setScreenKeptOn(false); };
  }, [running]);

  // Leaving the page mid-recording would lose the audio.
  useEffect(() => {
    if (phase === 'idle') return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [phase]);
  useEffect(() => () => { discard.current = true; recorder.current?.stop(); stream.current?.getTracks().forEach(track => track.stop()); }, []);

  return { phase, active: phase !== 'idle', elapsed, level, markers, error, interrupted, screenKeptOn, clearError: () => setError(''), start, pause, resume, mark, stop };
}

const AUDIO_TYPES: Record<string, string> = { m4a: 'audio/mp4', mp4: 'audio/mp4', aac: 'audio/aac', mp3: 'audio/mpeg', mpga: 'audio/mpeg', wav: 'audio/wav', webm: 'audio/webm', ogg: 'audio/ogg', oga: 'audio/ogg', opus: 'audio/ogg', flac: 'audio/flac' };
export const MAX_UPLOAD_BYTES = 24 * 1024 * 1024;

/**
 * Turn a picked audio file into a recording: a type the server accepts and its
 * length. Voice Memos and similar apps often label files audio/x-m4a or leave
 * the type blank, so the extension decides.
 */
export async function recordingFromFile(file: File): Promise<NoteRecording> {
  if (file.size > MAX_UPLOAD_BYTES) throw new Error('This file is larger than 24 MB. Trim it or export it at a lower quality, then try again.');
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  const type = AUDIO_TYPES[extension] || (/^audio\/(?:x-)?m4a$/.test(file.type) ? 'audio/mp4' : file.type);
  if (!type.startsWith('audio/') && type !== 'video/mp4') throw new Error('Choose an audio file, such as M4A, MP3, WAV or WebM.');
  const blob = new Blob([file], { type: type === 'video/mp4' ? 'audio/mp4' : type });
  const durationMs = await new Promise<number>(resolve => {
    const url = URL.createObjectURL(blob), audio = new Audio();
    const done = (value: number) => { URL.revokeObjectURL(url); resolve(Number.isFinite(value) && value > 0 ? Math.round(value * 1000) : 0); };
    const timer = window.setTimeout(() => done(0), 4000);
    audio.preload = 'metadata';
    audio.onloadedmetadata = () => { window.clearTimeout(timer); done(audio.duration); };
    audio.onerror = () => { window.clearTimeout(timer); done(0); };
    audio.src = url;
  });
  return { blob, durationMs, markersMs: [] };
}

export const formatElapsed = (ms: number) => {
  const total = Math.floor(ms / 1000), hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), seconds = total % 60;
  return `${hours ? `${hours}:${String(minutes).padStart(2, '0')}` : minutes}:${String(seconds).padStart(2, '0')}`;
};

type SpeechResultList = { length: number; [index: number]: { isFinal: boolean; 0: { transcript: string } } };
type SpeechRecognizer = { continuous: boolean; interimResults: boolean; lang: string; start: () => void; stop: () => void; abort: () => void;
  onresult: ((event: { resultIndex: number; results: SpeechResultList }) => void) | null; onerror: ((event: { error: string }) => void) | null; onend: (() => void) | null };
const LIVE_WORDS_KEY = 'openlearn-live-words-v1';

export function liveWordsSupported(): boolean {
  if (typeof window === 'undefined') return false;
  const scope = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
  return Boolean(scope.SpeechRecognition || scope.webkitSpeechRecognition);
}
function readLiveWordsChoice(): 'on' | 'off' | null {
  try { const value = localStorage.getItem(LIVE_WORDS_KEY); return value === 'on' || value === 'off' ? value : null; } catch { return null; }
}

/**
 * Words appearing as you speak, from the browser's own speech recognition.
 * They are a preview only: the note's transcript comes from the full recording.
 */
export function useLiveWords(listening: boolean) {
  const [text, setText] = useState(''), [interim, setInterim] = useState(''), [problem, setProblem] = useState('');
  useEffect(() => {
    if (!listening || !liveWordsSupported()) return;
    const scope = window as unknown as { SpeechRecognition?: new () => SpeechRecognizer; webkitSpeechRecognition?: new () => SpeechRecognizer };
    const Recognizer = (scope.SpeechRecognition || scope.webkitSpeechRecognition)!;
    let live = true, recognizer: SpeechRecognizer | null = null;
    const begin = () => {
      if (!live) return;
      recognizer = new Recognizer();
      recognizer.continuous = true; recognizer.interimResults = true; recognizer.lang = navigator.language || 'en-US';
      recognizer.onresult = event => {
        let finals = '', pending = '';
        for (let index = event.resultIndex; index < event.results.length; index++) {
          const result = event.results[index];
          if (result.isFinal) finals += result[0].transcript; else pending += result[0].transcript;
        }
        if (finals) setText(current => `${current} ${finals.trim()}`.trim().slice(-4000));
        setInterim(pending.trim());
      };
      recognizer.onerror = event => {
        if (event.error === 'no-speech' || event.error === 'aborted') return;
        live = false;
        setProblem(event.error === 'not-allowed' || event.error === 'service-not-allowed' ? 'Live words were blocked by the browser.' : 'Live words are not available while recording on this device. Your recording continues.');
      };
      // Browsers end recognition after a pause; keep listening while recording.
      recognizer.onend = () => { if (live) window.setTimeout(begin, 250); };
      try { recognizer.start(); } catch { /* Already started; the next end restarts it. */ }
    };
    begin();
    return () => { live = false; recognizer?.abort(); setInterim(''); };
  }, [listening]);
  return { text, interim, problem, reset: () => { setText(''); setInterim(''); setProblem(''); } };
}

/** The learner's live-words choice: asked once, remembered on this device. */
function useLiveWordsChoice() {
  const [choice, setChoice] = useState<'on' | 'off' | null>(() => readLiveWordsChoice());
  const decide = (value: 'on' | 'off') => { setChoice(value); try { localStorage.setItem(LIVE_WORDS_KEY, value); } catch { /* Choice holds for this visit. */ } };
  return { choice, decide };
}

/** The live recording strip shown at the top of a note while it records. */
export function NoteRecordingBar({ recorder }: { recorder: ReturnType<typeof useNoteRecorder> }) {
  const paused = recorder.phase === 'paused';
  const liveSupported = liveWordsSupported();
  const live = useLiveWordsChoice();
  const words = useLiveWords(liveSupported && recorder.phase === 'recording' && live.choice === 'on');
  return <div className={styles.bar} role="region" aria-label="Recording controls">
    <span className={styles.dot} data-paused={paused || undefined} aria-hidden="true"/>
    <span className={styles.time} aria-live="off">{recorder.phase === 'starting' ? 'Starting…' : formatElapsed(recorder.elapsed)}</span>
    <span className={styles.meter} aria-hidden="true"><span style={{ transform: `scaleX(${paused ? 0 : Math.max(0.04, recorder.level)})` }}/></span>
    <span className={styles.label}>{paused ? 'Paused' : 'Recording'}{recorder.markers.length ? ` · ${recorder.markers.length} marked` : ''}{recorder.screenKeptOn ? ' · Screen stays on' : ''}</span>
    <span className={styles.actions}>
      {liveSupported && live.choice !== null ? <Button type="button" size="icon-sm" variant="ghost" aria-pressed={live.choice === 'on'} aria-label={live.choice === 'on' ? 'Hide live words' : 'Show live words'} title={live.choice === 'on' ? 'Hide live words' : 'Show live words'} onClick={() => live.decide(live.choice === 'on' ? 'off' : 'on')}>{live.choice === 'on' ? <Captions size={15}/> : <CaptionsOff size={15}/>}</Button> : null}
      <Button type="button" size="icon-sm" variant="ghost" aria-label="Mark this moment" title="Mark this moment" disabled={recorder.phase === 'starting'} onClick={recorder.mark}><Bookmark size={15}/></Button>
      {paused
        ? <Button type="button" size="icon-sm" variant="ghost" aria-label="Resume recording" title="Resume" onClick={recorder.resume}><Play size={15}/></Button>
        : <Button type="button" size="icon-sm" variant="ghost" aria-label="Pause recording" title="Pause" disabled={recorder.phase === 'starting'} onClick={recorder.pause}><Pause size={15}/></Button>}
      <Button type="button" size="sm" className={styles.stop} disabled={recorder.phase === 'starting'} onClick={() => recorder.stop(true)}><Square size={13}/>Stop &amp; make notes</Button>
      <Button type="button" size="icon-sm" variant="ghost" aria-label="Discard recording" title="Discard recording" onClick={() => { if (window.confirm('Discard this recording? The audio will not be saved.')) recorder.stop(false); }}><X size={15}/></Button>
    </span>
    {liveSupported && live.choice === null ? <div className={styles.liveAsk} role="group" aria-label="Live words">
      <span>Show your words live while you record?</span>
      <Button type="button" size="sm" variant="outline" onClick={() => live.decide('on')}>Show live words</Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => live.decide('off')}>Not now</Button>
    </div> : null}
    {liveSupported && live.choice === 'on' ? <div className={styles.liveWords} aria-live="polite" aria-label="Live words">
      {words.problem ? <em>{words.problem}</em> : words.text || words.interim ? <p>{words.text.slice(-320)} <span>{words.interim}</span></p> : <em>{paused ? 'Paused.' : 'Listening… words appear here as you speak.'}</em>}
      <small>Preview only. Your notes use the full recording.</small>
    </div> : null}
    {recorder.interrupted ? <p className={styles.interrupted} role="alert">Your phone paused the microphone (screen locked or another app). Stay on this page to keep recording.</p> : null}
  </div>;
}
