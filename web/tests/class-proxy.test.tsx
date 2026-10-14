import {afterEach,expect,it,vi} from 'vitest';
import {proxyHostedApi} from '@/lib/hosted-api-proxy';
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('preserves scoped capture and immutable chunk headers through the development proxy',async()=>{
  vi.stubEnv('NODE_ENV','development');vi.stubEnv('OPENLEARN_API_ORIGIN','http://127.0.0.1:8795');
  const fetch=vi.fn(async()=>new Response('{}',{status:200,headers:{'Content-Type':'application/json'}}));vi.stubGlobal('fetch',fetch);
  await proxyHostedApi(new Request('http://127.0.0.1:5191/v1/recordings/chunks/0',{method:'PUT',headers:{'X-Capture-Capability':'scoped-test-capability','X-Capture-Run':'run-one','X-Capture-Epoch':'2','X-Chunk-Start-Ms':'1000','X-Chunk-End-Ms':'2000','X-Chunk-Sha256':'checksum','X-Unapproved-Secret':'never-forward','X-Dev-Learner-Id':'local'},body:'audio'}),['recordings','chunks','0']);
  const headers=(fetch.mock.calls[0] as unknown as [URL,RequestInit])[1].headers as Headers;
  expect(headers.get('x-capture-capability')).toBe('scoped-test-capability');expect(headers.get('x-capture-run')).toBe('run-one');expect(headers.get('x-chunk-start-ms')).toBe('1000');expect(headers.get('x-unapproved-secret')).toBeNull();expect(headers.get('x-dev-learner-id')).toBe('local');
});
it('rejects a loopback upstream in production',async()=>{
  vi.stubEnv('NODE_ENV','production');vi.stubEnv('OPENLEARN_API_ORIGIN','http://127.0.0.1:8795');
  const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
  const response=await proxyHostedApi(new Request('https://openlearn.example/v1/account'),['account']);
  expect(response.status).toBe(503);expect(fetch).not.toHaveBeenCalled();
});
