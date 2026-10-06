import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError,flushMessages,safeDeepLink,syncRecording,type Recording,type Transport,type PendingMessage} from '../src/protocol';
const make=():Recording=>({id:'rec_'+ 'a'.repeat(32),owner:'alice',title:'Physics',courseId:'course',startedAtMs:1000,directory:'file:///private',segments:[{sequence:0,uri:'file:///part.wav',startMs:0,endMs:30000}],durationMs:30000,interrupted:false,stopped:true,created:false,finalized:false});
function transport(calls:string[]):Transport{return {async json<T>(path:string){calls.push(path);return {} as T},async binary<T>(path:string){calls.push(path);return {} as T}}}
test('interrupted upload retries same identity and checksum before finalize',async()=>{
  const record=make(),calls:string[]=[];const api=transport(calls);let fail=true;
  api.binary=async<T>(path:string)=>{calls.push(path);if(fail){fail=false;throw Error('lost response')}return {} as T};
  const save=async()=>{};const bytes=async()=>new Uint8Array(100);const hash=async()=> 'a'.repeat(64);
  await assert.rejects(syncRecording(record,'alice',api,save,bytes,hash));assert.equal(record.created,true);assert.equal(record.segments[0].acknowledged,undefined);assert.equal(record.segments[0].sha256,'a'.repeat(64));
  await syncRecording(record,'alice',api,save,bytes,hash);assert.equal(record.finalized,true);
  assert.equal(calls.filter(c=>c.includes('/chunks/0')).length,2);assert.equal(calls.filter(c=>c.endsWith('/finalize')).length,1);
});
test('saved checksum rejects mutated audio',async()=>{const record=make();record.created=true;record.segments[0].sha256='old';await assert.rejects(syncRecording(record,'alice',transport([]),async()=>{},async()=>new Uint8Array(100),async()=> 'new'),/changed/)});
test('cross account recordings never dispatch',async()=>{const calls:string[]=[];await assert.rejects(syncRecording(make(),'bob',transport(calls),async()=>{},async()=>new Uint8Array(100),async()=> 'hash'));assert.deepEqual(calls,[])});
test('unsealed capture cannot finalize',async()=>{const record=make();record.stopped=false;const calls:string[]=[];await syncRecording(record,'alice',transport(calls),async()=>{},async()=>new Uint8Array(100),async()=> 'hash');assert.equal(calls.some(c=>c.endsWith('/finalize')),false)});
test('class recovery keeps setup identity, device fence and markers across lost upload responses',async()=>{
  const record=make();record.classSetup={deviceId:'phone-stable',captureEpoch:1};record.markersMs=[12000];
  const calls:string[]=[];const api=transport(calls);let failed=false;const bodies:Record<string,unknown>[]=[];const headers:Record<string,string>[]=[];
  api.json=async<T>(path:string,init?:RequestInit)=>{calls.push(path);bodies.push(JSON.parse(init?.body as string));return {} as T;};
  api.binary=async<T>(path:string,bytes:Uint8Array,supplied:Record<string,string>)=>{calls.push(path);headers.push(supplied);if(!failed){failed=true;throw Error('network lost');}return {} as T;};
  let durable='';const save=async(value:Recording)=>{durable=JSON.stringify(value);};
  await assert.rejects(syncRecording(record,'alice',api,save,async()=>new Uint8Array(100),async()=> 'a'.repeat(64)));
  const restored=JSON.parse(durable) as Recording;
  await syncRecording(restored,'alice',api,save,async()=>new Uint8Array(100),async()=> 'a'.repeat(64));
  assert.equal(calls.filter(path=>path==='/v1/class-sessions').length,1);
  assert.equal(bodies[0].deviceId,'phone-stable');assert.deepEqual(headers[0],headers[1]);
  assert.equal(headers[1]['X-Capture-Device'],'phone-stable');assert.equal(headers[1]['X-Capture-Epoch'],'1');
  assert.deepEqual(bodies.at(-1)?.markersMs,[12000]);assert.equal(restored.finalized,true);
});
test('missing segment fails finalization',async()=>{const record=make();record.segments[0].sequence=1;await assert.rejects(syncRecording(record,'alice',transport([]),async()=>{},async()=>new Uint8Array(100),async()=> 'hash'),/Missing/)});
test('oversized segments fail before binary upload',async()=>{const calls:string[]=[];await assert.rejects(syncRecording(make(),'alice',transport(calls),async()=>{},async()=>new Uint8Array(4*1024*1024+1),async()=> 'hash'));assert.equal(calls.some(c=>c.includes('/chunks/')),false)});
test('message retries retain stable key and body',async()=>{const queue:PendingMessage[]=[{key:'same-key',owner:'alice',body:{text:'Study'},state:'pending'}];let captured='';const api=transport([]);api.json=async<T>(path:string,init?:RequestInit)=>{captured=JSON.stringify(init);throw Error('offline')};await assert.rejects(flushMessages('alice',queue,api,async()=>{}));assert.equal(queue.length,1);assert.match(captured,/same-key/);api.json=async<T>()=>({} as T);await flushMessages('alice',queue,api,async()=>{});assert.equal(queue.length,0)});
test('owner isolation and revision conflict retain reviewable messages',async()=>{const queue:PendingMessage[]=[{key:'foreign',owner:'bob',body:{},state:'pending'},{key:'mine',owner:'alice',body:{},state:'pending'}];const calls:string[]=[];const api=transport(calls);api.json=async<T>()=>{throw new ApiError(409,'stale')};await flushMessages('alice',queue,api,async()=>{});assert.equal(queue[0].state,'pending');assert.equal(queue[1].state,'conflict')});
test('notification links accept only conversation references',()=>{assert.deepEqual(safeDeepLink('/s/session?task=task'),{session:'session',task:'task'});assert.deepEqual(safeDeepLink('openlearn://s/session'),{session:'session',task:undefined});for(const url of ['https://evil.example','javascript:alert(1)','/s/../../account','/s/a?token=secret'])assert.equal(safeDeepLink(url),null)});
