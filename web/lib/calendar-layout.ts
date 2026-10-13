import { dateKey, wallInstant, type CalendarEvent } from './calendar-client';

export function occursOnDate(event: CalendarEvent, day: string, zone: string) {
  const t = event.temporal;
  if (t.mode === 'all_day') return !!t.startDate && !!t.endDate && t.startDate <= day && day < t.endDate;
  if (t.mode === 'deadline') return (t.dueDate || dateKey(new Date(t.dueAt!), zone)) === day;
  const start = Date.parse(wallInstant(`${day}T00:00`, zone));
  const next = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const end = Date.parse(wallInstant(`${next}T00:00`, zone));
  return Date.parse(t.start!) < end && Date.parse(t.end!) > start;
}

function wallMinutes(value: string, zone: string) {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(value));
  return Number(parts.find(p => p.type === 'hour')?.value) * 60 + Number(parts.find(p => p.type === 'minute')?.value);
}

export function layoutDay(events: CalendarEvent[], day: string, zone: string) {
  const sorted = events.filter(e => e.temporal.mode === 'timed' && occursOnDate(e, day, zone)).map(event => ({ event, start: dateKey(new Date(event.temporal.start!), zone) < day ? 0 : wallMinutes(event.temporal.start!, zone), end: dateKey(new Date(event.temporal.end!), zone) > day ? 1440 : wallMinutes(event.temporal.end!, zone), lane: 0, lanes: 1 })).sort((a, b) => a.start - b.start || b.end - a.end);
  let group: typeof sorted = [], ends: number[] = [], groupEnd = -1;
  function finish() { for (const item of group) item.lanes = ends.length; group = []; ends = []; }
  for (const item of sorted) {
    if (item.start >= groupEnd) finish();
    let lane = ends.findIndex(end => end <= item.start); if (lane < 0) lane = ends.length;
    ends[lane] = item.end; item.lane = lane; group.push(item); groupEnd = Math.max(groupEnd, item.end);
  }
  finish(); return sorted;
}

export function shiftMonth(day: string, count: number) {
  const date = new Date(`${day}T12:00:00Z`), original = date.getUTCDate();
  date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + count);
  const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate(); date.setUTCDate(Math.min(original, last));
  return date.toISOString().slice(0, 10);
}
