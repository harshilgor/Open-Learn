'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { CALENDAR_CHANGED, calendarApi, type CalendarEvent, type StudentCalendar } from '@/lib/calendar-client';

export function useCalendar(from: string, to: string, zone: string) {
  const [calendars, setCalendars] = useState<StudentCalendar[]>([]);
  const [items, setItems] = useState<CalendarEvent[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const epoch = useRef(0);
  const refresh = useCallback(() => setRefreshKey(value => value + 1), []);
  useEffect(() => {
    const version = ++epoch.current, controller = new AbortController();
    let pending = false;
    async function load() {
      if (pending || controller.signal.aborted) return;
      pending = true;
      try {
        const [list, first] = await Promise.all([calendarApi.calendars(controller.signal), calendarApi.feed(from, to, zone, controller.signal)]);
        const events = [...first.items]; let cursor = first.nextCursor;
        while (cursor) {
          const page = await calendarApi.feed(from, to, zone, controller.signal, cursor);
          if (page.snapshotRevision !== first.snapshotRevision) throw new Error('Your schedule changed. Refresh to load the latest events.');
          events.push(...page.items); cursor = page.nextCursor;
        }
        if (epoch.current !== version) return;
        setCalendars(list.items); setItems(events); setUpdatedAt(first.generatedAt); setError(first.partial ? 'Some calendars are awaiting sync. This schedule may be incomplete.' : '');
      } catch (cause) { if (epoch.current === version && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Your schedule could not load.'); }
      finally { pending = false; if (epoch.current === version) setLoading(false); }
    }
    const reset = () => { epoch.current++; controller.abort(); setCalendars([]); setItems([]); setUpdatedAt(null); setLoading(true); refresh(); };
    void load(); const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 30000);
    const focus = () => void load();
    window.addEventListener('focus', focus); window.addEventListener(CALENDAR_CHANGED, refresh); window.addEventListener(ACCOUNT_CHANGED, reset);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener('focus', focus); window.removeEventListener(CALENDAR_CHANGED, refresh); window.removeEventListener(ACCOUNT_CHANGED, reset); };
  }, [from, to, zone, refresh, refreshKey]);
  return { calendars, items, error, loading, updatedAt, refresh };
}
