'use client';
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Plus, Repeat2 } from 'lucide-react';
import { dateKey, eventTime, type CalendarEvent, type StudentCalendar } from '@/lib/calendar-client';
import { layoutDay, occursOnDate } from '@/lib/calendar-layout';
import styles from './calendar.module.css';

const MIN_HOUR_HEIGHT = 48;
const MAX_HOUR_HEIGHT = 64;

const hourLabel = (hour: number) => new Intl.DateTimeFormat(undefined, { hour: 'numeric', hour12: true, timeZone: 'UTC' }).format(new Date(Date.UTC(2020, 0, 1, hour)));
const isWeekend = (day: string) => [0, 6].includes(new Date(`${day}T12:00:00Z`).getUTCDay());

/** Shared colour category for an event, used by every calendar view. */
export function eventCategory(event: CalendarEvent): string {
  return ['class', 'exam', 'assignment', 'study', 'reminder', 'personal'].includes(event.type) ? event.type : 'personal';
}

export function CalendarTimeline({ days, events, zone, calendars, onSelect, onAdd, onDay }: { days: string[]; events: CalendarEvent[]; zone: string; calendars: StudentCalendar[]; onSelect: (event: CalendarEvent) => void; onAdd: (day: string, time?: string) => void; onDay: (day: string) => void }) {
  const grid = useRef<HTMLDivElement>(null);
  const [hourHeight, setHourHeight] = useState(MIN_HOUR_HEIGHT);
  const [showFullDay, setShowFullDay] = useState(false);
  const today = dateKey(new Date(), zone);
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date());
  const nowMinute = Number(parts.find(p => p.type === 'hour')?.value) * 60 + Number(parts.find(p => p.type === 'minute')?.value);
  const dayKey = days.join(',');
  const firstHour = showFullDay ? 0 : 6;
  const lastHour = showFullDay ? 24 : 22;
  const hourCount = lastHour - firstHour;
  const hasAllDay = days.some(day => events.some(e => e.temporal.mode !== 'timed' && occursOnDate(e, day, zone)));
  const showsToday = days.includes(today);
  useEffect(() => {
    const scroll = grid.current?.closest(`.${styles.calendarScroll}`);
    if (!scroll) return;
    const update = () => {
      const available = Math.max(24, scroll.clientHeight - 110);
      setHourHeight(Math.max(MIN_HOUR_HEIGHT, Math.min(MAX_HOUR_HEIGHT, Math.floor(available / hourCount))));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(scroll);
    return () => observer.disconnect();
  }, [hourCount]);
  // Open on the part of the day that matters: the current time today, otherwise the first event or 8 AM.
  useEffect(() => {
    const scroll = grid.current?.closest<HTMLElement>(`.${styles.calendarScroll}`);
    if (!scroll) return;
    const firstEvent = Math.min(...days.flatMap(day => layoutDay(events, day, zone).map(item => item.start)), 24 * 60);
    const focus = showsToday ? nowMinute - 90 : firstEvent < 24 * 60 ? firstEvent - 30 : 8 * 60;
    scroll.scrollTop = Math.max(0, (focus - firstHour * 60) * hourHeight / 60);
    // Only re-anchor when the visible range or the row height changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayKey, hourHeight, firstHour]);
  return <div className={styles.timelineWrap}>
    <div ref={grid} className={styles.timeline} style={{ '--hour-height': `${hourHeight}px`, '--hour-count': hourCount, gridTemplateColumns: `var(--gutter-width) repeat(${days.length}, minmax(0,1fr))` } as CSSProperties} data-days={days.length}>
      <div className={styles.timeGutter}>
        <div className={styles.timelineHead}><button type="button" className={styles.rangeToggle} aria-pressed={showFullDay} onClick={() => setShowFullDay(value => !value)} title={showFullDay ? 'Showing all 24 hours. Show study hours (6 AM–10 PM)' : 'Showing study hours (6 AM–10 PM). Show all 24 hours'}>24h</button></div>
        {hasAllDay ? <div className={styles.allDayLabel} aria-hidden="true">All day</div> : null}
        <div className={styles.gutterTrack} aria-hidden="true">
          {Array.from({ length: hourCount }, (_, index) => <span key={index} style={{ top: index * hourHeight }}>{hourLabel(firstHour + index)}</span>)}
        </div>
      </div>
      {days.map(day => {
        const isToday = day === today;
        const date = new Date(`${day}T12:00Z`);
        return <div className={`${styles.dayColumn} ${isWeekend(day) ? styles.weekend : ''}`} key={day}>
          <header className={`${styles.timelineHead} ${isToday ? styles.todayHead : ''}`}>
            <button type="button" className={styles.dayHeading} onClick={() => onDay(day)} aria-label={`Open ${new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric' }).format(date)}`} aria-current={isToday ? 'date' : undefined}>
              <span>{new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', weekday: 'short' }).format(date)}</span>
              <strong>{new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', day: 'numeric' }).format(date)}</strong>
            </button>
            <button type="button" className={styles.dayAdd} aria-label={`Add event on ${day}`} onClick={() => onAdd(day)}><Plus size={15}/></button>
          </header>
          {hasAllDay ? <div className={styles.timelineAllDay}>{events.filter(e => e.temporal.mode !== 'timed' && occursOnDate(e, day, zone)).map(e => <button type="button" key={e.id} className={styles.allDayChip} data-category={eventCategory(e)} onClick={() => onSelect(e)} title={`${e.title} · ${eventTime(e, zone)}`}>{e.title}</button>)}</div> : null}
          <div className={styles.dayTrack}>
            {Array.from({ length: hourCount }, (_, index) => <button type="button" tabIndex={-1} className={styles.gridHour} key={index} aria-label={`Add event at ${hourLabel(firstHour + index)}`} onClick={() => onAdd(day, `${String(firstHour + index).padStart(2, '0')}:00`)}/>)}
            {isToday && nowMinute >= firstHour * 60 && nowMinute < lastHour * 60 ? <span className={styles.nowLine} style={{ top: (nowMinute - firstHour * 60) * hourHeight / 60 }} role="img" aria-label="Current time"/> : null}
            {layoutDay(events, day, zone).filter(({ start, end }) => end > firstHour * 60 && start < lastHour * 60).map(({ event, start, end, lane, lanes }) => {
              const visibleStart = Math.max(start, firstHour * 60);
              const visibleEnd = Math.min(end, lastHour * 60);
              const height = Math.max(24, (visibleEnd - visibleStart) * hourHeight / 60 - 2);
              const compact = height < 36;
              const narrow = lanes > 1 && days.length > 1;
              const short = !compact && (height < 64 || narrow);
              const calendarColor = calendars.find(c => c.id === event.calendarId)?.color;
              return <button type="button" key={event.id} className={`${styles.timelineEvent} ${compact ? styles.timelineEventCompact : short ? styles.timelineEventShort : ''} ${narrow ? styles.timelineEventNarrow : ''}`} title={`${event.title} · ${eventTime(event, zone)}`} data-category={eventCategory(event)} style={{ top: (visibleStart - firstHour * 60) * hourHeight / 60 + 1, height, left: `calc(${lane / lanes * 100}% + 2px)`, width: `calc(${100 / lanes}% - 5px)`, ...(calendarColor && event.type === 'personal' ? { '--event-color': calendarColor } as CSSProperties : {}) }} onClick={() => onSelect(event)} aria-label={`${event.title}, ${eventTime(event, zone)}`}>
                <strong>{event.title}</strong>
                <span>{eventTime(event, zone)}{event.recurrence ? <Repeat2 size={11} aria-label="Repeats"/> : null}</span>
              </button>;
            })}
          </div>
        </div>;
      })}
    </div>
  </div>;
}
