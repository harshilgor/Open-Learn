import assert from 'node:assert/strict';
import test from 'node:test';
import { usedPercentageLabel, usageActivityLabel } from '../src/usage-allowance';

test('usage percentage rounds to nearest whole and caps below full exhaustion',()=>{
  assert.equal(usedPercentageLabel(0),'0%');
  assert.equal(usedPercentageLabel(0.4),'Less than 1%');
  assert.equal(usedPercentageLabel(0.6),'1%');
  assert.equal(usedPercentageLabel(99.6),'99%');
  assert.equal(usedPercentageLabel(100),'100%');
});

test('pending-only activity displays reserved allowance instead of zero spent',()=>{
  assert.equal(usageActivityLabel({used:0,held:4_000_000,grant:100_000_000,status:'in_progress'}),'4% reserved · In progress');
  assert.equal(usageActivityLabel({used:2_000_000,held:4_000_000,grant:100_000_000,status:'in_progress'}),'2% used · 4% reserved · In progress');
});
