"use client";
import { useCallback, useEffect, useState } from 'react';
import {openWorkspaceFlashcards} from '@/lib/workspace-events';
import { request } from '@/lib/api';
import { Bell } from 'lucide-react';
import { Button } from './ui/button';
import { useBuddies } from './buddies';
import {RoutineControls} from './routine-controls';
import {ReminderDeliveryStatus} from './reminder-delivery-status';
type Reminder={kind:'academic'|'chat'|'routine';url?:string;lastError?:string;id:string;dueAt:number;status:string;title:string;courseId:string|null;buddyId:string};
const when=(seconds:number)=>new Intl.DateTimeFormat(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(seconds*1000));
const tone=(status:string)=>status==='pending'?'brand':status==='failed'?'danger':undefined;
const label=(value:string)=>value.charAt(0).toUpperCase()+value.slice(1).replaceAll('_',' ');
export function BuddyReminders({initialReminderId,onCourse}:{initialReminderId?:string|null;onCourse?:(id:string)=>void}){const [flashcardNotices,setFlashcardNotices]=useState<{id:string;title:string;body:string;status:string}[]>([]);const [items,setItems]=useState<Reminder[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const {snapshot,refresh}=useBuddies();const [filter,setFilter]=useState('');const [selected,setSelected]=useState(initialReminderId||'');const [busyId,setBusyId]=useState('');
 const load=useCallback(async()=>{setLoading(true);try{const result=await request<{reminders:Reminder[]}>('/v1/buddies/reminders');setItems(result.reminders);const cards=await request<{notifications:{id:string;title:string;body:string;status:string}[]}>('/v1/flashcard-notifications');setFlashcardNotices(cards.notifications);setError('');await request('/v1/buddies/reminders/read',{method:'POST',body:JSON.stringify({reminderIds:result.reminders.filter(item=>!initialReminderId||item.id===initialReminderId).slice(0,1000).map(item=>item.id)})});await refresh();}catch(e){setError(e instanceof Error?e.message:'Could not load reminders.');}finally{setLoading(false);}},[refresh,initialReminderId]);
 async function action(item:Reminder,verb:'cancel'|'snooze'){setBusyId(item.id);try{await request(`/v1/reminders/${item.id}/${verb}`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:verb==='snooze'?JSON.stringify({minutes:60}):undefined});await load();}catch(e){setError(e instanceof Error?e.message:'Could not update reminder.');}finally{setBusyId('');}}
 useEffect(()=>{const timer=setTimeout(()=>void load(),0);const poll=setInterval(()=>void load(),30000);return()=>{clearTimeout(timer);clearInterval(poll);};},[load]);
 const visible=items.filter(item=>(!filter||item.buddyId===filter)&&(!selected||item.id===selected));
 return <section className="ol-page ol-page-narrow" aria-labelledby="reminders-title">
  <header className="ol-page-header"><div><h1 id="reminders-title">Reminders</h1><p>Upcoming nudges from your Buddies, courses and chats.</p></div>
   <div className="ol-page-actions">{snapshot?.profiles.length?<label className="ol-field">Buddy<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="">All Buddies</option>{snapshot.profiles.map(buddy=><option key={buddy.id} value={buddy.id}>{buddy.name}</option>)}</select></label>:null}{selected?<Button variant="ghost" size="sm" onClick={()=>setSelected('')}>Show all reminders</Button>:null}</div></header>
  {error?<p role="alert" className="ol-card ol-card-padded ol-row-meta">{error}<Button size="sm" variant="outline" onClick={()=>void load()}>Retry</Button></p>:null}
  {flashcardNotices.length?<div className="ol-section"><h2>Flashcards</h2><div className="ol-card ol-list">{flashcardNotices.map(notice=><article className="ol-row" key={notice.id}><div className="ol-row-main"><strong>{notice.title}</strong><span className="ol-row-meta">{notice.body}</span></div><div className="ol-row-actions"><Button size="sm" onClick={()=>openWorkspaceFlashcards({view:'library'})}>Review flashcards</Button><Button size="sm" variant="ghost" onClick={()=>void request(`/v1/assistant/notifications/${notice.id}/ack`,{method:'POST'}).then(()=>void load())}>Mark read</Button></div></article>)}</div></div>:null}
  <div className="ol-section"><h2>Upcoming{visible.length?<small>{visible.length}</small>:null}</h2>
   {loading&&!items.length?<p role="status" className="ol-card ol-card-padded ol-row-meta">Loading reminders…</p>:null}
   {!loading&&!error&&!items.length?<div className="ol-card ol-empty"><Bell aria-hidden="true"/><h3>No reminders yet</h3><p>Ask your Buddy to remind you about something, or turn on reminders in a course’s settings.</p></div>:null}
   {visible.length?<div className="ol-card ol-list">{visible.map(item=><article key={item.id} className="ol-row"><div className="ol-row-main"><strong>{item.title}</strong><span className="ol-row-meta"><span>{when(item.dueAt)}</span><span aria-hidden="true">·</span><span>{snapshot?.profiles.find(p=>p.id===item.buddyId)?.name||'Buddy'}</span><span className="ol-badge" data-tone={tone(item.status)}>{label(item.status)}</span>{item.kind!=='chat'?<span className="ol-badge">{label(item.kind)}</span>:null}</span><ReminderDeliveryStatus id={item.id}/>{item.lastError?<span role="status" className="ol-row-meta">This reminder needs attention.</span>:null}</div>
    <div className="ol-row-actions">{item.url&&item.status==='delivered'?<Button asChild size="sm" variant="outline"><a href={item.url}>Open activity</a></Button>:null}{item.courseId&&onCourse?<Button size="sm" variant="outline" onClick={()=>onCourse(item.courseId!)}>Open course</Button>:null}{['pending','delivered'].includes(item.status)?<Button size="sm" variant="outline" disabled={busyId===item.id} onClick={()=>void action(item,'snooze')}>Snooze 1 hour</Button>:null}{item.status==='pending'?<Button size="sm" variant="ghost" disabled={busyId===item.id} onClick={()=>void action(item,'cancel')}>{item.kind==='routine'?'Cancel routine':'Cancel'}</Button>:null}</div></article>)}</div>:null}
  </div>
  <RoutineControls/>
 </section>;
}
