'use client';
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import { Plus, Repeat2 } from 'lucide-react';
import { dateKey, eventTime, type CalendarEvent, type StudentCalendar } from '@/lib/calendar-client';
import { layoutDay, occursOnDate } from '@/lib/calendar-layout';
import { clamp, clockTime, dragRange, slotEnd, slotLabel, snapRound, SNAP_MINUTES } from '@/lib/calendar-slots';
import styles from './calendar.module.css';

const MIN_HOUR_HEIGHT = 48;
const MAX_HOUR_HEIGHT = 64;

const hourLabel = (hour: number) => new Intl.DateTimeFormat(undefined, { hour: 'numeric', hour12: true, timeZone: 'UTC' }).format(new Date(Date.UTC(2020, 0, 1, hour)));
const isWeekend = (day: string) => [0, 6].includes(new Date(`${day}T12:00:00Z`).getUTCDay());
/** Pointer travel (px) before a press on the grid becomes a drag instead of a click. */
const DRAG_THRESHOLD = 4;

/** What a drag currently shows: a new time range, or an existing event at its new slot. Minutes of day. */
type DragPreview = { kind: 'create'; day: string; start: number; end: number } | { kind: 'move'; event: CalendarEvent; day: string; start: number; end: number };
/** Pointer gesture in progress. `preview` is set once the pointer passes the drag threshold. */
type Gesture = { pointerId: number; target: HTMLElement; x: number; y: number; cancelled: boolean; preview: DragPreview | null } & ({ kind: 'create'; day: string; anchor: number } | { kind: 'move'; event: CalendarEvent; day: string; start: number; duration: number; offset: number });

/** Shared colour category for an event, used by every calendar view. */
export function eventCategory(event: CalendarEvent): string {
  return ['class', 'exam', 'assignment', 'study', 'reminder', 'personal'].includes(event.type) ? event.type : 'personal';
}

/**
 * Week/day time grid. Click an hour to add an event there, or press and drag down a column to pick a
 * range; drag an editable event (mouse or pen) to another time or day. Escape cancels a drag.
 */
