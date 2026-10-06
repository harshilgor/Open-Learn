import { request } from './api';

export const LIVE_LECTURE_TRANSCRIPTION_EVENT = 'open-learn-live-lecture-transcription';
export type LiveTranscriptTurn = { id: string; text: string };
export type LiveTranscriptionStatus = 'connecting' | 'connected' | 'paused' | 'stopped' | 'error';
type CaptureInterval = { startMs: number; endMs: number };
const MAX_RECORDING_MS = 24 * 60 * 60 * 1000;
const MAX_PENDING_REALTIME_COMMITS = 100;
export type LiveTranscriptionDetail = {
  recordingId: string;
  status: LiveTranscriptionStatus;
  turns: LiveTranscriptTurn[];
  persistedTurnIds: string[];
  interim: string;
  error?: string;
  persistenceError?: string;
};

type ClientSecret = { value: string; expiresAt: number };

export type CaptionProviderEvent={kind:'committed'|'delta'|'final'|'error';itemId:string;text?:string};
/** Adapter isolates provider wire events from capture/persistence state. */
export function adaptOpenAICaptionEvent(raw:unknown):CaptionProviderEvent|null{
  if(typeof raw!=='string')return null;
  let event:Record<string,unknown>;
  try{const parsed:unknown=JSON.parse(raw);if(!parsed||typeof parsed!=='object')return null;event=parsed as Record<string,unknown>;}catch{return null;}
  const itemId=typeof event.item_id==='string'?event.item_id:'';
  if(event.type==='error'||event.type==='conversation.item.input_audio_transcription.failed')return {kind:'error',itemId};
  if(!itemId||itemId.length>160)return null;
  if(event.type==='input_audio_buffer.committed')return {kind:'committed',itemId};
  if(event.type==='conversation.item.input_audio_transcription.delta'&&typeof event.delta==='string')return {kind:'delta',itemId,text:event.delta};
  if(event.type==='conversation.item.input_audio_transcription.completed'&&typeof event.transcript==='string')return {kind:'final',itemId,text:event.transcript};
  return null;
}

/** Ephemeral captions only. Durable batch transcription remains the archive source. */
export class LiveLectureTranscription {
  private peer: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private cancelled = false;
  private status: LiveTranscriptionStatus = 'connecting';
  private readonly turns = new Map<string, { text: string; final: boolean }>();
  private error: string | undefined;
  private audioContext: AudioContext | null = null;
  private vadTimer: ReturnType<typeof setInterval> | null = null;
  private pendingCommitInterval: CaptureInterval | null = null;
  private readonly committedIntervals: CaptureInterval[] = [];
  private readonly intervalByItemId = new Map<string, CaptureInterval | null>();
  private readonly committedItemIds = new Set<string>();
  private readonly finalizedTranscripts = new Map<string, string>();
  private startInProgress = false;
  private readonly streamId = crypto.randomUUID();
  private nextSequence = 0;
  private ownerId = '';
  private captureCapability = '';
  private readonly turnSequences = new Map<string, number>();
  private readonly persistedTurns = new Set<string>();
  private readonly savingTurns = new Set<string>();
  private persistenceError: string | undefined;
  private readonly interimTimers=new Map<string,ReturnType<typeof setTimeout>>();
  private readonly interimRevisions=new Map<string,number>();

  constructor(private readonly recordingId: string, private readonly captureElapsedMs: () => number) {}

  private publish() {
    const ordered = [...this.turns.entries()];
    const detail: LiveTranscriptionDetail = {
      recordingId: this.recordingId,
      status: this.status,
      turns: ordered.filter(([, turn]) => turn.final).slice(-20).map(([id, turn]) => ({ id, text: turn.text })),
      persistedTurnIds: [...this.persistedTurns],
      interim: ordered.filter(([, turn]) => !turn.final).map(([, turn]) => turn.text).join(' '),
      ...(this.error ? { error: this.error } : {}),
      ...(this.persistenceError ? { persistenceError: this.persistenceError } : {}),
    };
    window.dispatchEvent(new CustomEvent(LIVE_LECTURE_TRANSCRIPTION_EVENT, { detail }));
  }

