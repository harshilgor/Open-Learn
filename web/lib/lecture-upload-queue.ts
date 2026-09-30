/** Durable upload queue with retry and browser restart recovery. */

import { learningApi, LearningApiError, type LectureStatus } from '@/lib/api';
import { clearLocalAudio, getLocalLecture, listLocalChunks, listLocalLectures, setLocalChunkState, updateLocalLecture, type LocalLecture } from '@/lib/lecture-local-store';

export const LECTURE_SYNC_EVENT = 'open-learn-lecture-sync';
const active = new Map<string, Promise<void>>();
const resyncRequested = new Set<string>();
const retries = new Map<string, ReturnType<typeof setTimeout>>();
const attempts = new Map<string, number>();
let recoveryStarted = false;

function announce(id: string, status?: LectureStatus) {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(LECTURE_SYNC_EVENT, { detail: { id, status } }));
}

function schedule(id: string) {
  if (retries.has(id)) return;
  const count = Math.min(7, (attempts.get(id) || 0) + 1);
  attempts.set(id, count);
  const delay = Math.min(60_000, 1000 * 2 ** count) + Math.round(Math.random() * 500);
  retries.set(id, setTimeout(() => { retries.delete(id); void syncLecture(id); }, delay));
}

async function ensureServer(session: LocalLecture): Promise<LectureStatus> {
  const status = await learningApi.createLectureRecording({ id: session.id, title: session.title, courseId: session.courseId, startedAtMs: session.startedAtMs, noteFolder: session.noteFolder, preferences: session.preferences as unknown as Record<string, unknown> });
  if (session.noteId !== status.noteId) await updateLocalLecture(session.id, { noteId: status.noteId });
  announce(session.id, status);
  return status;
}

async function sync(id: string): Promise<void> {
  const session = await getLocalLecture(id);
  if (!session || session.phase === 'completed' || (session.phase === 'interrupted' && session.nextSequenceNumber === 0)) return;
  try {
    await ensureServer(session);
    if (session.expectedChunkCount !== null) {
      await learningApi.finalizeLectureRecording(id, { expectedChunkCount: session.expectedChunkCount, durationMs: session.durationMs, markersMs: session.markersMs, captureInterrupted: session.captureInterrupted });
    }
    for (const chunk of await listLocalChunks(id)) {
      if (chunk.state === 'server_confirmed') continue;
      if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new Error('Waiting for a connection. Audio is saved locally.');
      await setLocalChunkState(id, chunk.sequenceNumber, 'uploading');
      try {
        const acknowledged = await learningApi.uploadLectureChunk(id, chunk);
        if (acknowledged.sequenceNumber !== chunk.sequenceNumber || acknowledged.sha256 !== chunk.sha256) throw new Error('The server acknowledgement did not match this audio slice.');
        await setLocalChunkState(id, chunk.sequenceNumber, 'server_confirmed');
        announce(id);
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : 'Upload failed.';
        await setLocalChunkState(id, chunk.sequenceNumber, 'failed', message);
        if (cause instanceof LearningApiError && ['chunk_conflict', 'checksum_mismatch', 'unsupported_audio', 'invalid_chunk_time'].includes(cause.code)) {
          await updateLocalLecture(id, { lastError: message });
          announce(id);
          return;
        }
        throw cause;
      }
    }
    const status = await learningApi.getLectureRecording(id);
    if (status.recordingStatus === 'completed') {
      await updateLocalLecture(id, { phase: 'completed', lastError: null });
      await clearLocalAudio(id);
    } else if (status.recordingStatus === 'failed') {
      await updateLocalLecture(id, { lastError: status.error || 'Lecture processing failed. Open the recording note for details.' });
    } else {
      attempts.delete(id);
      await updateLocalLecture(id, { lastError: null });
    }
    announce(id, status);
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : 'Sync paused. Your audio remains saved locally.';
    await updateLocalLecture(id, { lastError: message }).catch(() => undefined);
    announce(id);
    schedule(id);
  }
}

export function syncLecture(id: string): Promise<void> {
  const running = active.get(id);
  if (running) { resyncRequested.add(id); return running; }
  const current = sync(id).finally(() => {
    active.delete(id);
    if (resyncRequested.delete(id)) void syncLecture(id);
  });
  active.set(id, current);
  return current;
}

export async function recoverLocalLectures(activeCaptureId: string | null = null): Promise<LocalLecture[]> {
  const sessions = await listLocalLectures();
  for (const session of sessions) {
    if (session.id !== activeCaptureId && (session.phase === 'recording' || session.phase === 'paused')) {
      await updateLocalLecture(session.id, { phase: 'interrupted', captureInterrupted: true, lastError: 'The browser closed during recording. Saved audio can be recovered; the final seconds may be missing.' });
    }
    if (session.phase !== 'completed' && session.nextSequenceNumber > 0) void syncLecture(session.id);
  }
  return listLocalLectures();
}

export function startLectureRecovery(): () => void {
  if (typeof window === 'undefined' || recoveryStarted) return () => undefined;
  recoveryStarted = true;
  const resume = () => { void listLocalLectures().then(sessions => { for (const session of sessions) if (session.phase !== 'completed' && session.nextSequenceNumber > 0) void syncLecture(session.id); }); };
  const visible = () => { if (document.visibilityState === 'visible') resume(); };
  window.addEventListener('online', resume);
  document.addEventListener('visibilitychange', visible);
  const interval = window.setInterval(resume, 10_000);
  return () => { window.removeEventListener('online', resume); document.removeEventListener('visibilitychange', visible); window.clearInterval(interval); recoveryStarted = false; };
}
