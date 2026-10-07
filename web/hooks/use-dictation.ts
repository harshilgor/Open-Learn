"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { DictationTranscript } from '@/lib/dictation';

let cancelCurrentCapture: (() => void) | undefined;

type Phase = 'idle' | 'connecting' | 'listening' | 'finalizing' | 'review' | 'error';
type Session = { id: string; ticket: string; url: string; maxSeconds: number };

export function useDictation() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [text, setText] = useState(''), [interim, setInterim] = useState(''), [error, setError] = useState('');
  const [seconds, setSeconds] = useState(0), [level, setLevel] = useState(0);
  const generation = useRef(0), phaseRef = useRef<Phase>('idle');
  const media = useRef<MediaStream | null>(null), context = useRef<AudioContext | null>(null);
  const node = useRef<AudioWorkletNode | null>(null), socket = useRef<WebSocket | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null), deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completed = useRef<((text: string) => void) | undefined>(undefined);
  const session = useRef<Session | null>(null), transcript = useRef(new DictationTranscript());
  const changePhase = useCallback((next: Phase) => { phaseRef.current = next; setPhase(next); }, []);
  const stopCapture = useCallback(() => {
    media.current?.getTracks().forEach(track => track.stop()); media.current = null;
    node.current?.disconnect(); node.current = null;
    if (context.current) void context.current.close().catch(() => {}); context.current = null;
    if (timer.current) clearInterval(timer.current); timer.current = null;
  }, []);
  const dispose = useCallback(() => {
    stopCapture();
    if (deadline.current) clearTimeout(deadline.current); deadline.current = null;
    const current = socket.current; socket.current = null;
    if (current?.readyState === WebSocket.OPEN) current.send(JSON.stringify({ type: 'cancel' }));
    current?.close();
    const unused = session.current; session.current = null;
    if (unused) void request(`/v1/dictation/sessions/${encodeURIComponent(unused.id)}/cancel`, { method: 'POST' }).catch(() => {});
  }, [stopCapture]);
  const cancel = useCallback(() => {
    generation.current++; dispose(); changePhase('idle'); setText(''); setInterim(''); setError(''); setLevel(0);
  }, [dispose, changePhase]);
  useEffect(() => {
    window.addEventListener(ACCOUNT_CHANGED, cancel);
    const hide = () => { if (document.hidden && ['connecting', 'listening', 'finalizing'].includes(phaseRef.current)) cancel(); };
    document.addEventListener('visibilitychange', hide);
    const lifecycleGeneration = generation;
    return () => { if (cancelCurrentCapture === cancel) cancelCurrentCapture = undefined; lifecycleGeneration.current++; dispose(); window.removeEventListener(ACCOUNT_CHANGED, cancel); document.removeEventListener('visibilitychange', hide); };
  }, [cancel, dispose]);
  const finish = useCallback(() => {
    if (phaseRef.current !== 'listening') return;
    changePhase('finalizing'); setLevel(0);
    media.current?.getTracks().forEach(track => track.stop()); media.current = null;
    node.current?.port.postMessage('finish');
    deadline.current = setTimeout(() => {
      setError('The last phrase could not be finalized. Review the received text.');
      dispose(); changePhase('error');
    }, 7000);
  }, [changePhase, dispose]);
  const start = useCallback(async (onComplete?: (text: string) => void) => {
    if (['connecting', 'listening', 'finalizing'].includes(phaseRef.current)) return;
    cancelCurrentCapture?.(); cancelCurrentCapture = cancel;
    cancel(); completed.current = onComplete; const epoch = generation.current;
    changePhase('connecting'); setSeconds(0); transcript.current = new DictationTranscript();
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('Dictation needs a supported browser and a secure connection. You can still type.');
      const capability = await request<{ available: boolean }>('/v1/dictation/capability');
      if (epoch !== generation.current) return;
      if (!capability.available) throw new Error('Dictation is not available yet. You can still type or talk to Buddy.');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      if (epoch !== generation.current) { stream.getTracks().forEach(track => track.stop()); return; }
      media.current = stream;
      const audio = new AudioContext({ sampleRate: 48000 }); context.current = audio;
      await audio.resume(); await audio.audioWorklet.addModule('/dictation-worklet.js');
      if (epoch !== generation.current) return;
      const created = await request<Session>('/v1/dictation/sessions', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ sampleRate: audio.sampleRate }) });
      if (epoch !== generation.current) { void request(`/v1/dictation/sessions/${created.id}/cancel`, { method: 'POST' }).catch(() => {}); return; }
      session.current = created;
      const url = new URL(created.url);
      if (url.protocol !== 'wss:' && !(url.protocol === 'ws:' && ['localhost', '127.0.0.1'].includes(url.hostname))) throw new Error('Dictation requires a secure audio connection.');
      const ws = new WebSocket(url); socket.current = ws;
      const fail = () => { if (epoch !== generation.current) return; dispose(); setError('Dictation was interrupted. Your draft is safe; review any received text.'); changePhase('error'); };
      deadline.current = setTimeout(fail, 12000);
      ws.onopen = () => { if (epoch === generation.current) ws.send(JSON.stringify({ ticket: created.ticket })); };
      ws.onerror = fail;
      ws.onclose = () => { if (epoch === generation.current && !['review', 'error', 'idle'].includes(phaseRef.current)) fail(); };
      ws.onmessage = event => {
        if (epoch !== generation.current) return;
        try {
          const value = JSON.parse(event.data);
          if (value.sessionId && value.sessionId !== created.id) return;
          if (value.type === 'ready') {
            if (deadline.current) clearTimeout(deadline.current);
            const capture = new AudioWorkletNode(audio, 'dictation-capture'); node.current = capture;
            const source = audio.createMediaStreamSource(stream), sink = audio.createGain(); sink.gain.value = 0;
            source.connect(capture); capture.connect(sink); sink.connect(audio.destination);
            let lastMeterUpdate = 0;
            capture.port.onmessage = packet => {
              if (!['listening', 'finalizing'].includes(phaseRef.current) || ws.readyState !== WebSocket.OPEN) return;
              if (packet.data?.type === 'flushed') { stopCapture(); ws.send(JSON.stringify({ type: 'finish' })); return; }
              if (ws.bufferedAmount > 262144) { fail(); return; }
              ws.send(packet.data);
              const samples = new Int16Array(packet.data); let sum = 0;
              for (const sample of samples) sum += (sample / 32768) ** 2;
              if (Date.now() - lastMeterUpdate > 65) { lastMeterUpdate = Date.now(); setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 5)); }
            };
            changePhase('listening'); const began = Date.now();
            timer.current = setInterval(() => { const elapsed = Math.floor((Date.now() - began) / 1000); setSeconds(elapsed); if (Date.now() - began >= (created.maxSeconds - .5) * 1000) finish(); }, 250);
          } else if (value.type.startsWith('transcript.')) {
            transcript.current.receive(value); setText(transcript.current.final); setInterim(transcript.current.interim);
          } else if (value.type === 'completed') {
            changePhase('review'); dispose(); setInterim(''); completed.current?.(transcript.current.final);
          } else if (value.type === 'error') fail();
        } catch { fail(); }
      };
    } catch (cause) {
      if (epoch !== generation.current) return;
      dispose(); changePhase('error');
      setError(cause instanceof DOMException && cause.name === 'NotAllowedError' ? 'Allow microphone access to dictate. Your draft is unchanged.' : cause instanceof Error ? cause.message : 'Dictation could not start. You can still type.');
    }
  }, [cancel, changePhase, dispose, finish, stopCapture]);
  return { phase, text, interim, error, seconds, level, start, finish, cancel, active: ['connecting', 'listening', 'finalizing'].includes(phase) };
}
