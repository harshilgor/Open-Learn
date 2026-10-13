import { describe, expect, it } from 'vitest';
import { layoutDay, occursOnDate, shiftMonth } from '@/lib/calendar-layout';
import { wallInstant, type CalendarEvent } from '@/lib/calendar-client';

const event = (id: string, start: string, end: string): CalendarEvent => ({ id, calendarId: 'cal', title: id, type: 'study', revision: 1, busy: true, temporal: { mode: 'timed', timezone: 'UTC', start, end } });
describe('calendar time layout', () => {
  it('assigns simultaneous events separate lanes and reuses lanes after a group ends', () => {
    const result = layoutDay([event('a', '2026-10-09T09:00:00Z', '2026-10-09T10:00:00Z'), event('b', '2026-10-09T09:30:00Z', '2026-10-09T10:30:00Z'), event('c', '2026-10-09T11:00:00Z', '2026-10-09T12:00:00Z')], '2026-10-09', 'UTC');
    expect(result.map(r => [r.lane, r.lanes])).toEqual([[0, 2], [1, 2], [0, 1]]);
  });
  it('keeps overnight events visible on both days and respects exclusive all-day end', () => {
    const overnight = event('night', '2026-10-09T23:00:00Z', '2026-10-10T01:00:00Z');
    expect(occursOnDate(overnight, '2026-10-10', 'UTC')).toBe(true);
    expect(layoutDay([overnight], '2026-10-10', 'UTC')[0].start).toBe(0);
    const allDay = { ...overnight, temporal: { mode: 'all_day' as const, timezone: 'UTC', startDate: '2026-10-09', endDate: '2026-10-10' } };
    expect(occursOnDate(allDay, '2026-10-10', 'UTC')).toBe(false);
  });
  it('navigates month boundaries and rejects DST gaps', () => {
    expect(shiftMonth('2026-01-31', 1)).toBe('2026-02-28');
    expect(wallInstant('2026-10-09T09:00', 'America/Los_Angeles')).toBe('2026-10-09T16:00:00.000Z');
    expect(() => wallInstant('2026-03-08T02:30', 'America/Los_Angeles')).toThrow('does not exist');
  });
});
