import { UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { rememberCommand, forgetCommand, markConflict } from './offline-commands';
import { supabaseAccount, supabaseManager } from './supabase-account';

let manager: UserManager | undefined;
let account: { token: string; ownerId: string } | undefined;
export const ACCOUNT_CHANGED = 'openlearn-account-changed';
if (typeof window !== 'undefined') window.addEventListener(ACCOUNT_CHANGED, () => { account = undefined; });

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
  const token = await sessionToken();
  const headers = new Headers(init.headers);
  let target = input;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
    headers.delete('X-Dev-Learner-Id');
    if (!account || account.token !== token) {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token)))).map(byte => byte.toString(16).padStart(2, '0')).join('');
      const saved = sessionStorage.getItem(`openlearn-account-owner:${hash}`);
      if (saved) account = { token, ownerId: saved };
      const endpoint = new URL('/v1/account', new URL(input, window.location.origin));
      const identityHeaders = new Headers(headers);
      identityHeaders.delete('Content-Type');
      const response = await fetch(endpoint, { headers: identityHeaders, signal: init.signal }).catch(error => {
        if (!account || account.token !== token) throw error;
        return undefined;
      });
      if (response) {
      if (!response.ok) return response;
      const identity = await response.json() as { ownerId: string };
      account = { token, ownerId: identity.ownerId };
      sessionStorage.setItem(`openlearn-account-owner:${hash}`, identity.ownerId);
      }
    }
    // Existing UI defaults address the local profile. Explicit foreign IDs are
    // never rewritten and are rejected by the backend ownership check.
    if (!account) throw new Error('Sign in online before using this account offline.');
    target = input.replace('/v1/learners/local/', `/v1/learners/${encodeURIComponent(account.ownerId)}/`);
  }
  const owner = account?.ownerId || headers.get('X-Dev-Learner-Id') || 'local';
  const pending = typeof window !== 'undefined' ? rememberCommand(owner, target, { ...init, headers }) : undefined;
  if (pending?.commandKey) headers.set('Idempotency-Key', pending.commandKey);
  const response = await fetch(target, { ...init, headers });
  if (pending && response.ok) forgetCommand(owner, pending.id);
  else if (pending && response.status === 409) markConflict(owner, pending.id);
  if (response.status === 401) {
    account = undefined;
    window.dispatchEvent(new Event(ACCOUNT_CHANGED));
  }
  return response;
}
