'use client';
import {useEffect,useState} from 'react';
import {Button} from './ui/button';
import {RichContent} from './rich-content';
import {request} from '@/lib/api';
import {finishedTask,SITE_CHANGED,type BrowserTask,type SiteConnection} from '@/lib/browser-assistant';
import {SiteConnections} from './site-connections';
import {BrowserControlPanel} from './browser-control-panel';
import styles from './browser-assistant.module.css';

export function BrowserTaskCard({task,onCommand}:{task:BrowserTask;onCommand:(task:BrowserTask,action:'pause'|'cancel'|'resume'|'resolve',connectionId?:string,answer?:string,courseId?:string)=>Promise<void>}) {
  const [sites,setSites]=useState<SiteConnection[]>([]),[selected,setSelected]=useState(''),[answer,setAnswer]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [courses,setCourses]=useState<{id:string;name:string}[]>([]),[selectedCourse,setSelectedCourse]=useState('');
  const waiting=task.status.startsWith('waiting') || task.status==='paused';
  useEffect(()=>{
    if(!waiting)return;
    let live=true;
    const refresh=()=>void request<{connections:SiteConnection[]}>('/v1/site-connections').then(result=>{if(live){setSites(result.connections);setSelected(current=>current || task.connectionId || result.connections.find(c=>c.preferred)?.id || '');}}).catch(e=>{if(live)setError(e.message);});
    if(['course_required','ambiguous_course'].includes(task.error || ''))void request<{id:string;name:string}[]>('/v1/courses').then(result=>{if(live)setCourses(result);}).catch(e=>{if(live)setError(e.message);});
    refresh();window.addEventListener(SITE_CHANGED,refresh);
    return()=>{live=false;window.removeEventListener(SITE_CHANGED,refresh);};
  },[waiting,task.connectionId,task.error]);
  const command=async(action:'pause'|'cancel'|'resume'|'resolve')=>{setBusy(true);try{await onCommand(task,action,selected || undefined,answer || undefined,selectedCourse || undefined);}finally{setBusy(false);}};
  return <section className={styles.panel} aria-label="Website assistant task">
    <div className={styles.header}><h3>Website assistant</h3><span className={styles.status}>{task.status.replaceAll('_',' ')}</span></div>
    <p className={styles.question}>{task.message}</p>
    {!finishedTask(task.status) && !waiting ? <p role="status" className={styles.muted}>Reading the relevant pages… {task.actionsUsed ? `${task.actionsUsed} steps checked.` : 'Preparing the connection.'}</p> : null}
    {task.question ? <p role="status">{task.question}</p> : null}
    {task.summary ? <RichContent body={task.summary}/> : null}
    {task.facts.length ? <ul className={styles.list}>{task.facts.map((fact,index)=><li className={styles.fact} key={`${fact.entityId || fact.title}-${index}`}><strong>{fact.title}</strong><p>{fact.date?.value || 'Date not confirmed'}{fact.date?.kind==='date_only'?' · time not specified':''}{fact.conflict?' · conflicting sources':''}{fact.saved===false?' · not saved':''}</p>{fact.source?.locator?.startsWith('https://')?<a href={fact.source.locator} target="_blank" rel="noopener noreferrer">View source</a>:null}{fact.source?.quote?<details><summary>Supporting passage</summary><p className={styles.quote}>{fact.source.quote}</p></details>:null}</li>)}</ul>:null}
    {task.studyTasks?.length?<ul className={styles.list}>{task.studyTasks.map(activity=><li key={activity.id}><a href={`/courses/${activity.courseId}`}>{activity.reason}</a></li>)}</ul>:null}
    {task.coverage?.length ? <details className={styles.muted}><summary>Sources checked · {task.coverage.filter(c=>!c.complete).length} with incomplete coverage</summary><ul>{task.coverage.map(c=><li key={c.key}>{c.key} · {c.complete?'read completely':'partial or unverified'}</li>)}</ul></details>:null}
    <BrowserControlPanel key={`${task.id}:${task.browserControl?.generation || 'agent'}:${task.browserControl?.owner || 'agent'}`} task={task}/>
    {waiting && (!task.browserControl || task.browserControl.owner==='agent')?<div className={styles.form}>
      <label>Website<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Choose a website</option>{sites.map(site=><option key={site.id} value={site.id}>{site.label}</option>)}</select></label>
      {['course_required','ambiguous_course'].includes(task.error || '')?<label>Save to course<select value={selectedCourse} onChange={e=>setSelectedCourse(e.target.value)}><option value="">Choose a course</option>{courses.map(course=><option key={course.id} value={course.id}>{course.name}</option>)}</select></label>:null}
      {['clarification_required','ambiguous_event'].includes(task.error || '')?<label>Your answer<input value={answer} onChange={e=>setAnswer(e.target.value)}/></label>:null}
      <div className={styles.actions}><Button disabled={busy} onClick={()=>void command('resume')}>Continue</Button><Button variant="ghost" disabled={busy} onClick={()=>void command('cancel')}>Stop</Button></div>
      {['connection_required','device_offline','capability_unavailable','account_changed','origin_not_approved','login_required'].includes(task.error || '')?<SiteConnections compact/>:null}
    </div>:!finishedTask(task.status)?<div className={styles.actions}>{!task.browserControl || task.browserControl.owner==='agent'?<Button variant="outline" disabled={busy} onClick={()=>void command('pause')}>Pause</Button>:null}<Button variant="ghost" disabled={busy} onClick={()=>void command('cancel')}>Stop</Button></div>:null}
    {error?<p className={styles.error} role="alert">{error}</p>:null}
  </section>;
}
