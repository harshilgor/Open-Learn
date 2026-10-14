import { calendarApi, dateKey, wallInstant, type CalendarEvent } from './calendar-client';

/** Fired by a timestamp or key moment in a note; the note's recording player seeks to it. */
export const RECORDING_SEEK_EVENT = 'openlearn:recording-seek';
export type RecordingSeek = { noteId: string; ms: number };
export function seekRecording(detail: RecordingSeek): void {
  window.dispatchEvent(new CustomEvent<RecordingSeek>(RECORDING_SEEK_EVENT, { detail }));
}

/** "[12:05]", "[~1:02:05]" → milliseconds, or null when the text is not a transcript timestamp. */
export function timestampMs(label: string): number | null {
  const match = label.trim().match(/^\[~?(?:(\d+):)?(\d{1,2}):(\d{2})\]$/);
  if (!match) return null;
  return ((Number(match[1] || 0) * 60 + Number(match[2])) * 60 + Number(match[3])) * 1000;
}

const CLASS_TYPES = /class|lecture|lab|seminar|tutorial|section/i;
const EARLY_MS = 15 * 60 * 1000, LATE_MS = 10 * 60 * 1000;

/**
 * The calendar item a recording started now most likely belongs to: a timed
 * event under way (or starting within 15 minutes), preferring classes.
 */
export function eventForRecording(events: CalendarEvent[], now = Date.now()): CalendarEvent | null {
  const candidates = events.filter(event => {
    if (event.temporal.mode !== 'timed' || event.status === 'cancelled') return false;
    const start = Date.parse(event.temporal.start || ''), end = Date.parse(event.temporal.end || '') || start + 3600_000;
    return Number.isFinite(start) && start - EARLY_MS <= now && now <= end + LATE_MS;
  });
  const score = (event: CalendarEvent) => (CLASS_TYPES.test(`${event.type} ${event.title}`) ? 0 : 1) * 1e12 + Math.abs(Date.parse(event.temporal.start || '') - now);
  return candidates.sort((a, b) => score(a) - score(b))[0] || null;
}

export async function currentRecordingEvent(): Promise<CalendarEvent | null> {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const now = new Date(), day = dateKey(now, zone);
  const tomorrow = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const feed = await calendarApi.feed(wallInstant(`${day}T00:00`, zone), wallInstant(`${tomorrow}T00:00`, zone), zone);
  return eventForRecording(feed.items, now.getTime());
}

/** "Biology 101 · Oct 14" */
export function recordingTitle(event: CalendarEvent, now = new Date()): string {
  return `${event.title.trim().slice(0, 120)} · ${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(now)}`;
}
