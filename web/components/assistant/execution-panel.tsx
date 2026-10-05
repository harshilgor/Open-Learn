'use client';
import {FlashcardTaskCard,MakeFlashcards} from '../flashcard-create';
import {ResponsibilitiesPanel} from './responsibilities-panel';
import {useCallback,useEffect,useRef,useState} from 'react';
import {learningApi,request} from '@/lib/api';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import {snapshot,sendMessage,sendCommand,downloadArtifact,type AgentTask,type Activity} from '@/lib/assistant-client';
import {ResearchSourceList} from './research-sources';
import {LearningContinuationPanel} from './learning-continuation';
import {ConnectedTaskPanel} from './connected-task-panel';
import styles from './execution-panel.module.css';

type Pending={key:string;body:Record<string,unknown>;taskId?:string};
const prefix='openlearn-agent-pending:';

export function ExecutionPanel({sessionId,onSession,courseId}:{sessionId:string|null;onSession:(id:string)=>void;courseId?:string|null}){
  const [tasks,setTasks]=useState<AgentTask[]>([]),[items,setItems]=useState<Activity[]>([]);
  const [enabled,setEnabled]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [kind,setKind]=useState('lab_analysis'),[query,setQuery]=useState(''),[csv,setCsv]=useState('trial,distance,time\n1,10,2\n2,20,4\n3,999,1\n');
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [hasPending,setHasPending]=useState(false);
  const [sandboxState,setSandboxState]=useState('setup_required');
  const [sandboxFixture,setSandboxFixture]=useState(false);
  const generation=useRef(0),pending=useRef<Pending|null>(null),cursor=useRef<number|undefined>(undefined);
  const refresh=useCallback(async()=>{
    if(!sessionId)return;
    const epoch=generation.current;let page=await snapshot(sessionId,cursor.current);
    const collected=[...page.items];
    while(page.hasMore){page=await snapshot(sessionId,page.cursor);collected.push(...page.items);}
    if(epoch!==generation.current)return;
    cursor.current=page.cursor;setTasks(page.tasks);
    setItems(previous=>{const map=new Map(previous.map(item=>[item.id,item]));for(const item of collected)map.set(item.id,item);return [...map.values()].sort((a,b)=>a.sequence-b.sequence);});
  },[sessionId]);
  useEffect(()=>{
    generation.current++;cursor.current=undefined;
    let stopped=false,inflight=false;
    const invalidate=()=>{generation.current++;};
    const update=()=>{if(inflight)return;inflight=true;void refresh().catch(cause=>{if(!stopped)setError(cause.message);}).finally(()=>{inflight=false;});};
    const timer=window.setTimeout(()=>{setTasks([]);setItems([]);setError('');update();},0);
    void request<{admissionEnabled:boolean;capabilities?:{name:string;state:string;runtime?:string}[]}>('/v1/assistant/execution-capabilities').then(value=>{if(!stopped){setEnabled(value.admissionEnabled);const sandbox=value.capabilities?.find(capability=>capability.name==='sandbox_lab');setSandboxState(sandbox?.state||'setup_required');setSandboxFixture(sandbox?.runtime==='offline_sandbox_fixture');}}).catch(()=>undefined);
    const interval=window.setInterval(update,2000);
    const clear=()=>{
      generation.current++;cursor.current=undefined;pending.current=null;setHasPending(false);setTasks([]);setItems([]);setAnswers({});setQuery('');setEnabled(false);
      for(let at=sessionStorage.length-1;at>=0;at--){const key=sessionStorage.key(at);if(key?.startsWith(prefix))sessionStorage.removeItem(key);}
    };
    window.addEventListener(ACCOUNT_CHANGED,clear);
    return()=>{stopped=true;invalidate();window.clearTimeout(timer);window.clearInterval(interval);window.removeEventListener(ACCOUNT_CHANGED,clear);};
  },[refresh]);

  async function submit(body:Record<string,unknown>,taskId?:string){
    if(busy)return;
    setBusy(true);setError('');const epoch=generation.current;
    try{
      let sid=sessionId;
      if(!sid){sid=(await learningApi.createSession({topic:'Agent workspace',goal:'Analyze data and conduct research',courseId:courseId||undefined})).id;onSession(sid);}
      const storageKey=prefix+sid;
      const saved=sessionStorage.getItem(storageKey);
      const next=pending.current || (saved?JSON.parse(saved) as Pending:null) || {key:crypto.randomUUID(),body:{schemaVersion:2,clientMessageId:crypto.randomUUID(),sessionId:sid,...body},taskId};
      if(JSON.stringify({...next.body,clientMessageId:undefined})!==JSON.stringify({schemaVersion:2,clientMessageId:undefined,sessionId:sid,...body}))throw new Error('An earlier message still needs retry. Retry its original content before sending a changed request.');
      pending.current=next;setHasPending(true);sessionStorage.setItem(storageKey,JSON.stringify(next));
      await sendMessage(next.body,next.key);
      pending.current=null;setHasPending(false);sessionStorage.removeItem(storageKey);
      if(epoch===generation.current){if(taskId)setAnswers(previous=>({...previous,[taskId]:''}));else setQuery('');await refresh();}
    }catch(cause){if(epoch===generation.current)setError(cause instanceof Error?cause.message:'Could not send the request.');}
    finally{setBusy(false);}
  }

  async function control(task:AgentTask,action:string){
    setBusy(true);setError('');
    try{await sendCommand(task,{commandId:crypto.randomUUID(),action});await refresh();}
    catch(cause){setError(cause instanceof Error?cause.message:'Task changed. Refresh before trying again.');await refresh();}
    finally{setBusy(false);}
  }

  if(!enabled&&!tasks.length)return null;
  return <section aria-label="Agent execution" className={styles.panel}>
    <MakeFlashcards sessionId={sessionId} courseId={courseId}/><ResponsibilitiesPanel sessionId={sessionId} courseId={courseId}/>
    <details><summary>Agent workspace</summary><p>Lab analysis runs offline with a fixed CSV adapter. Daytona runs the same verified analysis remotely when configured. Research uses configured evidence sources. Tasks keep running when this conversation closes.</p>
      {sandboxFixture?<p>Offline sandbox fixture: no live Daytona calls.</p>:null}
      {enabled?<form onSubmit={event=>{event.preventDefault();void submit({capability:kind,text:query.trim()||'Analyze this lab CSV',...(kind!=='research'?{csvText:csv}:{researchSpec:{query:query,sourcePolicy:'attached_preferred'}})});}}>
        <label>Task type <select value={kind} onChange={event=>setKind(event.target.value)}><option value="lab_analysis">Lab CSV analysis</option><option value="research">Research</option><option value="sandbox_lab" disabled={sandboxState!=='available'}>{sandboxFixture?'Offline sandbox CSV fixture':'Daytona CSV analysis'}{sandboxState!=='available'?' — setup required':''}</option></select></label>
        <label>Request <input aria-label="Agent request" value={query} onChange={event=>setQuery(event.target.value)} placeholder={kind==='research'?'Compare the evidence for spaced repetition':'Analyze this lab CSV'}/></label>
        {kind!=='research'?<label>CSV (time in seconds)<textarea aria-label="Lab CSV" rows={4} value={csv} onChange={event=>setCsv(event.target.value)}/></label>:null}
        <button disabled={busy||(kind==='research'&&!query.trim())||(kind==='sandbox_lab'&&sandboxState!=='available')}>Start task</button>
      </form>:<p>New agent tasks are disabled. Existing tasks remain available.</p>}
    </details>
    {items.filter(item=>['user.message','command.applied'].includes(item.type)).map(item=><p key={item.id}>{item.type==='user.message'?'You: ':''}{item.text}</p>)}
    {tasks.map(task=>task.kind==='flashcards'?<FlashcardTaskCard key={task.id} task={task} onChanged={()=>void refresh()}/>:<article key={task.id} aria-label={`Task: ${task.message}`} style={{marginTop:12}}>
      <strong>{task.message}</strong><p role="status">{task.status.replaceAll('_',' ')} · {task.phase}</p>
      {task.summary?<p>{task.summary}</p>:null}
      <ResearchSourceList sources={task.sources||[]}/>
      {task.pendingRequests.map(question=><div key={question.requestId}><p>{question.question}</p>{question.options.map(option=><button type="button" key={option} disabled={busy} onClick={()=>setAnswers(previous=>({...previous,[task.id]:option}))}>{option}</button>)}</div>)}
      {task.allowedCommands.includes('steer')||['completed','completed_partial'].includes(task.status)?<form onSubmit={event=>{event.preventDefault();const question=task.pendingRequests[0];void submit({text:answers[task.id],targetTaskId:task.id,expectedRevision:task.revision,...(question?{replyToRequestId:question.requestId,expectedRequestRevision:question.revision}:{})},task.id);}}>
        <label>{task.pendingRequests.length?'Your answer':'Change the task'}<input aria-label={`Reply to ${task.message}`} value={answers[task.id]||''} onChange={event=>setAnswers(previous=>({...previous,[task.id]:event.target.value}))}/></label>
        <button disabled={busy||!answers[task.id]?.trim()}>{task.pendingRequests.length?'Send answer':task.status.startsWith('completed')?'Create corrected result':'Send change'}</button>
      </form>:null}
      {task.allowedCommands.filter(action=>['pause','resume','cancel'].includes(action)).map(action=><button type="button" key={action} disabled={busy} onClick={()=>void control(task,action)}>{action==='cancel'?'Stop task':action==='pause'?'Pause':'Resume'}</button>)}
      {task.artifacts.map(artifact=><button type="button" key={artifact.id} onClick={()=>void downloadArtifact(artifact).catch(cause=>setError(cause.message))}>Download {artifact.name}</button>)}
      <LearningContinuationPanel task={task}/>
      <ConnectedTaskPanel task={task}/>
    </article>)}
    {error?<p role="alert">{error} Your reply is preserved. Refresh and reconcile a changed task before sending again.</p>:null}
    {hasPending?<button type="button" disabled={busy} onClick={()=>{if(sessionId)sessionStorage.removeItem(prefix+sessionId);pending.current=null;setHasPending(false);setError('Earlier pending intent dismissed. Verify server history before sending changed content.');}}>Reconcile pending message</button>:null}
  </section>;
}
