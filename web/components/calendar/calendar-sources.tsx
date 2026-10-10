'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { CALENDAR_CHANGED, type StudentCalendar } from '@/lib/calendar-client';
import { Button } from '../ui/button';
import styles from './calendar.module.css';

type Connection = { id: string; email: string; status: string; capabilities: string[] };
type RemoteCalendar = { providerCalendarId: string; title: string; role: string };

export function CalendarSources({ calendars, onChanged }: { calendars: StudentCalendar[]; onChanged: () => void }) {
  const [accounts, setAccounts] = useState<Connection[]>([]), [remote, setRemote] = useState<RemoteCalendar[]>([]), [selectedAccount, setSelectedAccount] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false), [allowWrite, setAllowWrite] = useState(false);
  const epoch = useRef(0);
  const load = useCallback(async () => { const version = ++epoch.current; try { const result = await request<{ items: Connection[] }>('/v1/assistant/app-connections', { cache: 'no-store' }); if (epoch.current === version) setAccounts(result.items.filter(a => a.status === 'connected')); } catch (cause) { if (epoch.current === version) setError(cause instanceof Error ? cause.message : 'Connected accounts unavailable.'); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); const reset = () => { epoch.current++; setAccounts([]); setRemote([]); setSelectedAccount(''); void load(); }; const focus = () => void load(); window.addEventListener('focus', focus); window.addEventListener(ACCOUNT_CHANGED, reset); return () => { window.clearTimeout(timer); epoch.current++; window.removeEventListener('focus', focus); window.removeEventListener(ACCOUNT_CHANGED, reset); }; }, [load]);
  async function connect() {
    setBusy(true); setError('');
    try { const result = await request<{ authorizationUrl: string }>('/v1/assistant/app-connections/google/authorize', { method: 'POST', body: JSON.stringify({ capabilities: ['calendar_list', 'calendar_read', ...(allowWrite ? ['calendar_write'] : [])] }) }); const url = new URL(result.authorizationUrl); if (url.origin !== 'https://accounts.google.com') throw new Error('Invalid sign-in destination.'); window.open(url.href, '_blank', 'noopener,noreferrer'); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not connect Google.'); }
    finally { setBusy(false); }
  }
  async function discover(id: string) { setBusy(true); setError(''); setSelectedAccount(id); setRemote([]); try { const result = await request<{ items: RemoteCalendar[] }>(`/v1/calendar/google/${encodeURIComponent(id)}/calendars`); setRemote(result.items); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Calendar discovery unavailable.'); } finally { setBusy(false); } }
  async function select(calendar: RemoteCalendar) {
    setBusy(true); setError('');
    try { const chosen = await request<StudentCalendar>('/v1/calendar/google/calendars', { method: 'POST', body: JSON.stringify({ connectionId: selectedAccount, providerCalendarId: calendar.providerCalendarId }) }); for (let i = 0; i < 20; i++) { const result = await request<{ status: string }>(`/v1/calendar/calendars/${encodeURIComponent(chosen.id)}/sync`, { method: 'POST' }); if (result.status !== 'pending') break; } window.dispatchEvent(new Event(CALENDAR_CHANGED)); onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not sync calendar.'); }
    finally { setBusy(false); }
  }
  return <section className={styles.sources}><h3>Connected calendars</h3><p>Choose calendars to display. Buddy access is controlled separately for each calendar.</p><label className={styles.checkbox}><input type="checkbox" checked={allowWrite} onChange={e => setAllowWrite(e.target.checked)}/>Request Google event edit access</label><Button size="sm" variant="outline" disabled={busy} onClick={() => void connect()}>Connect Google Calendar</Button>{accounts.map(account => <button key={account.id} disabled={busy} onClick={() => void discover(account.id)}>{account.email}{account.capabilities.includes('calendar_list') ? ' · Choose calendars' : ' · Reconnect to discover calendars'}</button>)}{remote.map(calendar => <div key={calendar.providerCalendarId}><span>{calendar.title} · {calendar.role}</span><Button size="sm" disabled={busy} onClick={() => void select(calendar)}>Add and sync</Button></div>)}{calendars.filter(c => c.source === 'google').map(calendar => <div key={calendar.id}><span>{calendar.title}</span><Button size="sm" variant="ghost" disabled={busy} onClick={async () => { setBusy(true); try { await request(`/v1/calendar/calendars/${encodeURIComponent(calendar.id)}/sync`, { method: 'POST' }); onChanged(); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Refresh failed.'); } finally { setBusy(false); } }}>Refresh</Button></div>)}{error ? <p role="alert" className={styles.error}>{error}</p> : null}</section>;
}
