import {afterEach,expect,it,vi} from 'vitest';
import {GenerationStream,GenerationConnectionError} from '@/lib/generation-stream';
const {fetch,request}=vi.hoisted(()=>({fetch:vi.fn(),request:vi.fn()}));
vi.mock('@/lib/account-session',()=>({authenticatedFetch:fetch,ACCOUNT_CHANGED:'openlearn-account-changed',sessionToken:async()=>null}));
vi.mock('@/lib/api',()=>({apiBaseUrl:()=>'',request}));
afterEach(()=>{vi.useRealTimers();vi.resetAllMocks();});
it('retains terminal completion and sequence when the stream closes', async()=>{
  const descriptor={id:'g',sessionId:'s',mode:'ask' as const,status:'streaming',sequence:0,provider:'test',model:'test'};
  fetch.mockResolvedValue(new Response('data: '+JSON.stringify({generationId:'g',sequence:1,type:'generation.completed',data:{}})+'\n\n'));
  const stream=new GenerationStream();
  await stream.resume(descriptor,{onEvent:vi.fn()});
  expect(stream.descriptor?.status).toBe('completed');
  expect(stream.descriptor?.sequence).toBe(1);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it.each(['disconnected','empty-stream'])('bounds reconnection for %s without claiming generation failure',async mode=>{
  vi.useFakeTimers();
  const descriptor={id:'g',sessionId:'s',mode:'ask' as const,status:'streaming',sequence:0,provider:'test',model:'test'};
  request.mockResolvedValue(descriptor);
  if(mode==='disconnected')fetch.mockRejectedValue(new TypeError('Network lost'));
  else fetch.mockImplementation(async()=>new Response(new ReadableStream({start(controller){controller.close();}})));
  const callback=vi.fn();const stream=new GenerationStream();
  const outcome=stream.resume(descriptor,{onEvent:callback}).catch(error=>error);
  await vi.runAllTimersAsync();
  expect(await outcome).toBeInstanceOf(GenerationConnectionError);
  expect(fetch).toHaveBeenCalledTimes(6);
  expect(callback).not.toHaveBeenCalled();
  expect(stream.descriptor?.status).toBe('streaming');
});
