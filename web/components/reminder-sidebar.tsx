'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bell, CalendarClock, RefreshCw } from 'lucide-react';
import { request } from '@/lib/api';
import { useBuddies } from './buddies';
import styles from './reminder-sidebar.module.css';

type Reminder = {
  id: string; kind: 'chat' | 'routine' | 'academic'; status: string;
  dueAt: number; title: string; body?: string; message?: string;
  timezone?: string; courseId?: string | null; buddyId?: string | null;
  policyId?: string | null; lastError?: string | null;
};
type Routine = {
  id: string; revision: number; active: boolean; message: string;
  timezone: string; buddyId?: string | null; schedule: {type: string; cron?: string; rrule?: string};
};
type ReminderList = {reminders: Reminder[]; routines: Routine[]};

function describeSchedule(routine: Routine) {
  const cron = routine.schedule.cron;
  if (!cron) return routine.schedule.rrule?.replace(/^FREQ=/i, 'Every ').replaceAll(';', ' · ') || 'Scheduled routine';
  const [minute = '0', hour = '0', , , day = '*'] = cron.split(' ');
  const days: Record<string, string> = {'*':'Every day','1-5':'Weekdays','0,6':'Weekends','1':'Every Monday','2':'Every Tuesday','3':'Every Wednesday','4':'Every Thursday','5':'Every Friday','6':'Every Saturday','0':'Every Sunday'};
  const numericTime = /^\d+$/.test(minute) && /^\d+$/.test(hour);
  const clock = numericTime ? `${String(Number(hour) % 12 || 12)}:${String(minute).padStart(2, '0')} ${Number(hour) >= 12 ? 'PM' : 'AM'}` : null;
  return `${days[day] || `Cron: ${cron}`}${clock ? ` · ${clock}` : ''} · ${routine.timezone}`;
}

export function ReminderSidebar() {
  const [data, setData] = useState<ReminderList | null>(null);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState('');
  const {snapshot} = useBuddies();
  const load = useCallback(async () => {
    setError('');
    try { setData(await request<ReminderList>('/v1/reminders')); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load reminders.'); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  async function toggle(item: Routine) {
    setBusyId(item.id);
    setError('');
    try {
      await request(`/v1/reminder-routines/${encodeURIComponent(item.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({expectedRevision: item.revision, action: item.active ? 'pause' : 'resume'}),
      });
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update routine.'); }
    finally { setBusyId(''); }
  }

  const routines = data?.routines || [];
  const reminders = (data?.reminders || []).filter(item => item.kind !== 'routine').sort((a,b) => {
    const pendingA = a.status === 'pending' ? 0 : 1, pendingB = b.status === 'pending' ? 0 : 1;
    return pendingA - pendingB || a.dueAt - b.dueAt;
  });

  return <section className={styles.panel} aria-label="Reminders and routines">
    <header className={styles.header}><span className={styles.icon}><Bell size={16}/></span><div><h2>Reminders</h2><p>Routines and reminders from your study partners</p></div></header>
    {error ? <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={()=>void load()} aria-label="Retry loading reminders"><RefreshCw size={15}/></button></div> : null}
    {!data && !error ? <p className={styles.state} role="status">Loading your reminders…</p> : null}
    {data ? <>
      <section className={styles.section} aria-labelledby="saved-routines-heading">
        <div className={styles.sectionHeading}><h3 id="saved-routines-heading">Routines</h3><span>{routines.length}</span></div>
        {routines.length ? <ul className={styles.list}>{routines.map(item => {
          const next = data.reminders.filter(reminder=>reminder.policyId===item.id&&reminder.status==='pending').sort((a,b)=>a.dueAt-b.dueAt)[0];
          return <li className={styles.card} key={item.id}>
            <div className={styles.copy}><strong>{item.message}</strong><span>{item.active ? (next ? `Next · ${new Date(next.dueAt*1000).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}` : 'On') : 'Paused'}</span><small>{item.buddyId ? `${snapshot?.profiles.find(profile=>profile.id===item.buddyId)?.name || 'Buddy'} · ` : ''}{describeSchedule(item)}</small></div>
            <button type="button" role="switch" aria-checked={item.active} aria-label={`${item.active ? 'Pause' : 'Resume'} ${item.message}`} disabled={busyId===item.id} className={`${styles.switch} ${item.active ? styles.switchOn : ''}`} onClick={()=>void toggle(item)}><span/></button>
          </li>;
        })}</ul> : <p className={styles.empty}>When a study partner saves a recurring routine, it will appear here.</p>}
      </section>
      <section className={styles.section} aria-labelledby="saved-reminders-heading">
        <div className={styles.sectionHeading}><h3 id="saved-reminders-heading">One-time reminders</h3><span>{reminders.filter(item=>item.status==='pending').length} upcoming</span></div>
        {reminders.length ? <ul className={styles.list}>{reminders.map(item=><li className={styles.card} key={item.id}>
          <CalendarClock className={styles.reminderIcon} size={17}/><div className={styles.copy}><strong>{item.title || item.message || 'Study reminder'}</strong><span>{new Date(item.dueAt*1000).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</span><small>{item.status.replaceAll('_',' ')}{item.buddyId ? ` · ${snapshot?.profiles.find(profile=>profile.id===item.buddyId)?.name || 'Buddy'}` : ''}</small></div>
        </li>)}</ul> : <p className={styles.empty}>No one-time reminders saved.</p>}
      </section>
    </> : null}
    <p className={styles.footnote}>Pause a routine here and your study partner will stop scheduling it until you turn it back on.</p>
  </section>;
}
