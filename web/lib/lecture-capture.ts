/** Continuous microphone session that persists each independent audio slice. */
import { createLocalLecture, getLocalLecture, persistAudioSlice, updateLocalLecture, defaultLecturePreferences, type LecturePreferences } from '@/lib/lecture-local-store';
import { syncLecture } from '@/lib/lecture-upload-queue';

export type CapturePhase = 'idle' | 'recording' | 'paused' | 'finalizing' | 'saved' | 'error';
export const LECTURE_CAPTURE_EVENT = 'open-learn-lecture-capture';

class LectureCaptureController {
  private stream: MediaStream | null = null;
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
  private id: string | null = null;
  private markers: number[] = [];
  private phaseValue: CapturePhase = 'idle';
  private errorValue = '';

  get phase() { return this.phaseValue; }
  get recordingId() { return this.id; }
  get error() { return this.errorValue; }
  get mediaStream() { return this.stream; }
  get markersMs() { return [...this.markers]; }
  get elapsedMs() { return this.phaseValue === 'recording' ? this.capturedMs + Math.max(0, performance.now() - this.sliceStartedAt) : this.capturedMs; }

  private emit(phase: CapturePhase, error = '') {
    this.phaseValue = phase;
    this.errorValue = error;
    window.dispatchEvent(new CustomEvent(LECTURE_CAPTURE_EVENT, { detail: { id: this.id, phase, error, elapsedMs: this.elapsedMs } }));
  }

  private release() {
    if (this.sliceTimer) clearTimeout(this.sliceTimer);
    this.sliceTimer = null;
    this.recorder = null;
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
  }

  async start(input: { title: string; courseId?: string | null; noteFolder?: string | null; preferences?: LecturePreferences }): Promise<string> {
    if (this.phaseValue === 'recording' || this.phaseValue === 'paused' || this.phaseValue === 'finalizing') throw new Error('A lecture is already being recorded.');
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('Microphone recording is unavailable in this browser.');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    this.stream = stream;
    try {
      await navigator.storage?.persist?.().catch(() => false);
      const id = `rec_${crypto.randomUUID().replaceAll('-', '')}`;
      await createLocalLecture({ id, title: input.title, courseId: input.courseId || null, noteFolder: input.noteFolder || null, startedAtMs: Date.now(), preferences: input.preferences || defaultLecturePreferences });
      this.id = id;
      this.capturedMs = 0;
      this.markers = [];
      this.stopRequested = false;
      this.pauseRequested = false;
      this.finishing = false;
      this.captureFailure = null;
      this.saving = Promise.resolve();
      this.startSlice();
      this.emit('recording');
      return id;
    } catch (cause) {
      this.release();
      throw cause;
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
      else if (this.pauseRequested) this.emit('paused');
    };
    recorder.start();
    this.sliceTimer = setTimeout(() => this.stopCurrent(), 8000);
  }

  private stopCurrent() {
    if (this.sliceTimer) clearTimeout(this.sliceTimer);
    this.sliceTimer = null;
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
  }

  async pause() {
    if (this.phaseValue !== 'recording' || !this.id) return;
    this.pauseRequested = true;
    this.stopCurrent();
    await updateLocalLecture(this.id, { phase: 'paused' });
  }

  async resume() {
    if (this.phaseValue !== 'paused' || !this.id) return;
    this.pauseRequested = false;
    this.startSlice();
    await updateLocalLecture(this.id, { phase: 'recording' });
    this.emit('recording');
  }

  mark() {
    if (this.phaseValue !== 'recording') return;
    this.markers.push(Math.round(this.elapsedMs));
  }

  async stop() {
    if (!this.id || this.stopRequested) return;
    this.stopRequested = true;
    this.emit('finalizing');
    if (this.recorder && this.recorder.state !== 'inactive') this.stopCurrent();
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
