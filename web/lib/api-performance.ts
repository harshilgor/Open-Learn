/** Bounded local diagnostics: no bodies, query strings, owners, or credentials. */
export type ApiTiming = { resource: string; durationMs: number; status: number; startedAt: number;
  method: string; traceId?: string; serverTimingMs?: Record<string, number>; outcome: string };
export type GenerationTiming = { stage: 'accepted' | 'mode_choice' | 'first_text_received' | 'first_text_committed' | 'completed' | 'failed' | 'cancelled' | 'disconnected';
  durationMs: number; traceId: string; origin: 'submission' | 'resume' };
const samples: ApiTiming[] = [];
const generationSamples: GenerationTiming[] = [];
const generations = new Map<string, { started: number; traceId: string; origin: 'submission' | 'resume'; received: boolean; committed: boolean }>();
const pendingCommits = new Set<string>();
const stages = new Set(['api_headers', 'admission', 'identity', 'database_checkout', 'database_query', 'database_hold', 'proxy_upstream']);

export function createPerformanceTraceId(): string { return crypto.randomUUID().replaceAll('-', ''); }
export function apiResource(path: string): string {
  const clean = path.split('?')[0];
  if (/^\/v1\/learners\/[^/]+\/workspace-notes(?:\/|$)/.test(clean)) return 'notes';
  if (clean.startsWith('/v1/account')) return 'account';
  if (/^\/v1\/(sessions|generations)(?:\/|$)/.test(clean)) return 'chat';
  if (/^\/v1\/(assistant|browser-devices)(?:\/|$)/.test(clean)) return 'browser';
  return 'other';
}

export function recordApiTiming(path: string, startedAt: number, status: number,
  responseHeaders?: Headers, method = 'GET', outcome = status >= 400 || status === 0 ? 'failed' : 'completed') {
  if (typeof window === 'undefined') return;
  const serverTimingMs: Record<string, number> = {};
  for (const entry of (responseHeaders?.get('server-timing') || '').split(',')) {
    const match = entry.trim().match(/^([a-z_]+);dur=(\d+(?:\.\d+)?)/);
    if (match && stages.has(match[1]) && Number.isFinite(Number(match[2]))) serverTimingMs[match[1]] = Number(match[2]);
  }
  const incoming = responseHeaders?.get('x-openlearn-trace-id');
  samples.push({ resource: apiResource(path), durationMs: Math.round(performance.now() - startedAt), status,
    startedAt: Math.round(startedAt), method, outcome,
    ...(incoming && /^[a-f0-9]{32}$/.test(incoming) ? { traceId: incoming } : {}), serverTimingMs });
  if (samples.length > 200) samples.shift();
}

export function beginGenerationTiming(key: string, origin: 'submission' | 'resume' = 'submission', traceId = createPerformanceTraceId()) {
  if (origin === 'submission' && generations.has(key)) return generations.get(key)!.traceId;
  if (generations.size >= 100) { const oldest = generations.keys().next().value!; generations.delete(oldest); pendingCommits.delete(oldest); }
  generations.set(key, { started: performance.now(), traceId, origin, received: false, committed: false });
  return traceId;
}
export function bindGenerationTiming(key: string, generationId: string, traceId?: unknown) {
  const timing = generations.get(key);
  if (!timing) return;
  if (typeof traceId === 'string' && /^[a-f0-9]{32}$/.test(traceId)) timing.traceId = traceId;
  generations.delete(key); generations.set(generationId, timing);
}
export function recordGenerationTiming(key: string, stage: GenerationTiming['stage']) {
  const timing = generations.get(key);
  if (!timing || typeof window === 'undefined') return;
  if (stage === 'first_text_received') { if (timing.received) return; timing.received = true; pendingCommits.add(key); }
  if (stage === 'first_text_committed') { if (!timing.received || timing.committed) return; timing.committed = true; pendingCommits.delete(key); }
  generationSamples.push({ stage, durationMs: Math.round(performance.now() - timing.started), traceId: timing.traceId, origin: timing.origin });
  if (generationSamples.length > 200) generationSamples.shift();
  // Keep completed entries until React commits the final (possibly only) chunk.
  if (stage === 'disconnected') { generations.delete(key); pendingCommits.delete(key); }
}
export function hasPendingGenerationCommit() { return pendingCommits.size > 0; }
export function clearPerformanceSamples() { samples.length = 0; generationSamples.length = 0; generations.clear(); pendingCommits.clear(); }
export function getApiPerformanceSnapshot() { return samples.map(sample => ({ ...sample, serverTimingMs: { ...sample.serverTimingMs } })); }
export function getGenerationPerformanceSnapshot() { return generationSamples.map(sample => ({ ...sample })); }
if (typeof window !== 'undefined') window.addEventListener('openlearn-account-changed', clearPerformanceSamples);
