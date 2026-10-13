import {afterEach,describe,expect,it,vi} from 'vitest';
import {proxyHostedApi} from '@/lib/hosted-api-proxy';
import {apiBaseUrl} from '@/lib/api';
import {serviceConnectionMessage} from '@/lib/product-runtime';
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'openlearn-account-changed',sessionToken:async()=>undefined,authenticatedFetch:vi.fn()}));
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();delete (window as Window & {formaDesktop?:unknown}).formaDesktop;});

describe('product service boundaries',()=>{
  it('only proxies the fixed local API for a development loopback preview',async()=>{
    vi.stubEnv('NODE_ENV','development');vi.stubEnv('OPENLEARN_API_ORIGIN','');
    const fetch=vi.fn(async(_input:RequestInfo|URL)=>new Response('{"ownerId":"local"}',{headers:{'content-type':'application/json'}}));vi.stubGlobal('fetch',fetch);
    expect((await proxyHostedApi(new Request('http://127.0.0.1:3001/v1/account'),['account'])).status).toBe(200);
    expect(String(fetch.mock.calls[0][0])).toBe('http://127.0.0.1:8000/v1/account');
    vi.stubEnv('NODE_ENV','production');fetch.mockClear();
    expect((await proxyHostedApi(new Request('http://127.0.0.1:3001/v1/account'),['account'])).status).toBe(503);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('defaults to same-origin on hosted web and honors the desktop bridge',()=>{
    vi.stubEnv('NEXT_PUBLIC_LEARNING_API_URL','');
    vi.stubGlobal('window',{location:{hostname:'open-learn-eta.vercel.app'}});
    expect(apiBaseUrl()).toBe('');
    expect(serviceConnectionMessage()).not.toContain('local');
    vi.stubGlobal('window',{location:{hostname:'localhost'},formaDesktop:{apiBaseUrl:'https://app.example/'}});
    expect(apiBaseUrl()).toBe('https://app.example');
  });
  it('does not send hosted traffic to an accidentally configured loopback URL',()=>{
    vi.stubEnv('NEXT_PUBLIC_LEARNING_API_URL','http://127.0.0.1:8000');
    vi.stubGlobal('window',{location:{hostname:'open-learn-eta.vercel.app'}});
    expect(apiBaseUrl()).toBe('');
    vi.stubGlobal('window',{location:{hostname:'localhost'}});
    expect(apiBaseUrl()).toBe('http://127.0.0.1:8000');
  });
  it('returns a clear 503 without contacting a service when configuration is absent',async()=>{
    vi.stubEnv('OPENLEARN_API_ORIGIN','');const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
    const result=await proxyHostedApi(new Request('https://app.example/v1/account'),['account']);
    expect(result.status).toBe(503);expect(fetch).not.toHaveBeenCalled();
    expect(await result.text()).not.toContain('start-local');
  });
  it('forwards account authentication and streams responses without local identity headers',async()=>{
    vi.stubEnv('OPENLEARN_API_ORIGIN','https://api.example');
    const fetch=vi.fn(async(_input: RequestInfo | URL,_init?: RequestInit)=>new Response('event: ready\ndata: {}\n\n',{headers:{'content-type':'text/event-stream'}}));vi.stubGlobal('fetch',fetch);
    const result=await proxyHostedApi(new Request('https://app.example/v1/events?cursor=1',{headers:{Authorization:'Bearer learner-token','X-Dev-Learner-Id':'other','X-Forma-Desktop-Token':'local-secret'}}),['events']);
    expect(String(fetch.mock.calls[0][0])).toBe('https://api.example/v1/events?cursor=1');
    const options=fetch.mock.calls[0][1] as RequestInit;const headers=new Headers(options.headers);
    expect(headers.get('authorization')).toBe('Bearer learner-token');expect(headers.has('x-dev-learner-id')).toBe(false);expect(headers.has('x-forma-desktop-token')).toBe(false);
    expect(result.headers.get('cache-control')).toContain('no-store');expect(result.headers.get('server-timing')).toMatch(/proxy_upstream;dur=\d+(?:\.\d+)?/);expect(await result.text()).toContain('event: ready');
  });
  it('rejects unsafe origins and redirects',async()=>{
    const fetch=vi.fn(async(_input: RequestInfo | URL,_init?: RequestInit)=>new Response(null,{status:302,headers:{location:'https://other.example'}}));vi.stubGlobal('fetch',fetch);
    vi.stubEnv('OPENLEARN_API_ORIGIN','http://localhost:8000');
    expect((await proxyHostedApi(new Request('https://app.example/v1/account'),['account'])).status).toBe(503);expect(fetch).not.toHaveBeenCalled();
    vi.stubEnv('OPENLEARN_API_ORIGIN','https://api.example');
    expect((await proxyHostedApi(new Request('https://app.example/v1/account'),['account'])).status).toBe(503);
  });
});
