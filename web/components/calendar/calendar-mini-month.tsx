'use client';
import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { shiftMonth } from '@/lib/calendar-layout';
import { addDays } from '@/lib/calendar-slots';
import styles from './calendar.module.css';

const labelDay = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
const monthOf = (day: string) => `${day.slice(0, 7)}-01`;
/** Monday on or before `day`, matching the week view. */
const weekStart = (day: string) => addDays(day, -((new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7));
const KEY_STEPS: Record<string, (day: string) => string> = {
  ArrowLeft: day => addDays(day, -1), ArrowRight: day => addDays(day, 1), ArrowUp: day => addDays(day, -7), ArrowDown: day => addDays(day, 7),
  Home: day => weekStart(day), End: day => addDays(weekStart(day), 6), PageUp: day => shiftMonth(day, -1), PageDown: day => shiftMonth(day, 1),
};

/**
 * Small month grid beside the week/day timeline. Picking a date moves the main view there; today and the
 * visible range [rangeStart, rangeEnd) are highlighted. Arrow keys, Home/End and PageUp/PageDown move focus.
 */
export function CalendarMiniMonth({ day, today, rangeStart, rangeEnd, onPick }: { day: string; today: string; rangeStart: string; rangeEnd: string; onPick: (day: string) => void }) {
  const [month, setMonth] = useState(() => monthOf(day));
  const [focus, setFocus] = useState(day);
  const [syncedDay, setSyncedDay] = useState(day);
  const table = useRef<HTMLTableElement>(null);
  const moveFocus = useRef(false);
  // Follow the main view when it moves to another date.
  if (syncedDay !== day) { setSyncedDay(day); setFocus(day); setMonth(monthOf(day)); }
  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    table.current?.querySelector<HTMLElement>(`[data-date="${focus}"]`)?.focus();
  }, [focus, month]);
  const first = weekStart(month);
  const weeks = Array.from({ length: 6 }, (_, week) => Array.from({ length: 7 }, (_, index) => addDays(first, week * 7 + index)));
  const tabbable = focus.slice(0, 7) === month.slice(0, 7) ? focus : month;
  const lastVisible = addDays(rangeEnd, -1);
  const captionId = `mini-month-${month}`;
  /** Show the month containing `next`; keyboard moves also take focus there (the cell may be re-created). */
  function go(next: string, focusDate = true) {
    // Only flag a focus move when state changes, so the effect below runs and clears the flag.
    moveFocus.current = focusDate && (next !== focus || monthOf(next) !== month);
    setFocus(next); setMonth(monthOf(next));
  }
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    const step = KEY_STEPS[event.key];
    if (!step) return;
    event.preventDefault();
    go(step(date));
  }
  return <section className={styles.miniMonth} aria-labelledby={captionId}>
    <header>
      <h2 id={captionId} aria-live="polite">{labelDay(month, { month: 'long', year: 'numeric' })}</h2>
      <button type="button" aria-label="Previous month" onClick={() => go(shiftMonth(month, -1), false)}><ChevronLeft size={16}/></button>
      <button type="button" aria-label="Next month" onClick={() => go(shiftMonth(month, 1), false)}><ChevronRight size={16}/></button>
    </header>
    <table ref={table} role="grid" aria-labelledby={captionId}>
      <thead><tr>{weeks[0].map(date => <th key={date} scope="col" abbr={labelDay(date, { weekday: 'long' })}>{labelDay(date, { weekday: 'narrow' })}</th>)}</tr></thead>
      <tbody>{weeks.map((week, row) => <tr key={row}>{week.map(date => {
        const inRange = date >= rangeStart && date < rangeEnd;
        return <td key={date} aria-selected={inRange} data-in-range={inRange || undefined} data-range-start={inRange && (date === rangeStart || date === weekStart(date)) || undefined} data-range-end={inRange && (date === lastVisible || date === addDays(weekStart(date), 6)) || undefined}>
          <button type="button" data-date={date} tabIndex={date === tabbable ? 0 : -1} data-outside={date.slice(0, 7) !== month.slice(0, 7) || undefined} aria-current={date === today ? 'date' : undefined} aria-label={`${labelDay(date, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}${date === today ? ', today' : ''}`} onKeyDown={event => onKeyDown(event, date)} onClick={() => { moveFocus.current = date.slice(0, 7) !== month.slice(0, 7); setFocus(date); onPick(date); }}>{labelDay(date, { day: 'numeric' })}</button>
        </td>;
      })}</tr>)}</tbody>
    </table>
  </section>;
}
