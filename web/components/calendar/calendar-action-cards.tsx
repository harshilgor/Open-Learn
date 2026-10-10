'use client';
import { useEffect, useRef, useState } from 'react';
import { request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { calendarApi, CALENDAR_CHANGED, type CalendarEvent, type CalendarOperation, type StudentCalendar } from '@/lib/calendar-client';
import { Button } from '../ui/button';
import styles from './calendar.module.css';

type Proposal = { id: string; revision: number; status: string; kind?: string; reason?: string; proposalHash: string; calendarIds: string[]; beforeEvents?: (CalendarEvent | null)[]; changes?: { kind: string; event?: CalendarEvent; scope?: string }[]; operationId?: string; expiresAt: number; receipt?: {message:string; calendarAvailability?:{slots:{start:string;end:string}[]}} };

export function CalendarActionCards({ sessionId }: { sessionId?: string | null }) {
  const [items, setItems] = useState<Proposal[]>([]), [calendars, setCalendars] = useState<StudentCalendar[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState('');
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [readModes, setReadModes] = useState<Record<string, 'none' | 'busy_only' | 'details'>>({});
  const [receipts, setReceipts] = useState<Record<string, CalendarOperation>>({});
  const keys = useRef<Record<string, string>>({});
  const reload = useRef<() => void>(() => {});
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController(); let loading = false;
    async function load() {
      if (loading || controller.signal.aborted) return; loading = true;
      try { const [proposals, list] = await Promise.all([request<{ items: Proposal[] }>(`/v1/calendar/proposals?${new URLSearchParams({ sessionId: sessionId! })}`, { signal: controller.signal }), calendarApi.calendars(controller.signal)]); if (!controller.signal.aborted) { setItems(proposals.items.filter(p => ['read_required','awaiting_confirmation','executing','applied'].includes(p.status) || p.kind==='read_result'&&p.status==='completed')); setCalendars(list.items); } }
      catch { /* Do not put background service errors into otherwise unrelated chats. */ }
      finally { loading = false; }
    }
    reload.current = () => void load(); const timer = window.setInterval(() => void load(), 5000); void load();
    const reset = () => { controller.abort(); setItems([]); setCalendars([]); setReceipts({}); setRemember({}); setReadModes({}); keys.current = {}; };
    window.addEventListener(ACCOUNT_CHANGED, reset);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener(ACCOUNT_CHANGED, reset); };
  }, [sessionId]);
  async function decide(item: Proposal, decision: 'allow' | 'cancel') {
    setBusy(item.id); setError('');
    const signature = JSON.stringify([item.id, item.revision, decision, remember]); keys.current[signature] ||= crypto.randomUUID();
    try { const result = await request<CalendarOperation>(`/v1/calendar/proposals/${encodeURIComponent(item.id)}/decision`, { method:'POST', headers:{'Idempotency-Key':keys.current[signature]}, body:JSON.stringify({expectedRevision:item.revision,proposalHash:item.proposalHash,decision,rememberCalendarIds:decision==='allow'?item.calendarIds.filter(id=>remember[`${item.id}:${id}`]):[]}) }); setReceipts(current=>({...current,[item.id]:result})); window.dispatchEvent(new Event(CALENDAR_CHANGED)); reload.current(); }
    catch(cause){setError(cause instanceof Error?cause.message:'Could not apply calendar decision.');} finally{setBusy('');}
  }
  async function allowRead(item: Proposal) {
    setBusy(item.id); setError('');
    try { let allowed = 0; for(const id of item.calendarIds){const calendar=calendars.find(c=>c.id===id);const mode=readModes[id]||'none';if(calendar&&mode!=='none'){await calendarApi.permission(calendar,mode,'ask');allowed++;}}if(!allowed)throw new Error('Choose at least one calendar to read.'); const result=await request<{message:string}>(`/v1/calendar/proposals/${encodeURIComponent(item.id)}/read-retry`,{method:'POST'}); setError(result.message); reload.current(); }
    catch(cause){setError(cause instanceof Error?cause.message:'Calendar permission could not save.');}finally{setBusy('');}
  }
  if(!items.length)return null;
  return <section className={styles.actionCards} aria-label="Buddy calendar actions">{items.map(item=><article key={item.id} className={styles.actionCard}>{item.kind==='read_result'?<><h3>Calendar</h3><p style={{whiteSpace:'pre-wrap'}}>{item.receipt?.message}</p>{item.receipt?.calendarAvailability?.slots.slice(0,5).map(slot=><p key={slot.start}>{new Date(slot.start).toLocaleString()}–{new Date(slot.end).toLocaleTimeString()}</p>)}</>:item.kind==='read_consent'?<><h3>Let Buddy check your calendar?</h3><p>Choose what Buddy can read. This does not allow edits.</p>{item.calendarIds.map(id=><label key={id}>{calendars.find(c=>c.id===id)?.title||'Calendar'}<select value={readModes[id]||'none'} onChange={e=>setReadModes(current=>({...current,[id]:e.target.value as 'none'|'busy_only'|'details'}))}><option value="none">No access</option><option value="busy_only">Busy/free only</option><option value="details">Event details</option></select></label>)}<Button size="sm" disabled={busy===item.id} onClick={()=>void allowRead(item)}>Allow read access and continue</Button></>:<><h3>{item.status==='awaiting_confirmation'?'Allow Buddy to make this change?':item.status==='executing'?'Waiting for Google confirmation':'Calendar change saved'}</h3>{item.reason?<p>{item.reason}</p>:null}{item.changes?.map((change,index)=>{const before=item.beforeEvents?.[index];const event=change.event||before;return <div key={index} className={styles.changePreview}><strong>{change.kind==='cancel'?'Cancel':change.kind==='update'?'Update':'Add'} {event?.title}</strong>{before?<small>Before: {describeTime(before)}</small>:null}{change.event?<small>{change.kind==='update'?'After: ':''}{describeTime(change.event)}</small>:null}<small>{change.scope&&event?.recurrence?`Scope: ${change.scope==='series'?'Entire series':change.scope==='future'?'This and future occurrences':'This occurrence'}`:''}</small></div>;})}{item.status==='awaiting_confirmation'?<>{item.calendarIds.map(id=><label className={styles.checkbox} key={id}><input type="checkbox" checked={!!remember[`${item.id}:${id}`]} onChange={e=>setRemember(current=>({...current,[`${item.id}:${id}`]:e.target.checked}))}/>Don't ask again for changes to my {calendars.find(c=>c.id===id)?.title||'Open Learn'} calendar</label>)}<p className={styles.permissionHint}>Invitations, changes affecting others, and deleting an entire recurring series still need confirmation. Change access anytime in Calendar permissions.</p><div className={styles.controls}><Button size="sm" disabled={busy===item.id} onClick={()=>void decide(item,'allow')}>Allow this change</Button><Button size="sm" variant="ghost" disabled={busy===item.id} onClick={()=>void decide(item,'cancel')}>Cancel</Button></div></>:<div className={styles.controls}><a href="/calendar">View in calendar</a>{receipts[item.id]?.undoUntil?<button disabled={busy===item.id} onClick={async()=>{setBusy(item.id);try{await calendarApi.undo(receipts[item.id].id,crypto.randomUUID());setItems(current=>current.filter(p=>p.id!==item.id));window.dispatchEvent(new Event(CALENDAR_CHANGED));}catch(cause){setError(cause instanceof Error?cause.message:'Undo unavailable.');}finally{setBusy('');}}}>Undo</button>:null}</div>}</> }</article>)}{error?<p role="status" className={styles.notice}>{error}</p>:null}</section>;
}

function describeTime(event: CalendarEvent) { const t=event.temporal; if(t.mode==='all_day')return `${t.startDate} through ${t.endDate} (exclusive), all day`; if(t.mode==='deadline')return `Due ${t.dueDate||t.dueAt}`; return `${new Date(t.start!).toLocaleString(undefined,{timeZone:t.timezone})}–${new Date(t.end!).toLocaleTimeString(undefined,{timeZone:t.timezone,hour:'numeric',minute:'2-digit'})} (${t.timezone})`; }
