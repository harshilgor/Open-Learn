import { UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { rememberCommand, forgetCommand, markConflict } from './offline-commands';
import { supabaseAccount, supabaseManager } from './supabase-account';
import { recordApiTiming } from './api-performance';

let manager: UserManager | undefined;
let account: { token: string; ownerId: string } | undefined;
let identityEpoch = 0;
let identityRequest: { token: string; origin: string; promise: Promise<Response | undefined> } | undefined;
export const ACCOUNT_CHANGED = 'openlearn-account-changed';
if (typeof window !== 'undefined') window.addEventListener(ACCOUNT_CHANGED, () => {
  account = undefined;
  identityRequest = undefined;
  identityEpoch++;
});

// A cancelled caller must not cancel authentication for every other caller.
function withCallerSignal<T>(promise: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

function resolveIdentity(token: string, input: string, headers: Headers): Promise<Response | undefined> {
  const endpoint = new URL('/v1/account', new URL(input, window.location.origin));
  if (identityRequest?.token === token && identityRequest.origin === endpoint.origin) return identityRequest.promise;
  const epoch = identityEpoch;
  const promise = (async () => {
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token)))).map(byte => byte.toString(16).padStart(2, '0')).join('');
    let saved: string | null = null;
    try { saved = sessionStorage.getItem(`openlearn-account-owner:${hash}`); } catch { /* Storage is optional. */ }
    const identityHeaders = new Headers(headers);
    identityHeaders.delete('Content-Type');
    const startedAt = performance.now();
    const response = await fetch(endpoint, { headers: identityHeaders }).catch(error => {
      recordApiTiming('/v1/account', startedAt, 0);
      if (!saved) throw error;
      return undefined;
    });
    if (response) recordApiTiming('/v1/account', startedAt, response.status);
    if (epoch !== identityEpoch) throw new Error('The account changed while loading. Please retry.');
    if (response && !response.ok) return response;
    const ownerId = response ? (await response.clone().json() as { ownerId: string }).ownerId : saved;
    if (epoch !== identityEpoch) throw new Error('The account changed while loading. Please retry.');
    if (!ownerId || typeof ownerId !== 'string') throw new Error('The account identity could not be loaded.');
    account = { token, ownerId };
    try { sessionStorage.setItem(`openlearn-account-owner:${hash}`, ownerId); } catch { /* Storage is optional. */ }
    return response;
  })();
  const pending = { token, origin: endpoint.origin, promise };
  identityRequest = pending;
  void promise.finally(() => { if (identityRequest === pending) identityRequest = undefined; }).catch(() => undefined);
  return promise;
}

export function accountManager(): UserManager | typeof supabaseManager | undefined {
  if (typeof window === 'undefined') return undefined;
  if (supabaseAccount()) return supabaseManager;
  const authority = process.env.NEXT_PUBLIC_OPENLEARN_OIDC_ISSUER;
  const client_id = process.env.NEXT_PUBLIC_OPENLEARN_OIDC_CLIENT_ID;
  if (!authority || !client_id) return undefined;
  manager ??= new UserManager({ authority, client_id,
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code', scope: process.env.NEXT_PUBLIC_OPENLEARN_OIDC_SCOPE || 'openid profile email',
    extraQueryParams: process.env.NEXT_PUBLIC_OPENLEARN_OIDC_AUDIENCE ? { audience: process.env.NEXT_PUBLIC_OPENLEARN_OIDC_AUDIENCE } : undefined,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
  });
  return manager;
}

export async function sessionToken(): Promise<string | undefined> {
  if (typeof window === 'undefined') return undefined;
  const desktop = (window as Window & { formaDesktop?: { credentials?: { get: (key: string) => Promise<string | null> } } }).formaDesktop;
  const grant = await desktop?.credentials?.get('openlearn-device-grant') || sessionStorage.getItem('openlearn-device-grant');
  if (grant) return grant;
  const user = await accountManager()?.getUser();
  if (user && !user.expired) return user.access_token;
  if (user?.expired) throw new Error('Your account session expired. Sign in again; pending changes are preserved.');
  return undefined;
}

export async function signIn() {
  const client = accountManager();
  if (!client) throw new Error('An account provider has not been configured for this installation.');
  await client.signinRedirect();
}

export async function signOut() {
  sessionStorage.removeItem('openlearn-device-grant');
  const desktop = (window as Window & { formaDesktop?: { credentials?: { delete: (key: string) => Promise<void> } } }).formaDesktop;
  await desktop?.credentials?.delete('openlearn-device-grant');
  await accountManager()?.removeUser();
  account = undefined;
  window.dispatchEvent(new Event(ACCOUNT_CHANGED));
}

export async function useDeviceGrant(token: string) {
  if (!/^oldv_[A-Za-z0-9_-]{40,}$/.test(token)) throw new Error('Enter a valid device grant.');
  const desktop = (window as Window & { formaDesktop?: { credentials?: { set: (key: string, value: string) => Promise<void> } } }).formaDesktop;
  if (desktop?.credentials) await desktop.credentials.set('openlearn-device-grant', token);
  else sessionStorage.setItem('openlearn-device-grant', token);
  account = undefined;
  window.dispatchEvent(new Event(ACCOUNT_CHANGED));
}

/** All API paths, binary downloads and streams share this identity boundary. */
export async function authenticatedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const epoch = identityEpoch;
  const token = await sessionToken();
  if (epoch !== identityEpoch) throw new Error('The account changed while loading. Please retry.');
  const headers = new Headers(init.headers);
  let target = input;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
    headers.delete('X-Dev-Learner-Id');
    if (!account || account.token !== token) {
      const response = await withCallerSignal(resolveIdentity(token, input, headers), init.signal);
      if (response && (!response.ok || new URL(input, window.location.origin).pathname === '/v1/account')) return response.clone();
    }
    // Existing UI defaults address the local profile. Explicit foreign IDs are
    // never rewritten and are rejected by the backend ownership check.
    if (epoch !== identityEpoch || account?.token !== token) throw new Error('Sign in online before using this account offline.');
    target = input.replace('/v1/learners/local/', `/v1/learners/${encodeURIComponent(account.ownerId)}/`);
  }
  const owner = account?.ownerId || headers.get('X-Dev-Learner-Id') || 'local';
  const pending = typeof window !== 'undefined' ? rememberCommand(owner, target, { ...init, headers }) : undefined;
  if (pending?.commandKey) headers.set('Idempotency-Key', pending.commandKey);
  const response = await fetch(target, { ...init, headers });
  if (pending && response.ok) forgetCommand(owner, pending.id);
  else if (pending && response.status === 409) markConflict(owner, pending.id);
  if (response.status === 401 && token) {
    account = undefined;
    window.dispatchEvent(new Event(ACCOUNT_CHANGED));
  }
  return response;
}
