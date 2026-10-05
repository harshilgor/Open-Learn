import {afterEach,expect,it,vi} from 'vitest';
import {rememberCommand,pendingCommands} from '@/lib/offline-commands';
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();sessionStorage.clear();localStorage.clear();});
it('queues same-origin edits without requiring an absolute API URL',()=>{
  const saved=rememberCommand('alice','/v1/learners/alice/workspace-notes/note',{method:'PATCH',body:JSON.stringify({expectedRevision:1,body:'Retained edit'})});
  expect(saved?.ownerId).toBe('alice');expect(pendingCommands('alice')).toHaveLength(1);
});
it('verifies account identity and rewrites local aliases over same-origin transport',async()=>{
  vi.resetModules();vi.stubEnv('NEXT_PUBLIC_OPENLEARN_OIDC_ISSUER','');vi.stubEnv('NEXT_PUBLIC_OPENLEARN_OIDC_CLIENT_ID','');
  sessionStorage.setItem('openlearn-device-grant','oldv_fixture');
  const fetch=vi.fn(async(input: RequestInfo | URL)=>String(input).endsWith('/v1/account')?Response.json({ownerId:'alice'}):Response.json({notes:[]}));vi.stubGlobal('fetch',fetch);
  const {authenticatedFetch}=await import('@/lib/account-session');
  const response=await authenticatedFetch('/v1/learners/local/workspace-notes');
  expect(response.ok).toBe(true);
  expect(String(fetch.mock.calls[0][0])).toBe(new URL('/v1/account',window.location.origin).href);
  expect(String(fetch.mock.calls[1][0])).toBe('/v1/learners/alice/workspace-notes');
});


it('does not announce an account change for an already signed-out request', async () => {
  const { authenticatedFetch, ACCOUNT_CHANGED } = await import('@/lib/account-session');
  const listener = vi.fn();
  window.addEventListener(ACCOUNT_CHANGED, listener);
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })));
  await authenticatedFetch('/v1/buddies');
  expect(listener).not.toHaveBeenCalled();
  window.removeEventListener(ACCOUNT_CHANGED, listener);
});
