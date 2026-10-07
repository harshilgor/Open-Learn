type ApiTiming = { resource: string; durationMs: number; status: number; startedAt: number };
const samples: ApiTiming[] = [];

// No tokens, query strings, learner IDs, request bodies, or response content.
export function recordApiTiming(path: string, startedAt: number, status: number) {
  if (typeof window === 'undefined') return;
  const segments = path.split('?')[0].split('/').filter(Boolean);
  const resource = segments[1] === 'learners' ? `learners/${segments[3] || 'profile'}` : segments[1] || 'api';
  samples.push({ resource, durationMs: Math.round(performance.now() - startedAt), status, startedAt: Math.round(startedAt) });
  if (samples.length > 100) samples.shift();
}

export function getApiPerformanceSnapshot() { return samples.map(sample => ({ ...sample })); }
