import { LearningApiError, request, type Gear, type LessonArtifact, type ModeTransitionSuggestion, type SessionPositionUpdate, type SessionSnapshot } from './api';

export type ChatMode = 'ask' | 'learn' | 'quiz';
export type Source = { spanId: string; title: string; text: string; pageIndex: number };
export type Journey = {
  id: string; sessionId: string; revision: number; modeRevision?: number; mode: ChatMode; gear: Gear; goal: string;
  status: string; position: number; canonicalConceptIds?: string[]; taughtCanonicalConceptIds?: string[]; taskId?: string;
  steps: { conceptId: string; title: string; objective: string }[];
  turns: { question: string; lesson?: LessonArtifact; sessionId: string; generationId?: string; status?: 'pending' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; errorCode?: string; submittedAt?: number; sources?: Source[]; noteContext?: { label: string; totalCharacters: number; notes: { noteId: string; title: string; revision: number; startOffset?: number | null; endOffset?: number | null }[] }; transitionSuggestion?: ModeTransitionSuggestion | null }[];
};
export type Presentation = {
  id: string; quizId: string; concept_id: string; kind: 'single' | 'multiple' | 'short'; stem: string;
  options: { id: string; label: string }[]; hints: string[]; attemptId: string | null; difficulty: string;
  hintCount?: number; sources?: Source[]; retryOf?: string;
  questionPlan?: { objective: string; reason_codes: string[]; capability: string };
};
export type Attempt = {
  id: string; presentationId: string; conceptId: string; response: string; selectedIds: string[];
  score: number | null; feedback: string; solution: string; correctIds: string[]; status: string;
  outcome: string; assisted: boolean; conceptState: string | null;
};
export type Quiz = {
  id: string; sessionId: string; title: string; revision: number; status: string; count: number;
  lessonNoteId?: string | null; requestedTopic?: string | null; origin?: string;
  contextSource?: boolean; sourceSuperseded?:boolean;
  mode: 'topic_drill' | 'timed_short_quiz'; modeConfig: { duration_seconds?: number }; deadlineAt: string | null; remainingSeconds: number | null;
  current: Presentation | null; attempts: Attempt[];
  challenges?: { id: string; presentationId: string; status: string; explanation?: string; outcome?: string }[];
  summary: { score: number | null; evaluated: number; attempted: number; total: number; assisted: number; skipped: number; dontKnow: number; independentCorrect: number; retries: number; contested: number };
};
type Job = { id: string; status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; result: { quizId?: string; sessionId?: string; itemId?: string; attemptId?: string; noteDraftId?: string; noteId?: string; proposalId?: string; status?: string; heading?: string; applyKind?: string; skipped?: string; message?: string } | null };
export const getJourney = (sid: string) => request<Journey>(`/v1/sessions/${sid}/journey`);
export const getQuiz = (qid: string) => request<Quiz>(`/v1/quizzes/${qid}`);
export const getSessionSnapshot = (sid: string) => request<SessionSnapshot>(`/v1/sessions/${encodeURIComponent(sid)}/snapshot`);
export const updateSessionPosition = (sid: string, input: SessionPositionUpdate) =>
  request<SessionSnapshot>(`/v1/sessions/${encodeURIComponent(sid)}/position`, { method: 'PATCH', body: JSON.stringify(input) });

/** Stable URL for a learning session. localStorage is only a disposable hint. */
export function sessionPath(sessionId: string | null | undefined): string {
  return sessionId ? `/s/${encodeURIComponent(sessionId)}` : '/chat';
}

export function sessionIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/s\/([^/?#]+)/);
  if (!match) return null;
  try { return decodeURIComponent(match[1]); } catch { return match[1]; }
}

/** Prefer the route, then a disposable localStorage hint. */
export function resolveSessionHint(pathname = typeof window === 'undefined' ? '/' : window.location.pathname): string | null {
  const fromRoute = sessionIdFromPath(pathname);
  if (fromRoute) return fromRoute;
  try { return localStorage.getItem('forma-chat-session'); } catch { return null; }
}

export function rememberSessionHint(sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem('forma-chat-session', sessionId);
    else localStorage.removeItem('forma-chat-session');
  } catch { /* Server snapshot remains authoritative. */ }
}

export function navigateToSession(sessionId: string | null, replace = false): void {
  if (typeof window === 'undefined') return;
  if (replace && window.location.pathname === '/notes') return;
  const query = new URLSearchParams(window.location.search);
  const kept=new URLSearchParams();
  if(query.has('course'))kept.set('course',query.get('course')||'');
  if(query.has('class')&&window.location.pathname===sessionPath(sessionId))kept.set('class',query.get('class')||'');
  const next = `${sessionPath(sessionId)}${kept.size?'?'+kept.toString():''}`;
  if (`${window.location.pathname}${window.location.search}` === next) return;
  window.history[replace ? 'replaceState' : 'pushState']({ sessionId }, '', next);
}

export function isStaleSessionConflict(cause: unknown): boolean {
  return cause instanceof LearningApiError && cause.status === 409 && cause.code === 'stale_session';
}

/** Snapshot-first restore: committed position comes from the server, Journey fills turn content. */
export async function restoreSessionAuthority(sessionId: string): Promise<{ snapshot: SessionSnapshot; journey: Journey }> {
  const snapshot = await getSessionSnapshot(sessionId);
  const journey = await getJourney(sessionId);
  return { snapshot, journey };
}

/** Persist the job ID before polling so reloads recover committed operations. */
export async function workflow(path: string, body: unknown, scope: string, idempotencyKey?: string): Promise<Job['result']> {
  const serialized = JSON.stringify(body);
  let key = idempotencyKey || crypto.randomUUID();
  try {
    const pending = JSON.parse(localStorage.getItem(`forma-command:${scope}`) || 'null');
    if (!idempotencyKey && pending?.path === path && pending?.body === serialized) key = pending.key;
    localStorage.setItem(`forma-command:${scope}`, JSON.stringify({ path, body: serialized, key }));
  } catch { /* In-memory requests remain idempotent. */ }
  const job = await request<Job>(`/v1${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body) });
  try { localStorage.setItem(`forma-job:${scope}`, job.id); } catch { /* Server retains the operation. */ }
  return waitForJob(job.id, scope);
}
export async function waitForJob(id: string, scope: string): Promise<Job['result']> {
  for (let i = 0; i < 600; i++) {
    try {
      const job = await request<Job>(`/v1/learning-jobs/${id}`);
      if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
        try { localStorage.removeItem(`forma-job:${scope}`); localStorage.removeItem(`forma-command:${scope}`); } catch { /* Optional recovery pointer. */ }
        if (job.status === 'failed') throw new Error(job.result?.message || 'Please try again.');
        if (job.status === 'cancelled') throw new Error('Stopped. Your last completed step and saved answers are preserved.');
        return job.result;
      }
    } catch (cause) {
      if (cause instanceof LearningApiError && cause.status === 404) {
        // The job no longer exists on the server (completed & pruned, cancelled, or server restart).
        // Clear the stale pointer and return cleanly without failing the conversation.
        try { localStorage.removeItem(`forma-job:${scope}`); localStorage.removeItem(`forma-command:${scope}`); } catch { /* Optional recovery pointer. */ }
        return null;
      }
      throw cause;
    }
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
  throw new Error('This operation is still running. Reload to reconnect.');
}

export async function cancelWorkflow(scope: string): Promise<void> {
  const id = localStorage.getItem(`forma-job:${scope}`);
  if (id) await request(`/v1/learning-jobs/${id}/cancel`, { method: 'POST' });
}
