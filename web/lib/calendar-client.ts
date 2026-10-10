import { request } from './api';

export type CalendarTemporal = { mode: 'timed' | 'all_day' | 'deadline'; timezone: string; start?: string | null; end?: string | null; startDate?: string | null; endDate?: string | null; dueAt?: string | null; dueDate?: string | null };
export type CalendarEvent = { id: string; eventId?: string; calendarId: string; title: string; type: string; temporal: CalendarTemporal; description?: string; location?: string; url?: string; courseId?: string | null; recurrence?: string | null; busy: boolean; revision: number; occurrenceKey?: string; canEdit?: boolean; sourceType?: string; status?: string; sortAt?: number; reminderMinutes?: number[] };
export type CalendarPermission = { revision: number; read: 'none' | 'busy_only' | 'details'; edit: 'ask' | 'allow' };
export type StudentCalendar = { id: string; title: string; source: string; color: string; canEdit: boolean; permission: CalendarPermission };
export type CalendarFeed = { items: CalendarEvent[]; nextCursor: string | null; snapshotRevision: string; generatedAt: number; partial: boolean };
export type CalendarOperation = { id: string; status: string; undoUntil?: number; results: { after: CalendarEvent }[] };
export const CALENDAR_CHANGED = 'openlearn-calendar-changed';
export const calendarApi = {
  calendars: (signal?: AbortSignal) => request<{ items: StudentCalendar[] }>('/v1/calendar/calendars', { signal }),
  feed: (from: string, to: string, timezone: string, signal?: AbortSignal, cursor?: string) => request<CalendarFeed>(`/v1/calendar/occurrences?${new URLSearchParams({ from, to, timezone, ...(cursor ? { cursor } : {}) })}`, { signal }),
  event: (id: string) => request<CalendarEvent>(`/v1/calendar/events/${encodeURIComponent(id)}`),
  save: (event: Omit<CalendarEvent, 'id' | 'revision'>, key: string, existing?: CalendarEvent, scope = 'series') => request<CalendarOperation>(`/v1/calendar/events${existing ? `/${encodeURIComponent(existing.eventId || existing.id)}` : ''}`, { method: existing ? 'PATCH' : 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(existing ? { expectedRevision: existing.revision, event, scope, occurrenceKey: existing.occurrenceKey } : event) }),
  cancel: (event: CalendarEvent, key: string, scope: string) => request<CalendarOperation>(`/v1/calendar/events/${encodeURIComponent(event.eventId || event.id)}/cancel`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ expectedRevision: event.revision, scope, occurrenceKey: event.occurrenceKey }) }),
  permission: (calendar: StudentCalendar, read: CalendarPermission['read'], edit: CalendarPermission['edit']) => request<CalendarPermission>(`/v1/calendar/permissions/${encodeURIComponent(calendar.id)}`, { method: 'PUT', body: JSON.stringify({ expectedRevision: calendar.permission.revision, read, edit }) }),
  undo: (id: string, key: string) => request(`/v1/calendar/operations/${encodeURIComponent(id)}/undo`, { method: 'POST', headers: { 'Idempotency-Key': key } }),
};

export function dateKey(date: Date, zone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
  const value = (key: string) => parts.find(part => part.type === key)?.value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}

/** Convert a wall-time input to an instant in an explicit IANA zone, reject DST gaps. */
export function wallInstant(value: string, zone: string) {
  const target = new Date(`${value}:00Z`);
  let guess = target.getTime();
  for (let i = 0; i < 4; i++) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(guess));
    const p = (name: string) => parts.find(part => part.type === name)?.value;
    const displayed = Date.parse(`${p('year')}-${p('month')}-${p('day')}T${p('hour')}:${p('minute')}:${p('second')}Z`);
    const delta = target.getTime() - displayed;
    if (!delta) return new Date(guess).toISOString();
    guess += delta;
  }
  throw new Error('This local time does not exist because clocks change. Choose another time.');
}

export function eventDay(event: CalendarEvent, zone: string) { const t = event.temporal; return t.startDate || t.dueDate || dateKey(new Date(t.start || t.dueAt || ''), zone); }
export function eventTime(event: CalendarEvent, zone: string) { const t = event.temporal; return t.mode === 'all_day' ? 'All day' : t.dueDate ? 'Due today' : new Intl.DateTimeFormat(undefined, { timeZone: zone, hour: 'numeric', minute: '2-digit' }).format(new Date(t.start || t.dueAt || '')); }
