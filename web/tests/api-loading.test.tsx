import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiReadCache, readFreshness } from '@/lib/api-read-cache';
const transport = vi.hoisted(() => ({ identity: 'alice', fetch: vi.fn() }));
vi.mock('@/lib/account-session', () => ({
  ACCOUNT_CHANGED: 'openlearn-account-changed',
  sessionToken: async () => transport.identity,
  authenticatedFetch: (...args: unknown[]) => transport.fetch(...args),
}));
import { request } from '@/lib/api';
beforeEach(() => {
  transport.identity = 'alice';
  transport.fetch.mockReset().mockImplementation(async () => new Response('{"value":1}'));
  window.dispatchEvent(new Event('openlearn-account-changed'));
});
afterEach(() => vi.useRealTimers());
describe('initial data loading', () => {
  it('deduplicates parallel session reads but refetches live authority afterward', async () => {
    await Promise.all([request('/v1/sessions/one/snapshot'), request('/v1/sessions/one/snapshot')]);
    expect(transport.fetch).toHaveBeenCalledTimes(1);
    await request('/v1/sessions/one/snapshot');
    expect(transport.fetch).toHaveBeenCalledTimes(2);
  });
  it('reuses navigation summaries, expires them, and isolates returned objects', async () => {
    vi.useFakeTimers();
    const first = await request<{ value: number }>('/v1/courses');
    first.value = 99;
    expect(await request('/v1/courses')).toEqual({ value: 1 });
    expect(transport.fetch).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(15_001);
    await request('/v1/courses');
    expect(transport.fetch).toHaveBeenCalledTimes(2);
  });
  it('invalidates summaries after writes and never shares between accounts', async () => {
    await request('/v1/courses');
    await request('/v1/courses/one', { method: 'PATCH', body: '{}' });
    await request('/v1/courses');
    expect(transport.fetch).toHaveBeenCalledTimes(3);
    transport.identity = 'bob';
    await request('/v1/courses');
    expect(transport.fetch).toHaveBeenCalledTimes(4);
  });
  it('does not retain errors or bypass explicit reloads and cancellation ownership', async () => {
    transport.fetch.mockResolvedValueOnce(new Response('{"detail":"Unavailable"}', { status: 503 }));
    await expect(request('/v1/courses')).rejects.toThrow('Unavailable');
    await request('/v1/courses');
    await request('/v1/courses', { cache: 'no-store' });
    await request('/v1/courses', { signal: new AbortController().signal });
    expect(transport.fetch).toHaveBeenCalledTimes(4);
  });
  it('drops stale in-flight cache entries when invalidated during a write', async () => {
    const cache = new ApiReadCache();
    let finish!: (value: string) => void;
    const old = cache.read('courses', () => new Promise<string>(resolve => { finish = resolve; }), 15_000);
    await Promise.resolve();
    cache.clear();
    expect(await cache.read('courses', async () => 'updated', 15_000)).toBe('updated');
    finish('old'); await old;
    expect(await cache.read('courses', async () => 'wrong', 15_000)).toBe('updated');
  });
  it('does not retain balance, job, or session authority results', () => {
    for (const path of ['/v1/usage/allowance', '/v1/learning-jobs/job', '/v1/sessions/session', '/v1/sessions/session/snapshot', '/v1/sessions/session/journey']) {
      expect(readFreshness(path)).toBe(0);
    }
  });
});