  private async persistFinalTurn(itemId: string, transcript: string) {
    if (this.persistedTurns.has(itemId) || this.savingTurns.has(itemId)) return;
    if (!this.committedItemIds.has(itemId)) {
      this.finalizedTranscripts.set(itemId, transcript);
      while (this.finalizedTranscripts.size > 40) this.finalizedTranscripts.delete(this.finalizedTranscripts.keys().next().value!);
      return;
    }
    if (!this.ownerId || !this.captureCapability) return;
    const streamSequence = this.turnSequences.get(itemId) ?? ++this.nextSequence;
    this.turnSequences.set(itemId, streamSequence);
    const interval = this.intervalByItemId.get(itemId) ?? null;
    this.savingTurns.add(itemId);
    try {
      await request(`/v1/learners/${encodeURIComponent(this.ownerId)}/lecture-recordings/${encodeURIComponent(this.recordingId)}/live-transcription-segments`, {
        method: 'POST',
        headers: { 'X-Capture-Capability': this.captureCapability },
        body: JSON.stringify({
          streamId: this.streamId,
          streamSequence,
          providerItemId: itemId,
          transcript,
          transcriptionVersion: 1,
          startMs: interval?.startMs ?? null,
          endMs: interval?.endMs ?? null,
        }),
      });
      this.persistedTurns.add(itemId);
      this.intervalByItemId.delete(itemId);
      this.committedItemIds.delete(itemId);
      this.finalizedTranscripts.delete(itemId);
      this.persistenceError = undefined;
    } catch {
      this.persistenceError = 'A live caption could not be saved yet. Retry captions while recording to send it again.';
    } finally {
      this.savingTurns.delete(itemId);
      this.publish();
    }
  }

  private fail() {
    if (this.cancelled) return;
    this.status = 'error';
    this.error = 'Live captions disconnected. Your saved class audio is still recording.';
    this.closePeer();
    this.publish();
  }

  private closePeer() {
    for(const timer of this.interimTimers.values())clearTimeout(timer);
    this.interimTimers.clear();
    if (this.vadTimer) clearInterval(this.vadTimer);
    this.vadTimer = null;
    void this.audioContext?.close().catch(() => undefined);
    this.audioContext = null;
    if (this.channel) {
      this.channel.onmessage = null;
      this.channel.onopen = null;
      this.channel.onerror = null;
      this.channel.close();
    }
    this.channel = null;
    this.committedIntervals.length = 0;
    this.pendingCommitInterval = null;
    if (this.peer) {
      this.peer.onconnectionstatechange = null;
      this.peer.close();
    }
    this.peer = null;
  }

  private boundedInterval(startMs: number, endMs: number): CaptureInterval {
    const boundedStart = Math.min(MAX_RECORDING_MS - 1, Math.max(0, Math.round(startMs)));
    const boundedEnd = Math.min(MAX_RECORDING_MS, Math.max(boundedStart + 1, Math.round(endMs)));
    return { startMs: boundedStart, endMs: boundedEnd };
  }

  private recordingElapsedMs() {
    const value = this.captureElapsedMs();
    return Math.min(MAX_RECORDING_MS, Math.max(0, Number.isFinite(value) ? value : 0));
  }

  private queuePendingCommit(interval: CaptureInterval) {
    this.pendingCommitInterval = this.pendingCommitInterval
      ? { startMs: Math.min(this.pendingCommitInterval.startMs, interval.startMs), endMs: Math.max(this.pendingCommitInterval.endMs, interval.endMs) }
      : interval;
  }

  private commitTurn(interval: CaptureInterval) {
    const channel = this.channel;
    if (channel?.readyState === 'open') {
      if (this.committedIntervals.length >= MAX_PENDING_REALTIME_COMMITS) {
        this.queuePendingCommit(interval);
        return;
      }
      this.committedIntervals.push(interval);
      try {
        channel.send(JSON.stringify({ type: 'input_audio_buffer.commit' }));
      } catch {
        this.committedIntervals.pop();
        this.queuePendingCommit(interval);
      }
    } else {
      this.queuePendingCommit(interval);
    }
  }

  private flushPendingCommit() {
    const channel = this.channel;
    if (!this.pendingCommitInterval || channel?.readyState !== 'open' || this.committedIntervals.length >= MAX_PENDING_REALTIME_COMMITS) return;
    const interval = this.pendingCommitInterval;
    this.pendingCommitInterval = null;
    this.commitTurn(interval);
  }

