'use client';
import { useEffect, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Plus, Repeat2, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { useCalendar } from '@/hooks/use-calendar';
import { calendarApi, CALENDAR_CHANGED, dateKey, eventDay, eventTime, wallInstant, type CalendarEvent, type CalendarOperation } from '@/lib/calendar-client';
import type { CourseSummary } from '@/lib/api';
import { request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { CalendarRoutines } from './calendar-routines';
import { CalendarEventForm } from './calendar-event-form';
import styles from './calendar.module.css';
import { CalendarSources } from './calendar-sources';
import { CalendarTimeline } from './calendar-timeline';
import { occursOnDate, shiftMonth } from '@/lib/calendar-layout';

type View = 'week' | 'month' | 'day' | 'agenda';
const addDay = (day: string, amount: number) => new Date(Date.parse(`${day}T12:00:00Z`) + amount * 86400000).toISOString().slice(0, 10);
const labelDay = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));

export function CalendarWorkspace({ courses, onCourse, onStudy }: { courses: CourseSummary[]; onCourse: (id: string) => void; onStudy: (event: CalendarEvent) => void }) {
  const [zone, setZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [day, setDay] = useState(() => dateKey(new Date(), zone));
  const [view, setView] = useState<View>('week');
  const [selected, setSelected] = useState<CalendarEvent | null>(null);
  const [form, setForm] = useState<{ day: string; event?: CalendarEvent } | null>(null);
  const [tab, setTab] = useState<'calendar' | 'routines'>('calendar');
  const [filters, setFilters] = useState<string[] | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [courseFilter, setCourseFilter] = useState('');
  const [notice, setNotice] = useState('');
  const [operation, setOperation] = useState<CalendarOperation | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelScope, setCancelScope] = useState('occurrence');
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  const week = addDay(day, -((weekday + 6) % 7));
  const month = day.slice(0, 7) + '-01';
  const monthWeekday = new Date(`${month}T12:00:00Z`).getUTCDay();
  const first = view === 'month' ? addDay(month, -((monthWeekday + 6) % 7)) : view === 'week' ? week : day;
  const length = view === 'month' ? 42 : view === 'week' || view === 'agenda' ? 7 : 1;
  const end = addDay(first, length);
  const data = useCalendar(wallInstant(`${first}T00:00`, zone), wallInstant(`${end}T00:00`, zone), zone);
  const events = data.items.filter(item => (filters === null || filters.includes(item.calendarId)) && (!courseFilter || item.courseId === courseFilter));
  const days = Array.from({ length }, (_, index) => addDay(first, index));
  const today = dateKey(new Date(), zone);
  useEffect(() => {
    const timer = window.setTimeout(() => {
    if (window.matchMedia('(max-width: 760px)').matches) setView('agenda');
    const params = new URLSearchParams(window.location.search);
    if (/^\d{4}-\d{2}-\d{2}$/.test(params.get('date') || '')) setDay(params.get('date')!);
    if (['week', 'month', 'day', 'agenda'].includes(params.get('view') || '')) setView(params.get('view') as View);
    },0); return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    const reset = () => { setSelected(null); setForm(null); setOperation(null); setNotice(''); setFilters(null); setCourseFilter(''); };
    window.addEventListener(ACCOUNT_CHANGED, reset); return () => window.removeEventListener(ACCOUNT_CHANGED, reset);
  }, []);
  useEffect(() => {
    if (!operation || !['queued', 'dispatching'].includes(operation.status)) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void request<CalendarOperation & { reasonCode?: string }>(`/v1/calendar/operations/${encodeURIComponent(operation.id)}`, { signal: controller.signal }).then(receipt => {
        if (controller.signal.aborted) return;
        if (receipt.status === 'applied') { setOperation(receipt); setNotice('Google confirmed your calendar change.'); data.refresh(); }
        else if (['failed', 'outcome_unknown'].includes(receipt.status)) { setOperation(receipt); setNotice(receipt.status === 'outcome_unknown' ? 'Google may have applied this change. Its outcome needs reconciliation; it will not be sent again automatically.' : 'Google could not apply this change. Refresh the event before retrying.'); }
      }).catch(() => {});
    }, 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [operation, data.refresh]);
  function updateDate(value: string, nextView = view) {
    setDay(value); setView(nextView);
    if (window.location.pathname === '/calendar') window.history.replaceState({}, '', `/calendar?${new URLSearchParams({ date: value, view: nextView })}`);
  }
  function saved(receipt: CalendarOperation) { setOperation(receipt); setNotice(receipt.status === 'applied' ? 'Your calendar is updated.' : 'Your change is queued. Waiting for Google to confirm it.'); data.refresh(); }
  async function remove() {
    if (!selected) return;
    setBusy(true); setNotice('');
    try { saved(await calendarApi.cancel(selected, crypto.randomUUID(), selected.recurrence ? cancelScope : 'series')); setSelected(null); window.dispatchEvent(new Event(CALENDAR_CHANGED)); }
    catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Could not cancel event.'); }
    finally { setBusy(false); }
  }
  const eventButton = (event: CalendarEvent, compact = false) => <button key={event.id} type="button" className={`${styles.event} ${compact ? styles.compactEvent : ''}`} onClick={() => { setSelected(event); setCancelScope(event.recurrence ? 'occurrence' : 'series'); }} style={{ borderLeftColor: data.calendars.find(c => c.id === event.calendarId)?.color || 'var(--primary)' }}><span>{eventTime(event, zone)}{event.recurrence ? <Repeat2 size={12}/> : null}</span><strong>{event.title}</strong>{!compact ? <small>{courses.find(c => c.id === event.courseId)?.name || event.type}</small> : null}</button>;

  return <section className={styles.workspace} aria-label="Student calendar">
    <header className={styles.toolbar}><div><span className={styles.eyebrow}>YOUR TIME, IN ONE PLACE</span><h1>{labelDay(day, { month: 'long', year: 'numeric' })}</h1></div><div className={styles.controls}>
      <Button variant="outline" size="sm" onClick={() => updateDate(today)}>Today</Button>
      <Button variant="ghost" size="icon" aria-label="Previous dates" onClick={() => updateDate(view === 'month' ? shiftMonth(day,-1) : addDay(day,-length))}><ChevronLeft size={18}/></Button>
      <Button variant="ghost" size="icon" aria-label="Next dates" onClick={() => updateDate(view === 'month' ? shiftMonth(day,1) : addDay(day,length))}><ChevronRight size={18}/></Button>
      <label><span className="sr-only">Calendar view</span><select value={view} onChange={e => updateDate(day, e.target.value as View)}>{(['day', 'week', 'month', 'agenda'] as View[]).map(v => <option key={v} value={v}>{v[0].toUpperCase() + v.slice(1)}</option>)}</select></label>
      <Button variant="ghost" size="icon" aria-label="Calendar filters and Buddy permissions" onClick={() => setFilterOpen(!filterOpen)}><Settings2 size={18}/></Button>
      <Button size="sm" onClick={() => setForm({ day })}><Plus size={16}/>Add event</Button>
    </div></header>
    <div className={styles.subnav}><button aria-pressed={tab === 'calendar'} onClick={() => setTab('calendar')}><CalendarDays size={15}/>Calendar</button><button aria-pressed={tab === 'routines'} onClick={() => setTab('routines')}><Repeat2 size={15}/>Routines</button><span>{zone}</span></div>
    {filterOpen ? <div className={styles.filters}><label>Display timezone<input value={zone} onChange={e => { try { new Intl.DateTimeFormat(undefined, { timeZone: e.target.value }); setZone(e.target.value); } catch { setNotice('Choose a valid IANA timezone.'); } }}/></label><label>Course<select value={courseFilter} onChange={e => setCourseFilter(e.target.value)}><option value="">All courses</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>{data.calendars.map(calendar => <div key={calendar.id} className={styles.permissionRow}><label className={styles.checkbox}><input type="checkbox" checked={filters === null || filters.includes(calendar.id)} onChange={e => setFilters(e.target.checked ? [...new Set([...(filters || data.calendars.map(c=>c.id)), calendar.id])] : (filters || data.calendars.map(c=>c.id)).filter(id => id !== calendar.id))}/>{calendar.title}</label><label>Buddy access<select value={`${calendar.permission.read}:${calendar.permission.edit}`} onChange={async e => { setBusy(true); try { const [read, edit] = e.target.value.split(':'); await calendarApi.permission(calendar, read as 'none' | 'busy_only' | 'details', edit as 'ask' | 'allow'); data.refresh(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Permission could not save.'); } finally { setBusy(false); } }} disabled={busy}><option value="none:ask">No access</option><option value="busy_only:ask">Busy/free only</option><option value="details:ask">Read details; ask before editing</option><option value="details:allow">Allow ordinary edits</option></select></label></div>)}<CalendarSources calendars={data.calendars} onChanged={data.refresh}/></div> : null}
    {data.error ? <div role="alert" className={styles.error}>{data.error}<button onClick={data.refresh}>Retry</button>{data.updatedAt ? <small>Last refreshed {new Date(data.updatedAt * 1000).toLocaleTimeString()}</small> : null}</div> : null}
    {notice ? <div role="status" className={styles.notice}>{notice}{operation?.undoUntil && operation.undoUntil > (data.updatedAt || 0) ? <button disabled={busy} onClick={async () => { setBusy(true); try { await calendarApi.undo(operation.id, crypto.randomUUID()); setNotice('Change undone.'); setOperation(null); window.dispatchEvent(new Event(CALENDAR_CHANGED)); data.refresh(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Undo failed.'); } finally { setBusy(false); } }}>Undo</button> : null}<button aria-label="Dismiss calendar notice" onClick={() => setNotice('')}>×</button></div> : null}
    {tab === 'routines' ? <CalendarRoutines calendars={data.calendars} courses={courses} zone={zone} onStart={(courseId,title)=>onStudy({id:courseId,calendarId:data.calendars[0]?.id||'',title,type:'study',temporal:{mode:'deadline',timezone:zone,dueDate:day},courseId,busy:false,revision:1})}/> : <div className={view === 'week' ? styles.calendarContent : styles.calendarScroll}>
      <div className={styles.calendarScroll}>
      {data.loading ? <div role="status" className={styles.empty}>Loading your schedule…</div> : view === 'agenda' ? <div className={styles.agenda}>{days.map(date => <section key={date}><header><strong>{labelDay(date, { weekday: 'long', month: 'short', day: 'numeric' })}</strong><button aria-label={`Add event on ${date}`} onClick={() => setForm({ day: date })}><Plus size={16}/></button></header>{events.filter(e => occursOnDate(e, date, zone)).map(e => eventButton(e))}{!events.some(e => occursOnDate(e, date, zone)) && !data.error ? <p className={styles.free}>Nothing scheduled.</p> : null}</section>)}</div> : view === 'month' ? <div className={styles.month}>{days.map(date => <div key={date} className={`${styles.monthDay} ${date === today ? styles.today : ''}`}><button className={styles.dateButton} onClick={() => updateDate(date, 'agenda')}>{labelDay(date, { weekday: 'short', day: 'numeric' })}</button>{events.filter(e => occursOnDate(e, date, zone)).slice(0, 3).map(e => eventButton(e, true))}{events.filter(e => occursOnDate(e, date, zone)).length > 3 ? <button onClick={() => updateDate(date, 'agenda')}>More events</button> : null}</div>)}</div> : <CalendarTimeline days={days} events={events} zone={zone} calendars={data.calendars} onSelect={event=>{setSelected(event);setCancelScope(event.recurrence?'occurrence':'series');}} onAdd={date=>setForm({day:date})} onDay={date=>updateDate(date,'agenda')}/>}
      </div>
      {view === 'week' ? <aside className={styles.routineRail} aria-label="Study routines"><CalendarRoutines compact calendars={data.calendars} courses={courses} zone={zone} onStart={(courseId,title)=>onStudy({id:courseId,calendarId:data.calendars[0]?.id||'',title,type:'study',temporal:{mode:'deadline',timezone:zone,dueDate:day},courseId,busy:false,revision:1})}/></aside> : null}
    </div>}
    {selected ? <Dialog open onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className={styles.detailDialog}><DialogHeader><DialogTitle>{selected.title}</DialogTitle><DialogDescription>{eventTime(selected, zone)} · {eventDay(selected, zone)} · {zone}</DialogDescription></DialogHeader><p className={styles.detailMeta}>{selected.type}{selected.recurrence ? ' · Repeating' : ''} · {selected.sourceType === 'academic' ? 'Course schedule' : 'Open Learn'}</p>{selected.description ? <p>{selected.description}</p> : null}{selected.location ? <p>{selected.location}</p> : null}{selected.url ? <a href={selected.url} target="_blank" rel="noopener noreferrer">Open event link</a> : null}{selected.courseId ? <Button variant="outline" onClick={() => { onCourse(selected.courseId!); setSelected(null); }}>Open course</Button> : null}<Button variant="outline" onClick={() => { onStudy(selected); setSelected(null); }}>Prepare with Buddy</Button>{selected.canEdit ? <><Button onClick={() => { setForm({ day: eventDay(selected, zone), event: selected }); setSelected(null); }}>Edit event</Button>{selected.recurrence ? <label className={styles.form}>Cancel<select value={cancelScope} onChange={e => setCancelScope(e.target.value)}><option value="occurrence">This occurrence</option><option value="future">This and future</option><option value="series">Entire series</option></select></label> : null}<Button variant="ghost" disabled={busy} onClick={() => void remove()}>Cancel {selected.recurrence && cancelScope === 'occurrence' ? 'occurrence' : 'event'}</Button></> : <p>Update this event through its course source.</p>}</DialogContent></Dialog> : null}
    {form ? <CalendarEventForm key={form.event?.id || form.day} {...form} zone={zone} calendars={data.calendars} courses={courses} onClose={() => setForm(null)} onSaved={saved}/> : null}
  </section>;
}
