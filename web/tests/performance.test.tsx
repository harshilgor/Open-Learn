import { afterEach, expect, it } from 'vitest';
import { beginGenerationTiming, bindGenerationTiming, clearPerformanceSamples, getApiPerformanceSnapshot,
  getGenerationPerformanceSnapshot, recordApiTiming, recordGenerationTiming } from '@/lib/api-performance';
import { proxyHostedApi } from '@/lib/hosted-api-proxy';
import { vi } from 'vitest';
import { releaseRouting } from '@/lib/release-routing';
import { createHash } from 'node:crypto';

afterEach(() => { clearPerformanceSamples(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it('fingerprints the actual public or proxy API selection without exposing the origin', () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_LEARNING_API_URL', 'https://old-api.example');
  vi.stubEnv('OPENLEARN_API_ORIGIN', 'https://new-api.example');
  const direct = releaseRouting('https://frontend.example/api/release');
  expect(direct.apiOriginFingerprint).toBe(createHash('sha256').update('https://old-api.example').digest('hex'));
  expect(JSON.stringify(direct)).not.toContain('old-api.example');
  vi.stubEnv('NEXT_PUBLIC_LEARNING_API_URL', '');
  expect(releaseRouting('https://frontend.example/api/release').apiOriginFingerprint)
    .toBe(createHash('sha256').update('https://new-api.example').digest('hex'));
});

it('retains bounded diagnostics and strips path IDs, unknown timing names, and queries', () => {
  for (let index = 0; index < 250; index++) recordApiTiming('/v1/learners/private/workspace-notes/note-secret?q=secret', performance.now(), 503,
    new Headers({ 'server-timing': 'database_query;dur=4.2, private_identity;dur=7', 'x-openlearn-trace-id': 'a'.repeat(32) }), 'PATCH');
  const samples = getApiPerformanceSnapshot();
  expect(samples).toHaveLength(200);
  expect(samples[0].serverTimingMs).toEqual({ database_query: 4.2 });
  expect(samples[0].outcome).toBe('failed');
  expect(JSON.stringify(samples)).not.toMatch(/private|note-secret|q=secret/);
});

it('counts first nonempty text and first React commit once and isolates resumed work', () => {
  beginGenerationTiming('client-private', 'submission', 'b'.repeat(32));
  bindGenerationTiming('client-private', 'generation-private');
  recordGenerationTiming('generation-private', 'first_text_committed');
  recordGenerationTiming('generation-private', 'first_text_received');
  recordGenerationTiming('generation-private', 'first_text_received');
  recordGenerationTiming('generation-private', 'completed');
  recordGenerationTiming('generation-private', 'first_text_committed');
  recordGenerationTiming('generation-private', 'first_text_committed');
  beginGenerationTiming('resume-private', 'resume');
  recordGenerationTiming('resume-private', 'first_text_received');
  const samples = getGenerationPerformanceSnapshot();
  expect(samples.map(value => value.stage)).toEqual(['first_text_received', 'completed', 'first_text_committed', 'first_text_received']);
  expect(samples.at(-1)?.origin).toBe('resume');
  expect(JSON.stringify(samples)).not.toContain('private');
  window.dispatchEvent(new Event('openlearn-account-changed'));
  expect(getGenerationPerformanceSnapshot()).toEqual([]);
});

it('preserves trace IDs and timing through the streaming proxy without buffering', async () => {
  vi.stubEnv('OPENLEARN_API_ORIGIN', 'https://api.example');
  const fetch = vi.fn(async () => new Response('data: {}\n\n', { headers: {
    'x-openlearn-trace-id': 'c'.repeat(32), 'server-timing': 'api_headers;dur=2', 'content-type': 'text/event-stream',
  } }));
  vi.stubGlobal('fetch', fetch);
  const response = await proxyHostedApi(new Request('https://app.example/v1/generations/id/events', {
    headers: { 'x-openlearn-trace-id': 'c'.repeat(32) },
  }), ['generations', 'id', 'events']);
  const options = fetch.mock.calls[0] as unknown as [unknown, RequestInit];
  expect(new Headers(options[1].headers).get('x-openlearn-trace-id')).toBe('c'.repeat(32));
  expect(response.headers.get('x-openlearn-trace-id')).toBe('c'.repeat(32));
  expect(response.headers.get('server-timing')).toContain('api_headers;dur=2');
  expect(await response.text()).toBe('data: {}\n\n');
});