  private async startClientVad(stream: MediaStream, context: AudioContext) {
    if (typeof AudioContext === 'undefined') throw new Error('Live captions need browser audio analysis.');
    if (context.state !== 'running') await context.resume();
    if (context.state !== 'running') throw new Error('Browser audio analysis is suspended.');
    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    context.createMediaStreamSource(stream).connect(analyser);
    this.audioContext = context;
    const samples = new Uint8Array(analyser.fftSize);
    let speechStartedAt = 0;
    let speechStartMs = 0;
    let lastVoicedAt = 0;
    let pendingSpeech = false;
    this.vadTimer = setInterval(() => {
      if (this.cancelled || context.state !== 'running') return;
      analyser.getByteTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / samples.length);
      const now = performance.now();
      if (rms >= 0.018) {
        if (!pendingSpeech) {
          speechStartedAt = now;
          speechStartMs = this.recordingElapsedMs();
        }
        pendingSpeech = true;
        lastVoicedAt = now;
      }
      if (pendingSpeech && (now - lastVoicedAt >= 1000 || now - speechStartedAt >= 15000)) {
        this.commitTurn(this.boundedInterval(speechStartMs, this.recordingElapsedMs()));
        pendingSpeech = false;
        speechStartedAt = 0;
        speechStartMs = 0;
        lastVoicedAt = 0;
      }
    }, 100);
  }

  async start(stream: MediaStream, ownerId: string, captureCapability: string, vadContext: AudioContext): Promise<void> {
    if (this.startInProgress) return;
    this.startInProgress = true;
    this.ownerId = ownerId;
    this.captureCapability = captureCapability;
    this.cancelled = false;
    this.error = undefined;
    this.status = 'connecting';
    this.audioContext = vadContext;
    this.publish();
    for (const [itemId, turn] of this.turns) if (turn.final && !this.persistedTurns.has(itemId)) void this.persistFinalTurn(itemId, turn.text);
    try {
      if (typeof RTCPeerConnection === 'undefined') throw new Error('WebRTC is unavailable.');
      const secret = await request<ClientSecret>(`/v1/learners/${encodeURIComponent(ownerId)}/lecture-recordings/${encodeURIComponent(this.recordingId)}/live-transcription-session`, {
        method: 'POST',
        headers: { 'X-Capture-Capability': captureCapability },
      });
      if (this.cancelled) return;

      const peer = new RTCPeerConnection();
      this.peer = peer;
      const track = stream.getAudioTracks()[0];
      if (!track || track.readyState !== 'live') throw new Error('The microphone is no longer active.');
      peer.addTrack(track, stream);
      await this.startClientVad(stream, vadContext);
      peer.onconnectionstatechange = () => {
        if (peer.connectionState === 'failed' || peer.connectionState === 'closed') this.fail();
      };
      const channel = peer.createDataChannel('oai-events');
      this.channel = channel;
      channel.onopen = () => {
        if (this.cancelled) return;
        this.status = 'connected';
        this.flushPendingCommit();
        this.publish();
      };
      channel.onerror = () => this.fail();
      channel.onmessage = event => this.receive(event.data);

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      if (this.cancelled) return;
      const response = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST',
        headers: { Authorization: `Bearer ${secret.value}`, 'Content-Type': 'application/sdp' },
        body: offer.sdp,
      });
      if (!response.ok) throw new Error('The caption session could not connect.');
      const answer = await response.text();
      if (this.cancelled) return;
      await peer.setRemoteDescription({ type: 'answer', sdp: answer });
    } catch {
      if (this.cancelled) return;
      this.fail();
    } finally {
      this.startInProgress = false;
    }
  }

  private receive(raw: unknown) {
    const event=adaptOpenAICaptionEvent(raw);if(!event)return;
    const itemId=event.itemId;
    if (event.kind === 'committed') {
      const interval = this.committedIntervals.shift() ?? null;
      this.intervalByItemId.set(itemId, interval);
      this.committedItemIds.add(itemId);
      const transcript = this.finalizedTranscripts.get(itemId);
      if (transcript !== undefined) void this.persistFinalTurn(itemId, transcript);
      this.flushPendingCommit();
    } else if (event.kind === 'delta') {
      const current = this.turns.get(itemId) || { text: '', final: false };
      if (!current.final){this.turns.set(itemId, { text: (current.text + (event.text??'')).slice(0,6000), final: false });this.queueInterim(itemId);}
      this.publish();
    } else if (event.kind === 'final') {
      const timer=this.interimTimers.get(itemId);if(timer)clearTimeout(timer);this.interimTimers.delete(itemId);
      this.turns.set(itemId, { text: (event.text??'').slice(0,6000), final: true });
      while (this.turns.size > 40) this.turns.delete(this.turns.keys().next().value!);
      this.publish();
      void this.persistFinalTurn(itemId, (event.text??'').slice(0,6000));
    } else if (event.kind === 'error') {
      this.fail();
    }
  }

  private queueInterim(itemId:string){
    if(this.interimTimers.has(itemId)||this.cancelled||!this.ownerId||!this.captureCapability)return;
    if(this.interimTimers.size>=20)return;
    this.interimTimers.set(itemId,setTimeout(()=>{
      this.interimTimers.delete(itemId);
      const turn=this.turns.get(itemId);if(!turn||turn.final||!turn.text.trim()||this.cancelled)return;
      const revision=(this.interimRevisions.get(itemId)??0)+1;this.interimRevisions.set(itemId,revision);
      while(this.interimRevisions.size>40)this.interimRevisions.delete(this.interimRevisions.keys().next().value!);
      void request(`/v1/learners/${encodeURIComponent(this.ownerId)}/lecture-recordings/${encodeURIComponent(this.recordingId)}/live-transcription-interim`,{
        method:'POST',headers:{'X-Capture-Capability':this.captureCapability},
        body:JSON.stringify({streamId:this.streamId,providerItemId:itemId,updateRevision:revision,transcript:turn.text}),
      }).catch(()=>{ /* Latest bounded snapshot is retried on the next provider delta. */ });
    },1000));
  }

  pause() {
    if (this.cancelled) return;
    this.cancelled = true;
    this.closePeer();
    this.status = 'paused';
    this.publish();
  }

  stop() {
    this.cancelled = true;
    this.closePeer();
    this.status = 'stopped';
    this.publish();
  }
}
