/** Continuous microphone session that persists each independent audio slice. */
import { createLocalLecture, discardEmptyLocalLecture, getLocalLecture, persistAudioSlice, updateLocalLecture, defaultLecturePreferences, type LecturePreferences } from '@/lib/lecture-local-store';
import { syncLecture } from '@/lib/lecture-upload-queue';
import { ACCOUNT_CHANGED } from './account-session';
import { LiveLectureTranscription } from './live-lecture-transcription';

export type CapturePhase = 'idle' | 'recording' | 'paused' | 'finalizing' | 'saved' | 'error';
export const LECTURE_CAPTURE_EVENT = 'open-learn-lecture-capture';

class LectureCaptureController {
  private stream: MediaStream | null = null;
  private sourceStreams: MediaStream[] = [];
  private captureContext: AudioContext | null = null;
  private recorder: MediaRecorder | null = null;
  private sliceTimer: ReturnType<typeof setTimeout> | null = null;
  private sliceStartedAt = 0;
  private capturedMs = 0;
  private sliceStartMs = 0;
  private saving: Promise<void> = Promise.resolve();
  private stopRequested = false;
  private pauseRequested = false;
  private finishing = false;
  private captureFailure: string | null = null;
  private startInProgress = false;
  private startGeneration = 0;
  private id: string | null = null;
  private markers: number[] = [];
  private phaseValue: CapturePhase = 'idle';
  private errorValue = '';
  private watchdog: ReturnType<typeof setInterval> | null = null;
  private wakeLock: WakeLockSentinel | null = null;
  private liveTranscription: LiveLectureTranscription | null = null;
  private liveTranscriptionRequested = false;
  private liveOwnerId = '';
  private captureCapability = '';
  private liveVadContext: AudioContext | null = null;
  private microphoneId = '';
  private systemAudioRequested = false;
  private resuming = false;

  get phase() { return this.phaseValue; }
  get recordingId() { return this.id; }
  get error() { return this.errorValue; }
  get mediaStream() { return this.stream; }
  get includesSystemAudio() { return this.systemAudioRequested; }
  get markersMs() { return [...this.markers]; }
  get elapsedMs() { return this.phaseValue === 'recording' ? this.capturedMs + Math.max(0, performance.now() - this.sliceStartedAt) : this.capturedMs; }

  private emit(phase: CapturePhase, error = '') {
    this.phaseValue = phase;
    this.errorValue = error;
    window.dispatchEvent(new CustomEvent(LECTURE_CAPTURE_EVENT, { detail: { id: this.id, phase, error, elapsedMs: this.elapsedMs } }));
  }

  private release() {
    if (this.watchdog) clearInterval(this.watchdog);
    this.watchdog = null;
    void this.wakeLock?.release();
    this.wakeLock = null;
    if (this.sliceTimer) clearTimeout(this.sliceTimer);
    this.sliceTimer = null;
    this.recorder = null;
    this.liveTranscription?.stop();
    this.liveTranscription = null;
    this.liveTranscriptionRequested = false;
    if (this.liveVadContext && this.liveVadContext.state !== 'closed') void this.liveVadContext.close().catch(() => undefined);
    this.liveVadContext = null;
    this.releaseMedia();
  }

  private releaseMedia() {
    const tracks = new Set([...(this.stream?.getTracks() || []), ...this.sourceStreams.flatMap(stream => stream.getTracks())]);
    tracks.forEach(track => track.stop());
    this.stream = null;
    this.sourceStreams = [];
    if (this.captureContext && this.captureContext.state !== 'closed') void this.captureContext.close().catch(() => undefined);
    this.captureContext = null;
  }

  private listenToSource(stream: MediaStream, label: string, generation: number) {
    for (const track of stream.getAudioTracks()) {
      track.addEventListener('ended', () => {
        if (generation !== this.startGeneration || this.stopRequested || this.pauseRequested) return;
        if (this.startInProgress) this.cancelStart(`${label} Choose the source again and retry.`);
        else { this.captureFailure = `${label} Recover the saved recording.`; void this.stop(); }
      });
      track.addEventListener('mute', () => {
        if (generation === this.startGeneration) this.emit(this.phaseValue, `${label.startsWith('Computer') ? 'Computer audio' : 'The microphone'} is muted. Check capture before continuing.`);
      });
    }
  }

