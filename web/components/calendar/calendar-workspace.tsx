'use client';
import { useEffect, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Globe2, Plus, Repeat2, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { useCalendar } from '@/hooks/use-calendar';
import { calendarApi, CALENDAR_CHANGED, dateKey, eventDay, eventTime, wallInstant, type CalendarEvent, type CalendarOperation, type CalendarTemporal } from '@/lib/calendar-client';
import type { QuickAddDraft } from '@/lib/calendar-quick-add';
import type { CourseSummary } from '@/lib/api';
import { request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { CalendarRoutines } from './calendar-routines';
import { CalendarEventForm, type CalendarEventDefaults } from './calendar-event-form';
import { CalendarMiniMonth } from './calendar-mini-month';
import { CalendarQuickAdd } from './calendar-quick-add';
import styles from './calendar.module.css';
import { CalendarSources } from './calendar-sources';
import { CalendarTimeline, eventCategory } from './calendar-timeline';
import { occursOnDate, shiftMonth } from '@/lib/calendar-layout';

type View = 'week' | 'month' | 'day' | 'agenda';
const addDay = (day: string, amount: number) => new Date(Date.parse(`${day}T12:00:00Z`) + amount * 86400000).toISOString().slice(0, 10);
const labelDay = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
const VIEWS: Array<{ value: View; label: string }> = [{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }, { value: 'agenda', label: 'Agenda' }];
/** Title for the visible range: "October 2026", "Oct 12 – 18, 2026" or "Tuesday, October 13". */
function rangeTitle(view: View, first: string, last: string, day: string) {
  if (view === 'month') return labelDay(day, { month: 'long', year: 'numeric' });
  if (view === 'day') return labelDay(day, { weekday: 'long', month: 'long', day: 'numeric' });
  const format = new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' });
  return format.formatRange(new Date(`${first}T12:00:00Z`), new Date(`${last}T12:00:00Z`));
}

export function CalendarWorkspace({ courses, onCourse, onStudy }: { courses: CourseSummary[]; onCourse: (id: string) => void; onStudy: (event: CalendarEvent) => void }) {
  const [zone, setZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [day, setDay] = useState(() => dateKey(new Date(), zone));
  const [view, setView] = useState<View>('week');
  const [selected, setSelected] = useState<CalendarEvent | null>(null);
  const [form, setForm] = useState<{ day: string; time?: string; endDay?: string; endTime?: string; defaults?: CalendarEventDefaults; event?: CalendarEvent } | null>(null);
  // A dragged event shows at its new time until the next schedule load replaces the list it was moved in.
  const [moved, setMoved] = useState<{ items: CalendarEvent[]; id: string; temporal: CalendarTemporal } | null>(null);
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
  const items = moved && moved.items === data.items ? data.items.map(item => item.id === moved.id ? { ...item, temporal: moved.temporal } : item) : data.items;
  const events = items.filter(item => (filters === null || filters.includes(item.calendarId)) && (!courseFilter || item.courseId === courseFilter));
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
    let loading = false;
    const refreshOperation = () => {
      if (document.hidden || loading || controller.signal.aborted) return;
      loading = true;
      void request<CalendarOperation & { reasonCode?: string }>(`/v1/calendar/operations/${encodeURIComponent(operation.id)}`, { signal: controller.signal }).then(receipt => {
        if (controller.signal.aborted) return;
        if (receipt.status === 'applied') { setOperation(receipt); setNotice('Google confirmed your calendar change.'); data.refresh(); }
        else if (['failed', 'outcome_unknown'].includes(receipt.status)) { setOperation(receipt); setNotice(receipt.status === 'outcome_unknown' ? 'Google may have applied this change. Its outcome needs reconciliation; it will not be sent again automatically.' : 'Google could not apply this change. Refresh the event before retrying.'); }
      }).catch(() => {}).finally(() => { loading = false; });
    };
    const timer = window.setInterval(refreshOperation, 3000);
    document.addEventListener('visibilitychange', refreshOperation);
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', refreshOperation); };
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
  /** Persist a drag-and-drop move through the same save API as the edit form, keeping the duration. */
  async function move(event: CalendarEvent, date: string, time: string) {
    let temporal: CalendarTemporal;
    try {
      const start = wallInstant(`${date}T${time}`, zone);
      temporal = { mode: 'timed', timezone: event.temporal.timezone || zone, start, end: new Date(Date.parse(start) + Date.parse(event.temporal.end!) - Date.parse(event.temporal.start!)).toISOString() };
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Could not move event.'); return; }
    setMoved({ items: data.items, id: event.id, temporal }); setBusy(true); setNotice('');
    try {
      const value = { title: event.title, type: event.type, calendarId: event.calendarId, courseId: event.courseId || null, temporal, description: event.description || '', location: event.location || '', url: event.url || '', busy: event.busy, recurrence: event.recurrence || null, reminderMinutes: event.reminderMinutes || [] };
      saved(await calendarApi.save(value, crypto.randomUUID(), event, event.recurrence ? 'occurrence' : 'series'));
      window.dispatchEvent(new Event(CALENDAR_CHANGED));
    } catch (cause) { setMoved(null); setNotice(cause instanceof Error ? cause.message : 'Could not move event.'); }
    finally { setBusy(false); }
  }
  function draft({ title, type, mode, ...when }: QuickAddDraft) { setForm({ ...when, defaults: { title, type, mode } }); }
  const eventButton = (event: CalendarEvent, compact = false) => <button key={event.id} type="button" className={`${styles.event} ${compact ? styles.compactEvent : ''}`} data-category={eventCategory(event)} onClick={() => { setSelected(event); setCancelScope(event.recurrence ? 'occurrence' : 'series'); }} title={compact ? `${event.title} · ${eventTime(event, zone)}` : undefined}>{compact ? <><strong>{event.title}</strong><span>{eventTime(event, zone)}</span></> : <><span className={styles.eventTime}>{eventTime(event, zone)}{event.recurrence ? <Repeat2 size={12} aria-label="Repeats"/> : null}</span><span className={styles.eventBody}><strong>{event.title}</strong><small>{courses.find(c => c.id === event.courseId)?.name || event.type[0].toUpperCase() + event.type.slice(1)}</small></span></>}</button>;
  const title = rangeTitle(view, days[0], days[days.length - 1], day);

  return <section className={styles.workspace} aria-label="Student calendar">
    <header className={styles.toolbar}>
      <div className={styles.toolbarNav}>
        <Button variant="outline" size="sm" onClick={() => updateDate(today)}>Today</Button>
        <div className={styles.stepper}>
          <Button variant="ghost" size="icon-sm" aria-label="Previous dates" onClick={() => updateDate(view === 'month' ? shiftMonth(day,-1) : addDay(day,-length))}><ChevronLeft size={18}/></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Next dates" onClick={() => updateDate(view === 'month' ? shiftMonth(day,1) : addDay(day,length))}><ChevronRight size={18}/></Button>
        </div>
        <h1 aria-live="polite">{title}</h1>
      </div>
      <CalendarQuickAdd today={today} onDraft={draft}/>
      <div className={styles.controls}>
        <div className={styles.segmented} role="radiogroup" aria-label="Calendar view">{VIEWS.map(option => <button key={option.value} type="button" role="radio" aria-checked={view === option.value} onClick={() => updateDate(day, option.value)}>{option.label}</button>)}</div>
        <Button variant="ghost" size="icon-sm" aria-label="Calendar filters and Buddy permissions" aria-expanded={filterOpen} title="Filters and permissions" onClick={() => setFilterOpen(!filterOpen)}><Settings2 size={17}/></Button>
        <Button size="sm" aria-label="Add event" onClick={() => setForm({ day })}><Plus size={16}/><span className={styles.addLabel}>Add event</span></Button>
      </div>
    </header>
    <div className={styles.subnav} role="tablist" aria-label="Calendar sections"><button type="button" role="tab" aria-selected={tab === 'calendar'} onClick={() => setTab('calendar')}><CalendarDays size={15}/>Calendar</button><button type="button" role="tab" aria-selected={tab === 'routines'} onClick={() => setTab('routines')}><Repeat2 size={15}/>Routines</button><span title="Display timezone"><Globe2 size={13}/>{zone}</span></div>
    {filterOpen ? <div className={styles.filters}><label>Display timezone<input value={zone} onChange={e => { try { new Intl.DateTimeFormat(undefined, { timeZone: e.target.value }); setZone(e.target.value); } catch { setNotice('Choose a valid IANA timezone.'); } }}/></label><label>Course<select value={courseFilter} onChange={e => setCourseFilter(e.target.value)}><option value="">All courses</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>{data.calendars.map(calendar => <div key={calendar.id} className={styles.permissionRow}><label className={styles.checkbox}><input type="checkbox" checked={filters === null || filters.includes(calendar.id)} onChange={e => setFilters(e.target.checked ? [...new Set([...(filters || data.calendars.map(c=>c.id)), calendar.id])] : (filters || data.calendars.map(c=>c.id)).filter(id => id !== calendar.id))}/>{calendar.title}</label><label>Buddy access<select value={`${calendar.permission.read}:${calendar.permission.edit}`} onChange={async e => { setBusy(true); try { const [read, edit] = e.target.value.split(':'); await calendarApi.permission(calendar, read as 'none' | 'busy_only' | 'details', edit as 'ask' | 'allow'); data.refresh(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Permission could not save.'); } finally { setBusy(false); } }} disabled={busy}><option value="none:ask">No access</option><option value="busy_only:ask">Busy/free only</option><option value="details:ask">Read details; ask before editing</option><option value="details:allow">Allow ordinary edits</option></select></label></div>)}<CalendarSources calendars={data.calendars} onChanged={data.refresh}/></div> : null}
    {data.error ? <div role="alert" className={styles.error}>{data.error}<button onClick={data.refresh}>Retry</button>{data.updatedAt ? <small>Last refreshed {new Date(data.updatedAt * 1000).toLocaleTimeString()}</small> : null}</div> : null}
    {notice ? <div role="status" className={styles.notice}>{notice}{operation?.undoUntil && operation.undoUntil > (data.updatedAt || 0) ? <button disabled={busy} onClick={async () => { setBusy(true); try { await calendarApi.undo(operation.id, crypto.randomUUID()); setNotice('Change undone.'); setOperation(null); window.dispatchEvent(new Event(CALENDAR_CHANGED)); data.refresh(); } catch (cause) { setNotice(cause instanceof Error ? cause.message : 'Undo failed.'); } finally { setBusy(false); } }}>Undo</button> : null}<button aria-label="Dismiss calendar notice" onClick={() => setNotice('')}>×</button></div> : null}
    {tab === 'routines' ? <CalendarRoutines calendars={data.calendars} courses={courses} zone={zone} onStart={(courseId,title)=>onStudy({id:courseId,calendarId:data.calendars[0]?.id||'',title,type:'study',temporal:{mode:'deadline',timezone:zone,dueDate:day},courseId,busy:false,revision:1})}/> : <div className={view === 'week' || view === 'day' ? styles.calendarContent : styles.calendarScroll} data-view={view}>
      <div className={styles.calendarScroll}>
      {data.loading ? <div role="status" className={styles.empty}>Loading your schedule…</div> : view === 'agenda' ? <div className={styles.agenda}>{days.map(date => <section key={date} className={date === today ? styles.agendaToday : ''}><header><div className={styles.agendaDate}><strong>{labelDay(date, { day: 'numeric' })}</strong><span>{labelDay(date, { weekday: 'long' })}<small>{labelDay(date, { month: 'long' })}{date === today ? ' · Today' : ''}</small></span></div><button type="button" aria-label={`Add event on ${date}`} onClick={() => setForm({ day: date })}><Plus size={16}/></button></header>{events.filter(e => occursOnDate(e, date, zone)).map(e => eventButton(e))}{!events.some(e => occursOnDate(e, date, zone)) && !data.error ? <p className={styles.free}>Nothing scheduled.</p> : null}</section>)}</div> : view === 'month' ? <div className={styles.monthWrap}><div className={styles.monthWeekdays} aria-hidden="true">{days.slice(0, 7).map(date => <span key={date}>{labelDay(date, { weekday: 'short' })}</span>)}</div><div className={styles.month}>{days.map(date => { const dayEvents = events.filter(e => occursOnDate(e, date, zone)); return <div key={date} className={`${styles.monthDay} ${date === today ? styles.today : ''} ${date.slice(0, 7) !== day.slice(0, 7) ? styles.outsideMonth : ''}`}><button type="button" className={styles.dateButton} aria-current={date === today ? 'date' : undefined} aria-label={labelDay(date, { weekday: 'long', month: 'long', day: 'numeric' })} onClick={() => updateDate(date, 'day')}>{labelDay(date, { day: 'numeric' })}</button>{dayEvents.slice(0, 3).map(e => eventButton(e, true))}{dayEvents.length > 3 ? <button type="button" className={styles.moreEvents} onClick={() => updateDate(date, 'day')}>+{dayEvents.length - 3} more</button> : null}</div>; })}</div></div> : <CalendarTimeline days={days} events={events} zone={zone} calendars={data.calendars} onSelect={event=>{setSelected(event);setCancelScope(event.recurrence?'occurrence':'series');}} onAdd={(date,time,until)=>setForm({day:date,time,endDay:until?.day,endTime:until?.time})} onMove={(event,date,time)=>void move(event,date,time)} onDay={date=>updateDate(date,'day')}/>}
      </div>
      {view === 'week' || view === 'day' ? <aside className={styles.routineRail} aria-label={view === 'week' ? 'Date navigator and study routines' : 'Date navigator'}><CalendarMiniMonth day={day} today={today} rangeStart={days[0]} rangeEnd={end} onPick={date => updateDate(date)}/>{view === 'week' ? <CalendarRoutines compact calendars={data.calendars} courses={courses} zone={zone} onStart={(courseId,title)=>onStudy({id:courseId,calendarId:data.calendars[0]?.id||'',title,type:'study',temporal:{mode:'deadline',timezone:zone,dueDate:day},courseId,busy:false,revision:1})}/> : null}</aside> : null}
    </div>}
    {selected ? <Dialog open onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className={styles.detailDialog}><DialogHeader><DialogTitle>{selected.title}</DialogTitle><DialogDescription>{eventTime(selected, zone)} · {eventDay(selected, zone)} · {zone}</DialogDescription></DialogHeader><p className={styles.detailMeta}>{selected.type}{selected.recurrence ? ' · Repeating' : ''} · {selected.sourceType === 'academic' ? 'Course schedule' : 'Open Learn'}</p>{selected.description ? <p>{selected.description}</p> : null}{selected.location ? <p>{selected.location}</p> : null}{selected.url ? <a href={selected.url} target="_blank" rel="noopener noreferrer">Open event link</a> : null}{selected.courseId ? <Button variant="outline" onClick={() => { onCourse(selected.courseId!); setSelected(null); }}>Open course</Button> : null}<Button variant="outline" onClick={() => { onStudy(selected); setSelected(null); }}>Prepare with Buddy</Button>{selected.canEdit ? <><Button onClick={() => { setForm({ day: eventDay(selected, zone), event: selected }); setSelected(null); }}>Edit event</Button>{selected.recurrence ? <label className={styles.form}>Cancel<select value={cancelScope} onChange={e => setCancelScope(e.target.value)}><option value="occurrence">This occurrence</option><option value="future">This and future</option><option value="series">Entire series</option></select></label> : null}<Button variant="ghost" disabled={busy} onClick={() => void remove()}>Cancel {selected.recurrence && cancelScope === 'occurrence' ? 'occurrence' : 'event'}</Button></> : <p>Update this event through its course source.</p>}</DialogContent></Dialog> : null}
    {form ? <CalendarEventForm key={form.event?.id || `${form.day}-${form.time}-${form.endTime}-${form.defaults?.title}`} {...form} zone={zone} calendars={data.calendars} courses={courses} onClose={() => setForm(null)} onSaved={saved}/> : null}
  </section>;
}
