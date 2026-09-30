import type { LocalLecture } from './lecture-local-store';
import type { LectureStatus } from './api';

export function needsFloatingRecovery(session: LocalLecture, status?: LectureStatus): boolean {
  return !session.noteId && !status?.noteId && (session.phase === 'interrupted' || session.phase === 'stop_requested');
}

export function processingStarted(status: LectureStatus): boolean {
  return status.captureComplete && status.recordingStatus !== 'failed' && status.recordingStatus !== 'completed';
}
