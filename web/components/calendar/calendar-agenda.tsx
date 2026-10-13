'use client';
import { useState } from 'react';
import { CalendarDays, Plus, ArrowUpRight } from 'lucide-react';
import { useCalendar } from '@/hooks/use-calendar';
import { dateKey, eventDay, eventTime, wallInstant } from '@/lib/calendar-client';
import type { CourseSummary } from '@/lib/api';
import { CalendarEventForm } from './calendar-event-form';
import styles from './calendar.module.css';

export function CalendarAgenda({ courses, onCalendar, onPrep }: { courses: CourseSummary[]; onCalendar: () => void; onPrep: (courseId: string, title: string) => void }) {
  const [zone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const day = dateKey(new Date(), zone);
  const future = new Date(Date.parse(`${day}T12:00:00Z`) + 7 * 86400000).toISOString().slice(0, 10);
  const past = new Date(Date.parse(`${day}T12:00:00Z`) - 7 * 86400000).toISOString().slice(0, 10);
  const data = useCalendar(wallInstant(`${past}T00:00`, zone), wallInstant(`${future}T00:00`, zone), zone);
  const [form, setForm] = useState(false);
  const today = data.items.filter(event => eventDay(event, zone) === day);
  const deadlines = data.items.filter(event => event.temporal.mode === 'deadline' && eventDay(event, zone) >= day).slice(0, 6);
  const overdue = data.items.filter(event => event.temporal.mode === 'deadline' && eventDay(event, zone) < day && event.status !== 'completed').slice(0, 5);
  return <section className={styles.dashboardAgenda} aria-label="Today and upcoming deadlines">
    <header><div><span className={styles.eyebrow}>{new Intl.DateTimeFormat(undefined, { timeZone: zone, weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())}</span><h2>Today</h2></div><div><button type="button" onClick={() => setForm(true)}><Plus size={15}/>Add event</button><button type="button" onClick={onCalendar}><CalendarDays size={15}/>Open calendar<ArrowUpRight size={13}/></button></div></header>
    {data.error ? <p role="alert" className={styles.error}>{data.error}<button onClick={data.refresh}>Retry schedule</button></p> : null}
    {data.loading ? <p role="status" className={styles.free}>Loading your day…</p> : today.length ? <div>{today.slice(0, 8).map(event => <button className={styles.agendaRow} key={event.id} onClick={onCalendar}><span>{eventTime(event, zone)}</span><div><strong>{event.title}</strong><small>{courses.find(c => c.id === event.courseId)?.name || event.type}</small></div><ArrowUpRight size={14}/></button>)}</div> : !data.error ? <p className={styles.free}>A little room to focus. Add a class, deadline, or study session.</p> : null}
    {overdue.length ? <div className={styles.deadlines}><h3>Needs attention</h3>{overdue.map(event => <button key={event.id} onClick={onCalendar}>{event.title}<small>Due {eventDay(event, zone)}</small></button>)}</div> : null}
    {deadlines.length ? <div className={styles.deadlines}><h3>Upcoming deadlines</h3>{deadlines.map(event => <button key={event.id} onClick={() => event.courseId ? onPrep(event.courseId, event.title) : onCalendar()}>{event.title}<small>{eventDay(event, zone)}</small></button>)}</div> : null}
    {form ? <CalendarEventForm day={day} zone={zone} calendars={data.calendars} courses={courses} onClose={() => setForm(false)} onSaved={() => data.refresh()}/> : null}
  </section>;
}