export function CalendarTimeline({ days, events, zone, calendars, onSelect, onAdd, onMove, onDay }: { days: string[]; events: CalendarEvent[]; zone: string; calendars: StudentCalendar[]; onSelect: (event: CalendarEvent) => void; onAdd: (day: string, time?: string, end?: { day: string; time: string }) => void; onMove?: (event: CalendarEvent, day: string, time: string) => void; onDay: (day: string) => void }) {
  const grid = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const suppressClick = useRef(false);
  const [hourHeight, setHourHeight] = useState(MIN_HOUR_HEIGHT);
  const [showFullDay, setShowFullDay] = useState(false);
  const [drag, setDrag] = useState<DragPreview | null>(null);
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
  // Escape abandons a drag; the release that follows must not count as a click either.
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      const current = gesture.current;
      if (event.key !== 'Escape' || !current || current.cancelled) return;
      event.preventDefault();
      gesture.current = { ...current, cancelled: true, preview: null };
      setDrag(null);
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, []);

  /** Minute of the day under a viewport y coordinate. */
  const minuteAt = (track: Element, clientY: number) => firstHour * 60 + (clientY - track.getBoundingClientRect().top) * 60 / hourHeight;
  /** Day column under a viewport x coordinate, clamped to the first/last visible day. */
  function trackAt(clientX: number) {
    const tracks = [...(grid.current?.querySelectorAll<HTMLElement>('[data-track-day]') ?? [])];
    return tracks.find(track => { const rect = track.getBoundingClientRect(); return clientX >= rect.left && clientX < rect.right; }) ?? (tracks.length && clientX < tracks[0].getBoundingClientRect().left ? tracks[0] : tracks[tracks.length - 1]);
  }
  /** Ignore the click the browser sends right after a drag ends. */
  function swallowClick() {
    suppressClick.current = true;
    window.setTimeout(() => { suppressClick.current = false; }, 0);
  }
  function begin(event: ReactPointerEvent<HTMLElement>, gestureFor: (minute: number) => Gesture | null) {
    if (event.button !== 0 || event.pointerType === 'touch') return;
    const track = event.currentTarget.closest('[data-track-day]');
    if (!track) return;
    suppressClick.current = false;
    gesture.current = gestureFor(minuteAt(track, event.clientY));
    if (gesture.current) event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  const beginCreate = (event: ReactPointerEvent<HTMLElement>, day: string) => begin(event, anchor => ({ kind: 'create', day, anchor, pointerId: event.pointerId, target: event.currentTarget, x: event.clientX, y: event.clientY, cancelled: false, preview: null }));
  const beginMove = (pointer: ReactPointerEvent<HTMLElement>, event: CalendarEvent, day: string, start: number) => begin(pointer, minute => ({ kind: 'move', event, day, start, duration: (Date.parse(event.temporal.end!) - Date.parse(event.temporal.start!)) / 60000, offset: minute - start, pointerId: pointer.pointerId, target: pointer.currentTarget, x: pointer.clientX, y: pointer.clientY, cancelled: false, preview: null }));
  function pointerMove(event: ReactPointerEvent<HTMLElement>) {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId || current.cancelled) return;
    if (!current.preview && Math.hypot(event.clientX - current.x, event.clientY - current.y) < DRAG_THRESHOLD) return;
    let preview: DragPreview;
    if (current.kind === 'create') {
      const track = current.target.closest('[data-track-day]');
      if (!track) return;
      preview = { kind: 'create', day: current.day, ...dragRange(current.anchor, minuteAt(track, event.clientY), firstHour * 60, lastHour * 60) };
    } else {
      const track = trackAt(event.clientX);
      if (!track) return;
      const start = clamp(snapRound(minuteAt(track, event.clientY) - current.offset), firstHour * 60, lastHour * 60 - SNAP_MINUTES);
      preview = { kind: 'move', event: current.event, day: track.dataset.trackDay!, start, end: start + current.duration };
    }
    gesture.current = { ...current, preview };
    setDrag(preview);
  }
  function pointerEnd(event: ReactPointerEvent<HTMLElement>, commit: boolean) {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    gesture.current = null;
    if (current.target.hasPointerCapture?.(event.pointerId)) current.target.releasePointerCapture(event.pointerId);
    if (current.cancelled || current.preview) swallowClick();
    setDrag(null);
    const preview = current.preview;
    if (!commit || current.cancelled || !preview) return;
    if (preview.kind === 'create') onAdd(preview.day, clockTime(preview.start), slotEnd(preview.day, preview.end));
    else if (current.kind === 'move' && (preview.day !== current.day || preview.start !== current.start)) onMove?.(current.event, preview.day, clockTime(preview.start));
  }
  return <div className={styles.timelineWrap}>
    <div ref={grid} className={styles.timeline} data-dragging={drag?.kind} onPointerMove={pointerMove} onPointerUp={event => pointerEnd(event, true)} onPointerCancel={event => pointerEnd(event, false)} style={{ '--hour-height': `${hourHeight}px`, '--hour-count': hourCount, gridTemplateColumns: `var(--gutter-width) repeat(${days.length}, minmax(0,1fr))` } as CSSProperties} data-days={days.length}>
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
          <div className={styles.dayTrack} data-track-day={day}>
            {Array.from({ length: hourCount }, (_, index) => <button type="button" tabIndex={-1} className={styles.gridHour} key={index} aria-label={`Add event at ${hourLabel(firstHour + index)}`} onPointerDown={event => beginCreate(event, day)} onClick={() => { if (!suppressClick.current) onAdd(day, `${String(firstHour + index).padStart(2, '0')}:00`); }}/>)}
            {isToday && nowMinute >= firstHour * 60 && nowMinute < lastHour * 60 ? <span className={styles.nowLine} style={{ top: (nowMinute - firstHour * 60) * hourHeight / 60 }} role="img" aria-label="Current time"/> : null}
            {layoutDay(events, day, zone).filter(({ start, end }) => end > firstHour * 60 && start < lastHour * 60).map(({ event, start, end, lane, lanes }) => {
              const visibleStart = Math.max(start, firstHour * 60);
              const visibleEnd = Math.min(end, lastHour * 60);
              const height = Math.max(24, (visibleEnd - visibleStart) * hourHeight / 60 - 2);
              const compact = height < 36;
              const narrow = lanes > 1 && days.length > 1;
              const short = !compact && (height < 64 || narrow);
              const calendarColor = calendars.find(c => c.id === event.calendarId)?.color;
              // Only editable events that start on this day can be dragged; read-only sources open as before.
              const movable = !!onMove && !!event.canEdit && dateKey(new Date(event.temporal.start!), zone) === day;
              const dragging = drag?.kind === 'move' && drag.event.id === event.id;
              return <button type="button" key={event.id} className={`${styles.timelineEvent} ${compact ? styles.timelineEventCompact : short ? styles.timelineEventShort : ''} ${narrow ? styles.timelineEventNarrow : ''}`} title={`${event.title} · ${eventTime(event, zone)}${movable ? ' · Drag to reschedule' : ''}`} data-category={eventCategory(event)} data-movable={movable || undefined} data-dragging={dragging || undefined} style={{ top: (visibleStart - firstHour * 60) * hourHeight / 60 + 1, height, left: `calc(${lane / lanes * 100}% + 2px)`, width: `calc(${100 / lanes}% - 5px)`, ...(calendarColor && event.type === 'personal' ? { '--event-color': calendarColor } as CSSProperties : {}) }} onPointerDown={movable ? pointer => beginMove(pointer, event, day, start) : undefined} onClick={() => { if (!suppressClick.current) onSelect(event); }} aria-label={`${event.title}, ${eventTime(event, zone)}`}>
                <strong>{event.title}</strong>
                <span>{eventTime(event, zone)}{event.recurrence ? <Repeat2 size={11} aria-label="Repeats"/> : null}</span>
              </button>;
            })}
            {drag && drag.day === day ? (() => {
              const top = (Math.max(drag.start, firstHour * 60) - firstHour * 60) * hourHeight / 60;
              const height = Math.max(hourHeight / 4, (Math.min(drag.end, lastHour * 60) - Math.max(drag.start, firstHour * 60)) * hourHeight / 60 - 2);
              return <div className={styles.dragPreview} data-kind={drag.kind} data-category={drag.kind === 'move' ? eventCategory(drag.event) : undefined} style={{ top: top + 1, height }} aria-hidden="true">
                {drag.kind === 'move' ? <strong>{drag.event.title}</strong> : null}
                <span>{slotLabel(drag.start, drag.end)}</span>
              </div>;
            })() : null}
          </div>
        </div>;
      })}
    </div>
  </div>;
}
