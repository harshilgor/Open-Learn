/** Minute-of-day helpers shared by the calendar's drag gestures, quick add and event form. */

/** Drag gestures snap to quarter hours. */
export const SNAP_MINUTES = 15;

export const addDays = (day: string, amount: number) => new Date(Date.parse(`${day}T12:00:00Z`) + amount * 86400000).toISOString().slice(0, 10);

export const snapRound = (minutes: number, step = SNAP_MINUTES) => Math.round(minutes / step) * step;
export const snapFloor = (minutes: number, step = SNAP_MINUTES) => Math.floor(minutes / step) * step;
export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const pad = (value: number) => String(value).padStart(2, '0');

/** "HH:MM" wall clock for a minute of the day; values past midnight wrap. */
export function clockTime(minutes: number) {
  const value = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${pad(Math.floor(value / 60))}:${pad(value % 60)}`;
}

/** Minutes since midnight for an "HH:MM" wall clock. */
export const clockMinutes = (time: string) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));

/** Day and wall clock for a slot end that may run past midnight (1440 = next day 00:00). */
export function slotEnd(day: string, minutes: number) {
  return { day: addDays(day, Math.floor(minutes / 1440)), time: clockTime(minutes) };
}

/**
 * Range selected by dragging from `anchor` to `current` (minutes of day): both ends snap down to the grid,
 * the slot under the pointer is always included, and the result stays within [min, max].
 */
export function dragRange(anchor: number, current: number, min: number, max: number, step = SNAP_MINUTES) {
  const a = snapFloor(clamp(anchor, min, max - step), step), b = snapFloor(clamp(current, min, max - step), step);
  return { start: Math.min(a, b), end: Math.max(a, b) + step };
}

/** Localised "9:00 – 10:30 AM" label for a minute range on one day. */
export function slotLabel(start: number, end: number) {
  const at = (minutes: number) => new Date(Date.UTC(2020, 0, 1, 0, minutes % 1440));
  const format = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' });
  return end < 1440 ? format.formatRange(at(start), at(end)) : `${format.format(at(start))} – ${format.format(at(end))}`;
}
