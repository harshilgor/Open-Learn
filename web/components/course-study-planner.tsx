'use client';
import { useCallback, useEffect, useState } from 'react';
import { request } from '@/lib/api';
import { Button } from '@/components/ui/button';
type Entity = {id:string;kind:string;facts:Record<string,{value:unknown;conflict?:boolean}>};
export type Task = {id:string;action:string;status:string;reason:string;revision:number;pinned:boolean;duration:number[];conceptIds:string[];launch:Record<string,unknown>};
type Data = {entities:Entity[];tasks:Task[];plans:{status:string;blocks:{taskId:string;start:number;end:number}[];capacityGaps:{minutes:number}[]}[]};
type Report = {unknownScope:boolean;capabilities:{conceptId:string;capability:string;category:string}[]};
export function CourseStudyPlanner({courseId,onLaunchTask,onLaunchReady}:{courseId:string;onLaunchTask:(task:Task)=>Promise<string>;onLaunchReady:(task:Task,sessionId:string,revision:number)=>void}) {
 const base=`/v1/courses/${encodeURIComponent(courseId)}/academic`;
 const [data,setData]=useState<Data|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [title,setTitle]=useState(''),[kind,setKind]=useState('assessment'),[date,setDate]=useState(''),[concepts,setConcepts]=useState('');
 const [start,setStart]=useState(''),[end,setEnd]=useState(''),[report,setReport]=useState<Report|null>(null);
 const reload=useCallback(async()=>setData(await request<Data>(base)),[base]);
 useEffect(()=>{void reload().catch(e=>setError(e.message));},[reload]);
 async function run(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await reload();}catch(e){setError(e instanceof Error?e.message:'Request failed.');}finally{setBusy(false);}}
 async function add(){
  const resolved=await Promise.all(concepts.split(',').map(s=>s.trim()).filter(Boolean).map(async name=>{const match=await request<{status:string;concept_id?:string}>(`/v1/concepts/resolve?${new URLSearchParams({query:name,course_id:courseId})}`);if(match.status!=='resolved'||!match.concept_id)throw new Error(`Confirm the course topic ${name} in Review course concepts first.`);return {conceptId:match.concept_id,capability:'recall'};}));
  await request(`${base}/observations`,{method:'POST',body:JSON.stringify({kind,fields:{title,...(date?{[kind==='assignment'?'due':'date']:{kind:'date_only',value:date}}:{}),...(kind==='assessment'?{scope:{confirmed:resolved,probable:[],unknown:!concepts.trim()}}:{})},source:{locator:'manual:student-entry',revision:new Date().toISOString()}})});setTitle('');
 }
 async function update(task:Task,status?:string,extra:Record<string,unknown>={}){return request<Task>(`${base}/tasks/${task.id}`,{method:'PATCH',body:JSON.stringify({...(status?{status}:{pinned:!task.pinned}),...extra,revision:task.revision})});}
 async function launch(task:Task){let current=task;if(task.status==='proposed')current=await update(task,'accepted');if(task.action==='assignment'){await update(current,'active');return;}const sessionId=await onLaunchTask(current);const active=await update(current,'active',{sessionId});onLaunchReady(active,sessionId,active.revision);}
 const latest=data?.plans.at(-1);
 return <section className="course-folder-section" aria-label="Study planning"><h2>Academic expectations and study plan</h2>{error?<p role="alert">{error}</p>:null}
 <details><summary>Add an exam or assignment</summary><form onSubmit={e=>{e.preventDefault();void run(add);}}>
 <label>Type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="assessment">Exam</option><option value="assignment">Assignment</option></select></label>
 <label>Title<input required value={title} onChange={e=>setTitle(e.target.value)}/></label><label>Date, if known<input type="date" value={date} onChange={e=>setDate(e.target.value)}/></label>
 {kind==='assessment'?<label>Confirmed topics, separated by commas<input value={concepts} onChange={e=>setConcepts(e.target.value)}/><small>Leave empty when scope is unknown.</small></label>:null}<Button disabled={busy}>Save</Button></form></details>
 <ul>{data?.entities.map(entity=><li key={entity.id}><strong>{String(entity.facts.title?.value||entity.kind)}</strong> · {entity.kind}{Object.values(entity.facts).some(f=>f.conflict)?<p>Conflicting sources need review.</p>:null}{entity.kind==='assessment'?<><Button disabled={busy} variant="outline" onClick={()=>void run(async()=>setReport(await request(`${base}/assessments/${entity.id}/readiness`,{method:'POST'})))}>Evidence report</Button><Button disabled={busy} variant="outline" onClick={()=>void run(async()=>{await request(`${base}/assessments/${entity.id}/tasks`,{method:'POST'});})}>Suggest practice</Button></>:null}</li>)}</ul>
 {report?<div aria-live="polite"><h3>Readiness evidence</h3><p>{report.unknownScope?'Scope is incomplete; this report covers supplied topics.':'Evidence for supplied topics.'}</p><ul>{report.capabilities.map((s,i)=><li key={i}>{s.conceptId}: {s.capability} — {s.category.replaceAll('_',' ')}</li>)}</ul></div>:null}
 <h3>Study activities</h3><ul>{data?.tasks.map(task=><li key={task.id}><strong>{task.action}</strong> · {task.duration.join('–')} minutes · {task.status}<p>{task.reason}</p>{['proposed','accepted','scheduled'].includes(task.status)?<><Button disabled={busy} onClick={()=>void run(()=>launch(task))}>Start activity</Button><Button disabled={busy} variant="ghost" onClick={()=>void run(()=>update(task,'skipped'))}>Skip</Button></>:null}{task.action==='assignment'&&task.status==='active'?<Button disabled={busy} onClick={()=>void run(()=>update(task,'completed'))}>Mark assignment complete</Button>:null}<Button disabled={busy} variant="ghost" onClick={()=>void run(()=>update(task))}>{task.pinned?'Unpin':'Pin'}</Button></li>)}</ul>
 <form onSubmit={e=>{e.preventDefault();void run(async()=>{await request(`${base}/plans`,{method:'POST',body:JSON.stringify({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,windows:[{start:new Date(start).toISOString(),end:new Date(end).toISOString()}],autoAdjust:false})});});}}><label>Study window starts<input required type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label><label>Ends<input required type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label><Button disabled={busy}>Propose schedule</Button></form>
 {latest?<div><p>Schedule {latest.status}</p><ul>{latest.blocks.map(b=><li key={b.taskId}>{new Date(b.start*1000).toLocaleString()} – {new Date(b.end*1000).toLocaleTimeString()} · {data?.tasks.find(t=>t.id===b.taskId)?.reason}</li>)}</ul>{latest.capacityGaps.length?<p role="status">{latest.capacityGaps.reduce((sum,g)=>sum+g.minutes,0)} minutes could not fit. Add availability or shorten optional practice.</p>:null}</div>:null}</section>;
}
