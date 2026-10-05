"use client";
import {useEffect,useRef,useState} from 'react';
import {learningApi,type WorkspaceNoteSummary} from '@/lib/api';
import {snapshot,sendCommand,type AgentTask} from '@/lib/assistant-client';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import {flashcardsApi,type FlashcardSourceRef,type FlashcardGeneration} from '@/lib/flashcards-client';
import {openWorkspaceFlashcards} from '@/lib/workspace-events';
import {Button} from './ui/button';
import styles from './flashcards.module.css';

export function FlashcardTaskCard({task,onChanged}:{task:AgentTask;onChanged?:()=>void}){
 const [error,setError]=useState('');
 return <article className={styles.task} aria-label="Flashcard preparation"><strong>{task.summary||'Preparing your flashcards'}</strong><p role="status">{task.status.replaceAll('_',' ')} · {task.phase.replaceAll('_',' ')}</p>{task.deckId?<Button onClick={()=>openWorkspaceFlashcards({deckId:task.deckId,view:'editor'})}>Preview deck</Button>:null}{task.allowedCommands.filter(a=>['pause','resume','cancel'].includes(a)).map(action=><Button variant="outline" key={action} onClick={()=>void sendCommand(task,{commandId:crypto.randomUUID(),action}).then(()=>onChanged?.()).catch(e=>setError(e.message))}>{action==='cancel'?'Stop preparation':action}</Button>)}{error?<p role="alert">{error}</p>:null}</article>;
}

export function MakeFlashcards({sessionId,courseId,sourceRefs,origin='conversation',label='Make flashcards'}:{sessionId?:string|null;courseId?:string|null;sourceRefs?:FlashcardSourceRef[];origin?:FlashcardGeneration['origin'];label?:string}){
 const [open,setOpen]=useState(false),[notes,setNotes]=useState<WorkspaceNoteSummary[]>([]),[selected,setSelected]=useState(''),[count,setCount]=useState(12),[type,setType]=useState('both'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[task,setTask]=useState<AgentTask|null>(null);
 const pending=useRef<FlashcardGeneration|null>(null),epoch=useRef(0);
 useEffect(()=>{const clear=()=>{epoch.current++;pending.current=null;setTask(null);setOpen(false);setNotes([]);setError('');};window.addEventListener(ACCOUNT_CHANGED,clear);return()=>{epoch.current++;window.removeEventListener(ACCOUNT_CHANGED,clear);};},[]);
 useEffect(()=>{if(!open||sourceRefs?.length)return;let active=true;void learningApi.listWorkspaceNotes().then(value=>{if(active)setNotes(value.filter(n=>!courseId||!n.frontmatter?.course_id||n.frontmatter.course_id===courseId));}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[open,sourceRefs,courseId]);
 useEffect(()=>{if(!task||!['queued','running'].includes(task.status))return;let active=true,inflight=false;const update=async()=>{if(inflight)return;inflight=true;try{const value=await snapshot(task.sessionId);if(active){const next=value.tasks.find(t=>t.id===task.id);if(next)setTask(next);}}catch(e){if(active)setError(e instanceof Error?e.message:'Connection interrupted.');}finally{inflight=false;}};const timer=setInterval(()=>void update(),2000);void update();return()=>{active=false;clearInterval(timer);};},[task]);
 async function create(){setBusy(true);setError('');const generation=epoch.current;try{
  if(!pending.current){let sid=sessionId;if(!sid)sid=(await learningApi.createSession({topic:'Flashcard study',goal:'Create source-grounded flashcards',courseId:courseId||undefined})).id;
   const note=notes.find(n=>n.id===selected);const refs=sourceRefs?.length?sourceRefs:note?[{kind:'note' as const,id:note.id,revision:note.revision}]:[];
   if(!refs.length)throw new Error('Choose a saved source first.');
   pending.current={sessionId:sid,courseId:courseId||undefined,origin,sourceRefs:refs,requestedCount:count,cardTypes:type==='both'?['qa','cloze']:[type as 'qa'|'cloze'],clientCommandId:crypto.randomUUID()};
  }
  const intent=pending.current;const result=await flashcardsApi.generate(intent);const value=await snapshot(intent.sessionId);if(generation!==epoch.current)return;
  setTask(value.tasks.find(t=>t.id===result.references.find(r=>r.kind==='task')?.id)||null);pending.current=null;
 }catch(e){if(generation===epoch.current)setError(e instanceof Error?e.message:'Could not create cards.');}finally{if(generation===epoch.current)setBusy(false);}}
 return <div className={styles.create}><Button variant="outline" onClick={()=>setOpen(value=>!value)}>{label}</Button>{open?<div className={styles.createForm}>{!sourceRefs?.length?<label>Saved source<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Choose a note</option>{notes.map(note=><option key={note.id} value={note.id}>{note.title}</option>)}</select></label>:<p>Cards will use the selected, saved source revision.</p>}<label>Maximum cards<input type="number" min={1} max={60} value={count} onChange={e=>setCount(Number(e.target.value))}/></label><label>Card style<select value={type} onChange={e=>setType(e.target.value)}><option value="both">Question/answer and cloze</option><option value="qa">Question/answer</option><option value="cloze">Cloze deletion</option></select></label><Button disabled={busy||count<1||count>60} onClick={()=>void create()}>{busy?'Submitting…':pending.current?'Retry original request':'Prepare draft'}</Button>{error?<p role="alert">{error}</p>:null}</div>:null}{task?<FlashcardTaskCard task={task} onChanged={()=>void snapshot(task.sessionId).then(value=>setTask(value.tasks.find(t=>t.id===task.id)||null))}/>:null}</div>;
}
