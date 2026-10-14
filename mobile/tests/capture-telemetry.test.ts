import {test} from 'node:test';
import assert from 'node:assert/strict';
import {batteryPercent,createBatteryReader,captureHeartbeat} from '../src/capture-telemetry';
import type {Recording} from '../src/protocol';
test('battery readings preserve zero and reject unsupported sentinel values',()=>{
  assert.equal(batteryPercent(0),0);assert.equal(batteryPercent(57.4),57);
  for(const value of [-1,101,NaN,Infinity,null,undefined,'50'])assert.equal(batteryPercent(value),null);
});
test('battery reads are deduplicated, cached and tolerate older native builds',async()=>{
  let clock=0,calls=0;const read=createBatteryReader(async()=>{calls++;return 62;},()=>clock);
  assert.deepEqual(await Promise.all([read(),read()]),[62,62]);assert.equal(calls,1);
  clock=29999;assert.equal(await read(),62);assert.equal(calls,1);
  clock=30001;await read();assert.equal(calls,2);
  assert.equal(await createBatteryReader(async()=>{throw Error('Unavailable');})(),null);
});
test('a stalled battery sensor does not block recording status',async()=>{
  const read=createBatteryReader(()=>new Promise(()=>{}),Date.now,5);assert.equal(await read(),null);
});
test('heartbeat reports paused progress, offline backlog and handoff offset',()=>{
  const record={durationMs:61000,paused:true,stopped:false,interrupted:false,segments:[{acknowledged:true},{}],classSetup:{startMs:120000,finalizeOnStop:false}} as Recording;
  assert.deepEqual(captureHeartbeat(record,0),{state:'paused',audioEndMs:181000,sealedChunkCount:2,backlog:1,batteryPercent:0,endClass:false});
  record.stopped=true;record.interrupted=true;assert.equal(captureHeartbeat(record,null).state,'interrupted');
});
