'use client';
import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { calendarApi, CALENDAR_CHANGED, dateKey, wallInstant, type CalendarEvent, type StudentCalendar, type CalendarOperation } from '@/lib/calendar-client';
import type { CourseSummary } from '@/lib/api';
import styles from './calendar.module.css';

function wallValue(value: string | null | undefined, zone: string, day: string, hour = '09:00') {
  if (!value) return `${day}T${hour}`;
  const date = new Date(value);
  return `${dateKey(date, zone)}T${new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date)}`;
}

export function CalendarEventForm({ event, day, zone, calendars, courses, onClose, onSaved }: { event?: CalendarEvent; day: string; zone: string; calendars: StudentCalendar[]; courses: CourseSummary[]; onClose: () => void; onSaved: (operation: CalendarOperation) => void }) {
  const [title, setTitle] = useState(event?.title || '');
  const [type, setType] = useState(event?.type || 'study');
  const [mode, setMode] = useState(event?.temporal.mode || 'timed');
  const [timezone, setTimezone] = useState(event?.temporal.timezone || zone);
  const [calendarId, setCalendarId] = useState(event?.calendarId || calendars.find(c => c.canEdit)?.id || '');
  const [courseId, setCourseId] = useState(event?.courseId || '');
  const [start, setStart] = useState(wallValue(event?.temporal.start || event?.temporal.dueAt, timezone, day));
  const [end, setEnd] = useState(wallValue(event?.temporal.end, timezone, day, '09:30'));
  const [startDate, setStartDate] = useState(event?.temporal.startDate || event?.temporal.dueDate || day);
  const [endDate, setEndDate] = useState(event?.temporal.endDate || new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10));
  const [description, setDescription] = useState(event?.description || '');
  const [location, setLocation] = useState(event?.location || '');
  const [url, setUrl] = useState(event?.url || '');
  const [busyTime, setBusyTime] = useState(event?.busy ?? true);
  const [recurrence, setRecurrence] = useState(event?.recurrence || '');
  const [scope, setScope] = useState(event?.recurrence ? 'occurrence' : 'series');
  const [reminder, setReminder] = useState(String(event?.reminderMinutes?.[0] ?? -1));
  const [error, setError] = useState(''), [saving, setSaving] = useState(false);
  const [pendingKey, setPendingKey] = useState<{ hash: string; key: string } | null>(null);
  async function save() {
    setSaving(true); setError('');
    try {
      const temporal = mode === 'timed' ? { mode, timezone, start: wallInstant(start, timezone), end: wallInstant(end, timezone) } : mode === 'all_day' ? { mode, timezone, startDate, endDate } : { mode, timezone, dueDate: startDate };
      const value = { title: title.trim(), type, calendarId, courseId: courseId || null, temporal, description, location, url, busy: mode === 'deadline' ? false : busyTime, recurrence: recurrence || null, reminderMinutes: Number(reminder) >= 0 ? [Number(reminder)] : [] };
      const hash = JSON.stringify({ value, scope }); const key = pendingKey?.hash === hash ? pendingKey.key : crypto.randomUUID(); setPendingKey({ hash, key });
      const operation = await calendarApi.save(value, key, event, scope);
      window.dispatchEvent(new Event(CALENDAR_CHANGED)); onSaved(operation); onClose();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save event.'); }
    finally { setSaving(false); }
  }
  async function changeScope(value: string) {
    setScope(value);
    if (value === 'series' && event) {
      try { const base = await calendarApi.event(event.eventId || event.id); setStart(wallValue(base.temporal.start, timezone, day)); setEnd(wallValue(base.temporal.end, timezone, day, '09:30')); setStartDate(base.temporal.startDate || base.temporal.dueDate || day); setEndDate(base.temporal.endDate || endDate); }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load series.'); }
    }
  }
  return <Dialog open onOpenChange={open => { if (!open && !saving) onClose(); }}><DialogContent className={styles.formDialog}>
    <DialogHeader><DialogTitle>{event ? 'Edit event' : 'Add event'}</DialogTitle><DialogDescription>Plan time for your classes, deadlines, and studying.</DialogDescription></DialogHeader>
    <form onSubmit={e => { e.preventDefault(); void save(); }} className={styles.form}>
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      <label>Title<input autoFocus required maxLength={300} value={title} onChange={e => setTitle(e.target.value)} placeholder="Physics revision" /></label>
      <div className={styles.formRow}><label>Type<select value={type} onChange={e => setType(e.target.value)}>{['class', 'assignment', 'exam', 'study', 'reminder', 'personal'].map(t => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}</select></label><label>Calendar<select value={calendarId} onChange={e => setCalendarId(e.target.value)}>{calendars.filter(c => c.canEdit).map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label></div>
      <label>Course<select value={courseId} onChange={e => setCourseId(e.target.value)}><option value="">No course</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      {event?.recurrence ? <label>Apply changes to<select value={scope} onChange={e => void changeScope(e.target.value)}><option value="occurrence">This occurrence</option><option value="future">This and future occurrences</option><option value="series">Entire series</option></select></label> : null}
      <label>Timing<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="timed">Date and time</option><option value="all_day">All day</option><option value="deadline">Deadline (date only)</option></select></label>
      <div className={styles.formRow}>{mode === 'timed' ? <><label>Starts<input type="datetime-local" required value={start} onChange={e => setStart(e.target.value)}/></label><label>Ends<input type="datetime-local" required value={end} onChange={e => setEnd(e.target.value)}/></label></> : <><label>{mode === 'deadline' ? 'Due date' : 'Starts'}<input type="date" required value={startDate} onChange={e => setStartDate(e.target.value)}/></label>{mode === 'all_day' ? <label>Ends (exclusive)<input type="date" required value={endDate} onChange={e => setEndDate(e.target.value)}/></label> : null}</>}</div>
      <label>Timezone<input required value={timezone} onChange={e => setTimezone(e.target.value)} list="calendar-timezones"/><datalist id="calendar-timezones">{['UTC', 'America/Los_Angeles', 'America/New_York', 'Europe/London', 'Asia/Kolkata'].map(z => <option key={z} value={z}/>)}</datalist></label>
      {scope !== 'occurrence' || !event?.recurrence ? <label>Repeat<select value={recurrence} onChange={e => setRecurrence(e.target.value)}><option value="">Does not repeat</option><option value="FREQ=DAILY">Every day</option><option value="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR">Weekdays</option><option value="FREQ=WEEKLY">Every week</option><option value="FREQ=MONTHLY">Every month</option>{recurrence && !['FREQ=DAILY', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', 'FREQ=WEEKLY', 'FREQ=MONTHLY'].includes(recurrence) ? <option value={recurrence}>Existing custom schedule</option> : null}</select></label> : null}
      <label>Reminder<select value={reminder} onChange={e => setReminder(e.target.value)}><option value="-1">No reminder</option><option value="0">At event time</option><option value="10">10 minutes before</option><option value="30">30 minutes before</option><option value="1440">1 day before</option></select></label>
      <label>Location<input value={location} onChange={e => setLocation(e.target.value)}/></label><label>Link<input type="url" value={url} onChange={e => setUrl(e.target.value)}/></label><label>Notes<textarea rows={3} value={description} onChange={e => setDescription(e.target.value)}/></label>
      {mode !== 'deadline' ? <label className={styles.checkbox}><input type="checkbox" checked={busyTime} onChange={e => setBusyTime(e.target.checked)}/>Reserve this time</label> : null}
      <footer><Button type="button" variant="ghost" disabled={saving} onClick={onClose}>Cancel</Button><Button disabled={saving || !title.trim() || !calendarId}>{saving ? 'Saving…' : 'Save event'}</Button></footer>
    </form>
  </DialogContent></Dialog>;
}