  cancelStart(message?: string) {
    if (!this.startInProgress) return;
    this.startGeneration += 1;
    this.release();
    this.id = null;
    this.stopRequested = false;
    this.pauseRequested = false;
    this.finishing = false;
    this.emit(message ? 'error' : 'idle', message || '');
  }

  async start(input: { title: string; courseId?: string | null; buddyId?:string; noteFolder?: string | null; preferences?: LecturePreferences; ownerId?:string; classSetup?:import('./in-class').ClassSetup; microphoneId?:string; includeSystemAudio?:boolean; liveTranscription?:boolean; liveVadContext?:AudioContext|null }): Promise<string> {
    if (this.startInProgress || this.phaseValue === 'recording' || this.phaseValue === 'paused' || this.phaseValue === 'finalizing') throw new Error('A lecture is already being recorded or started.');
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('Microphone recording is unavailable in this browser.');
    this.startInProgress = true;
    const generation = ++this.startGeneration;
    let systemStream: MediaStream | null = null;
    let microphoneStream: MediaStream | null = null;
    let manifestCreated = false;
    let recordingId = '';
    const ensureCurrent = async () => {
      if (generation === this.startGeneration) return;
      microphoneStream?.getTracks().forEach(track => track.stop());
      systemStream?.getTracks().forEach(track => track.stop());
      this.release();
      this.id = null;
      if (manifestCreated && recordingId) {
        await updateLocalLecture(recordingId, { phase: 'interrupted', captureInterrupted: true });
        await discardEmptyLocalLecture(recordingId).catch(() => undefined);
      }
      throw new DOMException('Recording start was cancelled.', 'AbortError');
    };
    try {
      if (input.includeSystemAudio) {
        if (!navigator.mediaDevices.getDisplayMedia || typeof AudioContext === 'undefined') throw new Error('Computer-audio capture is unavailable in this browser.');
        // Invoke display capture while the user's Start click is still active.
        // Electron needs temporary video permission for loopback audio; stop
        // every video track immediately and keep only the selected source audio.
        this.captureContext = new AudioContext();
        const contextReady = this.captureContext.resume().then(() => null, cause => cause);
        const systemCapture = navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
        void systemCapture.then(stream => stream.getVideoTracks().forEach(track => track.stop()), () => undefined);
        systemStream = await systemCapture;
        await ensureCurrent();
        if (!systemStream.getAudioTracks().length) throw new Error('Computer audio was not available from the selected source.');
        this.sourceStreams = [systemStream];
        this.listenToSource(systemStream, 'Computer audio capture ended.', generation);
        if (systemStream.getAudioTracks().some(track => track.readyState !== 'live')) throw new Error('Computer audio capture ended before recording could start.');

        microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, ...(input.microphoneId?{deviceId:{exact:input.microphoneId}}:{}) } });
        await ensureCurrent();
        this.sourceStreams.unshift(microphoneStream);
        this.listenToSource(microphoneStream, 'The microphone disconnected.', generation);
        if (microphoneStream.getAudioTracks().some(track => track.readyState !== 'live')) throw new Error('The microphone disconnected before recording could start.');
        const contextError = await contextReady;
        await ensureCurrent();
        if (contextError) throw contextError;
        if (!this.captureContext || this.captureContext.state !== 'running') throw new Error('The audio mixer could not start.');
        const destination = this.captureContext.createMediaStreamDestination();
        for (const source of this.sourceStreams) {
          const audioOnly = new MediaStream(source.getAudioTracks());
          this.captureContext.createMediaStreamSource(audioOnly).connect(destination);
        }
        this.stream = destination.stream;
      } else {
        microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, ...(input.microphoneId?{deviceId:{exact:input.microphoneId}}:{}) } });
        await ensureCurrent();
        this.sourceStreams = [microphoneStream];
        this.listenToSource(microphoneStream, 'The microphone disconnected.', generation);
        if (microphoneStream.getAudioTracks().some(track => track.readyState !== 'live')) throw new Error('The microphone disconnected before recording could start.');
        this.stream = microphoneStream;
      }
      const storage = await navigator.storage?.estimate?.();
      await ensureCurrent();
      if (storage?.quota && storage.usage !== undefined && storage.quota - storage.usage < 20 * 1024 * 1024) throw new Error('Local storage is nearly full. Export saved recordings before recording.');
      await navigator.storage?.persist?.().catch(() => false);
      await ensureCurrent();
      this.wakeLock = await navigator.wakeLock?.request('screen').catch(() => null) || null;
      await ensureCurrent();
      recordingId = `rec_${crypto.randomUUID().replaceAll('-', '')}`;
      await createLocalLecture({ id: recordingId, ownerId:input.ownerId,classSetup:input.classSetup, buddyId:input.buddyId, title: input.title, courseId: input.courseId || null, noteFolder: input.noteFolder || null, startedAtMs: Date.now(), preferences: { ...(input.preferences || defaultLecturePreferences), captureSystemAudio: Boolean(input.includeSystemAudio) } });
      manifestCreated = true;
      await ensureCurrent();
      this.id = recordingId;
      this.microphoneId = input.microphoneId || '';
      this.systemAudioRequested = Boolean(input.includeSystemAudio);
      this.liveTranscriptionRequested = Boolean(input.liveTranscription);
      this.liveOwnerId = input.ownerId || '';
      this.captureCapability = input.classSetup?.captureCapability || '';
      this.liveVadContext = input.liveTranscription ? input.liveVadContext || null : null;
      this.capturedMs = 0;
      this.markers = [];
      this.stopRequested = false;
      this.pauseRequested = false;
      this.finishing = false;
      this.captureFailure = null;
      this.saving = Promise.resolve();
      this.watchdog = setInterval(() => {
        if (this.phaseValue === 'recording' && performance.now() - this.sliceStartedAt > 20000) this.emit('recording', 'Audio delivery has stalled. Stop and recover the saved portion.');
      }, 5000);
      this.startSlice();
      this.emit('recording');
      return recordingId;
    } catch (cause) {
      if (generation === this.startGeneration) {
        microphoneStream?.getTracks().forEach(track => track.stop());
        systemStream?.getTracks().forEach(track => track.stop());
        if (manifestCreated && recordingId) {
          await updateLocalLecture(recordingId, { phase: 'interrupted', captureInterrupted: true }).catch(() => undefined);
          await discardEmptyLocalLecture(recordingId).catch(() => undefined);
        }
        this.release();
      }
      throw cause;
    } finally {
      this.startInProgress = false;
    }
  }

  private startSlice() {
    if (!this.stream || !this.id || this.stopRequested || this.pauseRequested) return;
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(this.stream, { ...(mimeType ? { mimeType } : {}), audioBitsPerSecond: 64_000 });
    const pieces: Blob[] = [];
    this.recorder = recorder;
    this.sliceStartMs = this.capturedMs;
    this.sliceStartedAt = performance.now();
    const startMs = this.sliceStartMs;
    recorder.ondataavailable = event => { if (event.data.size) pieces.push(event.data); };
    recorder.onerror = () => { this.captureFailure = 'The microphone stopped unexpectedly. Saved audio can be recovered.'; this.emit('error', this.captureFailure); this.stopRequested = true; this.stopCurrent(); };
    recorder.onstop = () => {
      if (this.sliceTimer) clearTimeout(this.sliceTimer);
      this.sliceTimer = null;
      const endMs = Math.max(startMs + 1, Math.round(startMs + performance.now() - this.sliceStartedAt));
      this.capturedMs = endMs;
      const blob = new Blob(pieces, { type: recorder.mimeType || mimeType || 'audio/webm' });
      if (!this.stopRequested && !this.pauseRequested) {
        try { this.startSlice(); } catch (cause) { this.stopRequested = true; this.captureFailure = cause instanceof Error ? cause.message : 'Could not continue recording.'; this.emit('error', this.captureFailure); }
      }
      if (!blob.size) {
        this.stopRequested = true;
        this.captureFailure = 'An audio slice was empty. Earlier audio is safe; stop and recover this lecture.';
        this.emit('error', this.captureFailure);
      } else {
        const id = this.id!;
        this.saving = this.saving.then(async () => {
          await persistAudioSlice(id, blob, startMs, endMs);
          void syncLecture(id);
        }).catch(cause => {
          this.stopRequested = true;
          this.captureFailure = cause instanceof Error ? `Local audio storage failed: ${cause.message}` : 'Local audio storage failed.';
          this.emit('error', this.captureFailure);
          this.stopCurrent();
        });
      }
      if (this.stopRequested) void this.finishStop();
      else if (this.pauseRequested) { this.releaseMedia(); void this.wakeLock?.release(); this.wakeLock = null; this.emit('paused'); }
    };
    recorder.start();
    this.sliceTimer = setTimeout(() => this.stopCurrent(), 5000);
  }

  private stopCurrent() {
    if (this.sliceTimer) clearTimeout(this.sliceTimer);
    this.sliceTimer = null;
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
  }

  async pause() {
    if (this.phaseValue !== 'recording' || !this.id) return;
    this.pauseRequested = true;
    this.liveTranscription?.pause();
    if (this.liveVadContext && this.liveVadContext.state !== 'closed') void this.liveVadContext.close().catch(() => undefined);
    this.liveVadContext = null;
    this.stopCurrent();
    await updateLocalLecture(this.id, { phase: 'paused' });
  }

  async resume() {
    if (this.phaseValue !== 'paused' || !this.id || this.resuming) return;
    this.resuming = true;
    const generation = this.startGeneration;
    const streams: MediaStream[] = [];
    try {
      // Resume is a user gesture; source selection is requested again explicitly.
      if (this.systemAudioRequested) {
        this.captureContext = new AudioContext();
        void this.captureContext.resume().catch(() => undefined);
        const system = await navigator.mediaDevices.getDisplayMedia({audio: true, video: true});
        system.getVideoTracks().forEach(track => track.stop()); streams.push(system);
        if (!system.getAudioTracks().length) throw new Error('The selected source has no computer audio.');
      }
      if (this.stopRequested || generation !== this.startGeneration) throw new Error('Resume cancelled.');
      const microphone = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, ...(this.microphoneId ? {deviceId: {exact: this.microphoneId}} : {})}});
      streams.unshift(microphone);
      if (this.stopRequested || generation !== this.startGeneration) throw new Error('Resume cancelled.');
      this.sourceStreams = streams;
      if (this.systemAudioRequested) {
        if (!this.captureContext || this.captureContext.state !== 'running') throw new Error('The audio mixer could not resume.');
        const destination = this.captureContext.createMediaStreamDestination();
        for (const source of streams) this.captureContext.createMediaStreamSource(new MediaStream(source.getAudioTracks())).connect(destination);
        this.stream = destination.stream;
      } else this.stream = microphone;
      for (const source of streams) this.listenToSource(source, source === microphone ? 'The microphone disconnected.' : 'Computer audio capture ended.', generation);
      this.wakeLock = await navigator.wakeLock?.request('screen').catch(() => null) || null;
      if (this.stopRequested || generation !== this.startGeneration) throw new Error('Resume cancelled.');
    if (this.liveTranscriptionRequested && typeof AudioContext !== 'undefined') {
      this.liveVadContext = new AudioContext();
      void this.liveVadContext.resume().catch(() => undefined);
    }
    this.pauseRequested = false;
    this.startSlice();
    await updateLocalLecture(this.id, { phase: 'recording' });
    this.emit('recording');
    if (this.liveTranscriptionRequested) void this.startLiveTranscription();
    } catch (cause) {
      streams.forEach(stream => stream.getTracks().forEach(track => track.stop()));
      this.pauseRequested = true;
      this.releaseMedia();
      void this.wakeLock?.release(); this.wakeLock = null;
      if (!this.stopRequested) this.emit('paused', cause instanceof Error ? cause.message : 'Could not resume capture.');
    } finally { this.resuming = false; }
  }

  async startLiveTranscription() {
    if (!this.liveTranscriptionRequested || !this.id || !this.stream || !this.liveOwnerId || !this.captureCapability || this.phaseValue !== 'recording') return;
    if (!this.liveVadContext) {
      window.dispatchEvent(new CustomEvent('open-learn-live-lecture-transcription', { detail: { recordingId: this.id, status: 'error', turns: [], persistedTurnIds: [], interim: '', error: 'Live captions need browser audio analysis. Your saved class audio is still recording.' } }));
      return;
    }
    const client = this.liveTranscription || new LiveLectureTranscription(this.id, () => this.elapsedMs);
    this.liveTranscription = client;
    await client.start(this.stream, this.liveOwnerId, this.captureCapability, this.liveVadContext);
  }

  deferLiveTranscription() {
    this.liveTranscription?.stop();
    this.liveTranscription = null;
    if (this.liveVadContext && this.liveVadContext.state !== 'closed') void this.liveVadContext.close().catch(() => undefined);
    this.liveVadContext = null;
  }

  retryLiveTranscription() {
    if (!this.liveTranscriptionRequested || this.phaseValue !== 'recording') return;
    if (typeof AudioContext === 'undefined') {
      window.dispatchEvent(new CustomEvent('open-learn-live-lecture-transcription', { detail: { recordingId: this.id, status: 'error', turns: [], persistedTurnIds: [], interim: '', error: 'Live captions need browser audio analysis. Your saved class audio is still recording.' } }));
      return;
    }
    if (!this.liveVadContext || this.liveVadContext.state === 'closed') this.liveVadContext = new AudioContext();
    if (this.liveVadContext.state !== 'running') void this.liveVadContext.resume().catch(() => undefined);
    void this.startLiveTranscription();
  }

  stopLiveTranscription() {
    this.liveTranscriptionRequested = false;
    this.liveTranscription?.stop();
    this.liveTranscription = null;
    if (this.liveVadContext && this.liveVadContext.state !== 'closed') void this.liveVadContext.close().catch(() => undefined);
    this.liveVadContext = null;
  }

  mark() {
    if (this.phaseValue !== 'recording') return;
    this.markers.push(Math.round(this.elapsedMs));
  }

  async stop() {
    if (!this.id || this.stopRequested) return;
    this.stopRequested = true;
    this.stopLiveTranscription();
    this.emit('finalizing');
    if (this.recorder && this.recorder.state !== 'inactive') {this.stopCurrent();this.releaseMedia();}
    else await this.finishStop();
  }

  private async finishStop() {
    if (this.finishing || !this.id) return;
    this.finishing = true;
    this.release();
    await this.saving;
    const session = await getLocalLecture(this.id);
    if (!session) { this.emit('error', 'The local recording manifest is missing.'); return; }
    if (this.captureFailure) {
      await updateLocalLecture(this.id, { phase: 'interrupted', captureInterrupted: true, lastError: this.captureFailure });
      this.emit('error', this.captureFailure);
      if (session.nextSequenceNumber > 0) void syncLecture(this.id);
      return;
    }
    if (session.nextSequenceNumber === 0) { this.emit('error', 'No audio was saved.'); return; }
    await updateLocalLecture(this.id, { phase: 'stop_requested', expectedChunkCount: session.nextSequenceNumber, durationMs: this.capturedMs, markersMs: this.markers });
    this.emit('saved');
    void syncLecture(this.id);
  }
}

export const lectureCapture = new LectureCaptureController();
if(typeof window!=='undefined')window.addEventListener(ACCOUNT_CHANGED,()=>{lectureCapture.cancelStart('Account changed. Capture setup was cancelled.');void lectureCapture.stop();});
