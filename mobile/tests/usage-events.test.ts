import assert from 'node:assert/strict';
import test from 'node:test';
import { parseUsageEventPage } from '../src/usage-events';

test('usage event page accepts contiguous owner feed revisions',()=>{
  const page={events:[{id:'evt-2',revision:2,kind:'settled',createdAt:2}],nextRevision:2,latestRevision:4,hasMore:true,resnapshotRequired:false};
  assert.equal(parseUsageEventPage(page,1)?.nextRevision,2);
});

test('usage event page rejects gaps and accepts explicit resnapshot requests',()=>{
  const gap={events:[{id:'evt-3',revision:3,kind:'settled',createdAt:3}],nextRevision:3,latestRevision:3,hasMore:false,resnapshotRequired:false};
  assert.equal(parseUsageEventPage(gap,1),null);
  const resnapshot={events:[],nextRevision:4,latestRevision:4,hasMore:false,resnapshotRequired:true};
  assert.equal(parseUsageEventPage(resnapshot,1)?.resnapshotRequired,true);
});
