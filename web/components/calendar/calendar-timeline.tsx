'use client';
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Plus, Repeat2 } from 'lucide-react';
import { dateKey, eventTime, type CalendarEvent, type StudentCalendar } from '@/lib/calendar-client';
import { layoutDay, occursOnDate } from '@/lib/calendar-layout';
import styles from './calendar.module.css';

export function CalendarTimeline({ days, events, zone, calendars, onSelect, onAdd, onDay }: { days: string[]; events: CalendarEvent[]; zone: string; calendars: StudentCalendar[]; onSelect: (event: CalendarEvent) => void; onAdd: (day: string) => void; onDay: (day: string) => void }) {
  const grid = useRef<HTMLDivElement>(null);
  const [hourHeight, setHourHeight] = useState(42);
  const [showFullDay, setShowFullDay] = useState(false);
  const today = dateKey(new Date(), zone);
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date());
  const nowMinute = Number(parts.find(p => p.type === 'hour')?.value) * 60 + Number(parts.find(p => p.type === 'minute')?.value);
  const dayKey = days.join(',');
  const firstHour = showFullDay ? 0 : 6;
  const lastHour = showFullDay ? 24 : 22;
  useEffect(() => {
    const scroll = grid.current?.closest(`.${styles.calendarScroll}`);
    if (!scroll) return;
    const update = () => {
      const available = Math.max(24, scroll.clientHeight - 92);
      setHourHeight(Math.max(28, Math.min(56, Math.floor(available / (lastHour - firstHour)))));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(scroll);
    return () => observer.disconnect();
  }, [firstHour, lastHour]);
  useEffect(() => { const parent = grid.current?.closest(`.${styles.calendarScroll}`); if (parent) parent.scrollTop = 0; }, [dayKey]);
  return <>
    <div className={styles.scheduleControls}><span>{showFullDay ? 'Full day · 12 AM–12 AM' : 'Study hours · 6 AM–10 PM'}</span><button type="button" onClick={() => setShowFullDay(value => !value)}>{showFullDay ? 'Show study hours' : 'Show full day'}</button></div>
    <div ref={grid} className={styles.timeline} style={{ '--hour-height': `${hourHeight}px`, '--hour-count': lastHour - firstHour, gridTemplateColumns: `42px repeat(${days.length}, minmax(0,1fr))` } as CSSProperties}>
    <div className={styles.timeGutter}>
      <div className={styles.timelineHeadSpace}/>
      {Array.from({ length: lastHour - firstHour }, (_, index) => { const hour = firstHour + index; return <span key={hour}>{new Intl.DateTimeFormat(undefined, { hour: 'numeric', hour12: true, timeZone: 'UTC' }).format(new Date(Date.UTC(2020, 0, 1, hour)))}</span>; })}
    </div>
    {days.map(day => <div className={styles.dayColumn} key={day}>
      <header className={day === today ? styles.today : ''}>
        <button onClick={() => onDay(day)}>{new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'short', day: 'numeric' }).format(new Date(`${day}T12:00Z`))}</button>
        <button aria-label={`Add event on ${day}`} onClick={() => onAdd(day)}><Plus size={14}/></button>
      </header>
      <div className={styles.timelineAllDay}>{events.filter(e => e.temporal.mode !== 'timed' && occursOnDate(e, day, zone)).map(e => <button key={e.id} className={styles.compactEvent} onClick={() => onSelect(e)}>{e.title}</button>)}</div>
      <div className={styles.dayTrack}>
        {Array.from({ length: lastHour - firstHour }, (_, index) => <div className={styles.gridHour} key={index} aria-hidden="true"/>)}
        {day === today && nowMinute >= firstHour * 60 && nowMinute < lastHour * 60 ? <span className={styles.nowLine} style={{ top: (nowMinute - firstHour * 60) * hourHeight / 60 }} aria-label="Current time"/> : null}
        {layoutDay(events, day, zone).filter(({ start, end }) => end > firstHour * 60 && start < lastHour * 60).map(({ event, start, end, lane, lanes }) => { const visibleStart = Math.max(start, firstHour * 60); const visibleEnd = Math.min(end, lastHour * 60); return <button key={event.id} className={styles.timelineEvent} style={{ top: (visibleStart - firstHour * 60) * hourHeight / 60, height: Math.max(22, (visibleEnd - visibleStart) * hourHeight / 60), left: `${lane / lanes * 100}%`, width: `calc(${100 / lanes}% - 4px)`, borderLeftColor: calendars.find(c => c.id === event.calendarId)?.color || 'var(--primary)' }} onClick={() => onSelect(event)} aria-label={`${event.title}, ${eventTime(event, zone)}`}><span>{eventTime(event, zone)}{event.recurrence ? <Repeat2 size={10}/> : null}</span><strong>{event.title}</strong></button>; })}
      </div>
    </div>)}
    </div>
  </>;
}
