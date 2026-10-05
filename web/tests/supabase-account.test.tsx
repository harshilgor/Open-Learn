import { afterEach, expect, it, vi } from 'vitest';

const sdk = vi.hoisted(() => ({
  getSession: vi.fn(), exchangeCodeForSession: vi.fn(), signOut: vi.fn(), onAuthStateChange: vi.fn(),
}));
vi.mock('@supabase/supabase-js', () => ({ createClient: vi.fn(() => ({ auth: sdk })) }));
afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); vi.resetModules(); });

function configure() {
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'https://example.supabase.co');
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY', 'public-test-key');
}

it('uses refreshed Supabase session tokens with an expiry boundary', async () => {
  configure();
  sdk.getSession.mockResolvedValue({ data: { session: { access_token: 'token', expires_at: 1 } } });
  const { supabaseManager } = await import('@/lib/supabase-account');
  expect(await supabaseManager.getUser()).toEqual({ access_token: 'token', expired: true });
  sdk.getSession.mockResolvedValue({ data: { session: null } });
  expect(await supabaseManager.getUser()).toBeUndefined();
});

it('refuses a callback without a PKCE authorization code', async () => {
  configure();
  history.replaceState(null, '', '/auth/callback');
  const { supabaseManager } = await import('@/lib/supabase-account');
  await expect(supabaseManager.signinRedirectCallback()).rejects.toThrow('missing its code');
  expect(sdk.exchangeCodeForSession).not.toHaveBeenCalled();
});

it('exchanges the callback code and signs out only this device', async () => {
  configure();
  history.replaceState(null, '', '/auth/callback?code=one-time-code');
  sdk.exchangeCodeForSession.mockResolvedValue({ error: null });
  sdk.signOut.mockResolvedValue({ error: null });
  const { supabaseManager } = await import('@/lib/supabase-account');
  await supabaseManager.signinRedirectCallback();
  expect(sdk.exchangeCodeForSession).toHaveBeenCalledWith('one-time-code');
  await supabaseManager.removeUser();
  expect(sdk.signOut).toHaveBeenCalledWith({ scope: 'local' });
  history.replaceState(null, '', '/');
});


it('ignores repeated sign-in events and token refreshes for the same account', async () => {
  configure();
  vi.useFakeTimers();
  const listener = vi.fn();
  window.addEventListener('openlearn-account-changed', listener);
  const { supabaseAccount } = await import('@/lib/supabase-account');
  supabaseAccount();
  const notify = sdk.onAuthStateChange.mock.calls[0][0];
  notify('INITIAL_SESSION', { user: { id: 'alice' } });
  notify('SIGNED_IN', { user: { id: 'alice' } });
  notify('TOKEN_REFRESHED', { user: { id: 'alice' } });
  vi.runAllTimers();
  expect(listener).not.toHaveBeenCalled();
  notify('SIGNED_IN', { user: { id: 'bob' } });
  vi.runAllTimers();
  expect(listener).toHaveBeenCalledTimes(1);
  window.removeEventListener('openlearn-account-changed', listener);
  vi.useRealTimers();
});
