'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {request} from '@/lib/api';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
type Spec={sessionId:string;courseId:string;goal:string;timezone:string;weekday:number;hour:number;minute:number;schedule:'weekly'|'once'|'events';lectureEvents:boolean;maxRunsPerWeek:number;startsAt:number};
type Responsibility={id:string;revision:number;status:string;spec:Spec;nextOccurrences:number[]};
type Notice={id:string;title:string;url:string;status:string;pushStatus?:string};
type Note={id:string;revision:number;text:string};
export function ResponsibilitiesPanel({sessionId,courseId}:{sessionId:string|null;courseId?:string|null}) {
  const [items,setItems]=useState<Responsibility[]>([]),[notices,setNotices]=useState<Notice[]>([]),[goal,setGoal]=useState('Prepare a short review from my course materials'),[zone,setZone]=useState('America/Los_Angeles'),[weekday,setWeekday]=useState(0),[hour,setHour]=useState(9),[dates,setDates]=useState<number[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [notes,setNotes]=useState<Record<string,Note[]>>({}),[noteText,setNoteText]=useState('');
  const epoch=useRef(0),key=useRef(crypto.randomUUID()),previewed=useRef('');
  const refresh=useCallback(async()=>{
    const version=epoch.current;
    const [work,inbox]=await Promise.all([request<{responsibilities:Responsibility[]}>('/v1/assistant/responsibilities'),request<{notifications:Notice[]}>('/v1/assistant/responsibility-notifications')]);
    if(version===epoch.current){setItems(work.responsibilities || []);setNotices(inbox.notifications || []);}
  },[]);
  useEffect(()=>{
    const sequence=epoch;sequence.current++;
    const clear=()=>{sequence.current++;setItems([]);setNotices([]);setNotes({});setDates([]);setError('');setBusy(false);setNoteText('');key.current=crypto.randomUUID();previewed.current='';};
    const timer=window.setTimeout(()=>void refresh().catch(cause=>setError(cause.message)),0);
    const interval=window.setInterval(()=>void refresh().catch(()=>undefined),10000);
    window.addEventListener(ACCOUNT_CHANGED,clear);
    return()=>{sequence.current++;window.clearTimeout(timer);window.clearInterval(interval);window.removeEventListener(ACCOUNT_CHANGED,clear);};
  },[refresh,sessionId,courseId]);
  const spec=():Spec=>({sessionId:sessionId!,courseId:courseId!,goal,timezone:zone,weekday,hour,minute:0,schedule:'weekly',lectureEvents:true,maxRunsPerWeek:3,startsAt:0});
  async function perform(action:(isCurrent:()=>boolean)=>Promise<unknown>) {
    setBusy(true);setError('');const version=epoch.current;
    try{await action(()=>version===epoch.current);if(version===epoch.current)await refresh();}catch(cause){if(version===epoch.current)setError(cause instanceof Error?cause.message:'Unable to update ongoing work.');}finally{if(version===epoch.current)setBusy(false);}
  }
  return <details aria-label="Ongoing responsibilities"><summary>Ongoing work and notifications</summary>
    <p>Course preparation uses attached materials. Pause stops current and future work; disable keeps the current task running; stop all cancels both.</p>
    {sessionId && courseId?<form onSubmit={event=>{event.preventDefault();void perform(async(isCurrent)=>{
      const value=spec();if(previewed.current!==JSON.stringify(value))throw Error('Preview this schedule before saving.');
      await request('/v1/assistant/responsibilities',{method:'POST',headers:{'Idempotency-Key':key.current},body:JSON.stringify(value)});if(!isCurrent())return;key.current=crypto.randomUUID();setDates([]);previewed.current='';
    });}}>
      <label>Responsibility <input aria-label="Responsibility goal" value={goal} maxLength={400} onChange={e=>{setGoal(e.target.value);setDates([]);}}/></label>
      <label>Timezone <input aria-label="Responsibility timezone" value={zone} onChange={e=>{setZone(e.target.value);setDates([]);}}/></label>
      <label>Weekly day <select value={weekday} onChange={e=>{setWeekday(Number(e.target.value));setDates([]);}}>{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((day,index)=><option key={day} value={index}>{day}</option>)}</select></label>
      <label>Hour <input type="number" min={0} max={23} value={hour} onChange={e=>{setHour(Number(e.target.value));setDates([]);}}/></label>
      <button type="button" disabled={busy} onClick={()=>void perform(async(isCurrent)=>{const value=spec();const result=await request<{nextOccurrences:number[]}>('/v1/assistant/responsibilities/preview',{method:'POST',body:JSON.stringify(value)});if(!isCurrent())return;previewed.current=JSON.stringify(value);setDates(result.nextOccurrences);})}>Preview schedule</button>
      {dates.length?<ul aria-label="Next three occurrences">{dates.map(date=><li key={date}>{new Date(date*1000).toLocaleString(undefined,{timeZone:zone})} · {zone}</li>)}</ul>:null}
      <p>Also checks after finalized lectures. Limit: three runs per week. Quiet hours: 22:00–08:00.</p>
      <button disabled={busy || !dates.length || !goal.trim()}>Save responsibility</button>
    </form>:<p>Open a course conversation to create ongoing work.</p>}
    {!items.length?<p>No ongoing responsibilities yet.</p>:items.map(item=><section key={item.id} aria-label={item.spec.goal}>
      <h4>{item.spec.goal}</h4><p>{item.status} · {item.spec.timezone}</p>
      {item.status!=='cancelled'?<div>{(['pause','disable','resume','stop_all'] as const).map(action=><button key={action} disabled={busy} onClick={()=>void perform(()=>request(`/v1/assistant/responsibilities/${item.id}/commands`,{method:'POST',body:JSON.stringify({action,expectedRevision:item.revision})}))}>{({pause:'Pause responsibility',disable:'Disable future runs',resume:'Resume responsibility',stop_all:'Stop all'})[action]}</button>)}
      <button disabled={busy || !goal.trim()} onClick={()=>void perform(()=>request(`/v1/assistant/responsibilities/${item.id}/commands`,{method:'POST',body:JSON.stringify({action:'edit',expectedRevision:item.revision,spec:{...item.spec,goal}})}))}>Use current goal for future runs</button></div>:null}
      <button onClick={()=>void perform(async(isCurrent)=>{const result=await request<{notes:Note[]}>(`/v1/assistant/responsibilities/${item.id}/notes`);if(!isCurrent())return;setNotes(previous=>({...previous,[item.id]:result.notes}));})}>Inspect operational notes</button>
      {notes[item.id]?.map(note=><p key={note.id}>{note.text}<button onClick={()=>void perform(async(isCurrent)=>{await request(`/v1/assistant/responsibilities/${item.id}/notes/${note.id}?expectedRevision=${note.revision}`,{method:'DELETE'});if(!isCurrent())return;setNotes(previous=>({...previous,[item.id]:previous[item.id].filter(n=>n.id!==note.id)}));})}>Delete note</button><button disabled={!noteText.trim()} onClick={()=>void perform(async(isCurrent)=>{const result=await request<{notes:Note[]}>(`/v1/assistant/responsibilities/${item.id}/notes`,{method:'POST',body:JSON.stringify({id:note.id,expectedRevision:note.revision,text:noteText})});if(!isCurrent())return;setNotes(previous=>({...previous,[item.id]:result.notes}));})}>Replace note with current text</button></p>)}
      <label>Operational note <input value={noteText} maxLength={4000} onChange={e=>setNoteText(e.target.value)}/></label><button disabled={!noteText.trim() || busy} onClick={()=>void perform(async(isCurrent)=>{const result=await request<{notes:Note[]}>(`/v1/assistant/responsibilities/${item.id}/notes`,{method:'POST',body:JSON.stringify({text:noteText})});if(!isCurrent())return;setNotes(previous=>({...previous,[item.id]:result.notes}));setNoteText('');})}>Save private note</button>
    </section>)}
    <h4>Inbox</h4>{!notices.length?<p>No responsibility updates yet.</p>:<ul>{notices.map(notice=><li key={notice.id}><a href={notice.url}>{notice.title}</a> · {notice.status}{notice.pushStatus && notice.pushStatus!=='disabled'?` · Push: ${notice.pushStatus}`:''}<button disabled={busy} onClick={()=>void perform(()=>request(`/v1/notifications/${notice.id}/ack`,{method:'POST'}))}>Mark read</button></li>)}</ul>}
    {error?<p role="alert">{error}</p>:null}
  </details>;
}
