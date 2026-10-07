import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const auth = vi.hoisted(() => ({ token: 'alice-token' }));
vi.mock('@/lib/supabase-account', () => ({
  supabaseAccount: () => ({}),
  supabaseManager: { getUser: async () => ({ access_token: auth.token, expired: false }) },
}));
import { ACCOUNT_CHANGED, authenticatedFetch } from '@/lib/account-session';
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  auth.token = 'alice-token';
  sessionStorage.clear(); localStorage.clear();
  window.dispatchEvent(new Event(ACCOUNT_CHANGED));
  vi.stubGlobal('crypto', webcrypto);
});
afterEach(() => vi.unstubAllGlobals());
describe('shared account initialization', () => {
  it('resolves identity once for concurrent first-load calls and rewrites learner paths', async () => {
    const fetcher = vi.fn(async (input: string | URL) => new Response(JSON.stringify(
      String(input).endsWith('/v1/account') ? { ownerId: 'alice' } : { ok: true }
    )));
    vi.stubGlobal('fetch', fetcher);
    await Promise.all([
      authenticatedFetch('/v1/buddies'),
      authenticatedFetch('/v1/courses'),
      authenticatedFetch('/v1/learners/local/review'),
    ]);
    expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith('/v1/account'))).toHaveLength(1);
    expect(fetcher.mock.calls.some(([input]) => input === '/v1/learners/alice/review')).toBe(true);
  });
  it('does not let one aborted caller cancel shared authentication', async () => {
    const identity = deferred<Response>();
    const started = deferred<void>();
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      if (String(input).endsWith('/v1/account')) { started.resolve(); return identity.promise; }
      return Promise.resolve(new Response('{}'));
    }));
    const controller = new AbortController();
    const first = authenticatedFetch('/v1/courses', { signal: controller.signal });
    const rejection = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const second = authenticatedFetch('/v1/buddies');
    await started.promise;
    controller.abort();
    identity.resolve(new Response('{"ownerId":"alice"}'));
    await rejection;
    expect((await second).ok).toBe(true);
  });
  it('uses the initializing response for an explicit account read', async () => {
    const fetcher = vi.fn(async () => new Response('{"ownerId":"alice","displayName":"Alice"}'));
    vi.stubGlobal('fetch', fetcher);
    expect(await (await authenticatedFetch('/v1/account')).json()).toEqual({ ownerId: 'alice', displayName: 'Alice' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('gives each caller a readable identity error response and retries afterward', async () => {
    let denied = true;
    const fetcher = vi.fn(async (input: string | URL) => String(input).endsWith('/v1/account')
      ? new Response(denied ? '{"detail":"denied"}' : '{"ownerId":"alice"}', { status: denied ? 403 : 200 })
      : new Response('{}'));
    vi.stubGlobal('fetch', fetcher);
    const responses = await Promise.all([authenticatedFetch('/v1/courses'), authenticatedFetch('/v1/buddies')]);
    expect(await Promise.all(responses.map(response => response.json()))).toEqual([{ detail: 'denied' }, { detail: 'denied' }]);
    denied = false;
    expect((await authenticatedFetch('/v1/courses')).ok).toBe(true);
  });
  it('does not publish an old identity after switching accounts', async () => {
    const old = deferred<Response>();
    const started = deferred<void>();
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/account')) {
        if (new Headers(init?.headers).get('Authorization') === 'Bearer alice-token') { started.resolve(); return old.promise; }
        return Promise.resolve(new Response('{"ownerId":"bob"}'));
      }
      return Promise.resolve(new Response('{}'));
    }));
    const first = authenticatedFetch('/v1/courses');
    const rejection = expect(first).rejects.toThrow('account changed');
    await started.promise;
    auth.token = 'bob-token';
    window.dispatchEvent(new Event(ACCOUNT_CHANGED));
    expect((await authenticatedFetch('/v1/learners/local/review')).ok).toBe(true);
    old.resolve(new Response('{"ownerId":"alice"}'));
    await rejection;
    const fetcher = vi.mocked(fetch);
    expect(fetcher.mock.calls.some(([input]) => input === '/v1/learners/bob/review')).toBe(true);
    expect(fetcher.mock.calls.some(([input]) => input === '/v1/learners/alice/review')).toBe(false);
  });
});
