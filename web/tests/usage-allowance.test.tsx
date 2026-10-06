import { describe, expect, it } from 'vitest';
import { parseUsageEventPage, usageActivityLabel, usagePercent, type Allowance } from '@/lib/usage-allowance';

function allowance(granted: number, used: number, held: number): Allowance {
  return {
    windowId: 'window-1', windowState: 'active', serverTime: 1, resetsAt: 18001,
    grantedMicrocredits: granted, usedMicrocredits: used, heldMicrocredits: held,
    availableMicrocredits: Math.max(0, granted - used - held), revision: 1,
    availability: 'available', reasonCode: null,
  };
}

describe('usage percentage presentation', () => {
  it('uses the server grant as the denominator and separates holds', () => {
    expect(usagePercent(allowance(70_000_000, 56_000_000, 7_000_000))).toMatchObject({
      used: 80, held: 10, available: 10, label: '80%',
    });
  });

  it('does not round fractional use up to true exhaustion', () => {
    expect(usagePercent(allowance(1_000_000, 4_000, 0))?.label).toBe('<1%');
    expect(usagePercent(allowance(1_000_000, 996_000, 0))?.label).toBe('99%');
    expect(usagePercent(allowance(1_000_000, 1_000_000, 0))?.label).toBe('100%');
  });

  it('rejects corrupt grant or balance snapshots', () => {
    expect(usagePercent(allowance(0, 0, 0))).toBeNull();
    expect(usagePercent(allowance(100, 90, 20))).toBeNull();
    const corrupted = allowance(100, 20, 10);
    corrupted.availableMicrocredits = 80;
    expect(usagePercent(corrupted)).toBeNull();
  });
});

describe('replayable usage events',()=>{
  it('accepts contiguous revisions and pages that have more events',()=>{
    const page={events:[{id:'evt-2',revision:2,kind:'settled',createdAt:2}],nextRevision:2,latestRevision:4,hasMore:true,resnapshotRequired:false};
    expect(parseUsageEventPage(page,1)?.nextRevision).toBe(2);
  });

  it('rejects a gap and accepts an explicit resnapshot request',()=>{
    const gap={events:[{id:'evt-3',revision:3,kind:'settled',createdAt:3}],nextRevision:3,latestRevision:3,hasMore:false,resnapshotRequired:false};
    expect(parseUsageEventPage(gap,1)).toBeNull();
    expect(parseUsageEventPage({events:[],nextRevision:4,latestRevision:4,hasMore:false,resnapshotRequired:true},1)?.resnapshotRequired).toBe(true);
  });
});

describe('recent usage activity',()=>{
  it('shows a reservation for pending-only work instead of zero spent',()=>{
    expect(usageActivityLabel({used:0,held:4_000_000,grant:100_000_000,status:'in_progress'})).toBe('4% reserved · In progress');
    expect(usageActivityLabel({used:2_000_000,held:4_000_000,grant:100_000_000,status:'in_progress'})).toBe('2% used · 4% reserved · In progress');
  });
});
