/** Cross-surface request to begin a class, optionally for a specific course. */
export const START_CLASS_EVENT = 'openlearn:start-class';
export type StartClassDetail = { courseId?: string };

/** How long a request made before the class tool mounted is still honoured. */
const PENDING_TTL_MS = 30_000;
let pending: { detail: StartClassDetail; at: number } | null = null;

/**
 * Ask the class tool to preselect a course and focus its start action.
 * The request is also kept briefly so a class tool that mounts after the
 * event (it loads lazily) still receives it.
 */
export function startClass(courseId?: string): boolean {
  if (typeof window === 'undefined') return false;
  const detail: StartClassDetail = courseId ? { courseId } : {};
  pending = { detail, at: Date.now() };
  // The study panel cancels the event when it opens the class tool; callers fall back otherwise.
  return !window.dispatchEvent(new CustomEvent<StartClassDetail>(START_CLASS_EVENT, { detail, cancelable: true }));
}

/** Read the latest unexpired start request without consuming it. */
export function peekPendingStartClass(): StartClassDetail | null {
  if (!pending || Date.now() - pending.at > PENDING_TTL_MS) return null;
  return pending.detail;
}

/** Mark the latest start request as handled. */
export function clearPendingStartClass(): void {
  pending = null;
}
