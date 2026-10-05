'use client';
import {lazy,Suspense,useEffect,useRef,useState} from 'react';
import {request} from '@/lib/api';
import type {AgentTask} from '@/lib/assistant-client';
import {ACCOUNT_CHANGED} from '@/lib/account-session';

const QuizWorkspace=lazy(()=>import('../quiz-workspace').then(module=>({default:module.QuizWorkspace})));
type Continuation={id:string;kind:'teach'|'quiz';status:string;errorCode?:string;quizId?:string;lesson?:{title:string;blocks:{id:string;heading:string;body:string}[]}};

export function LearningContinuationPanel({task}:{task:AgentTask}){
  const [items,setItems]=useState<Continuation[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[quiz,setQuiz]=useState<string|null>(null);
  const path=`/v1/assistant/tasks/${encodeURIComponent(task.id)}/continuations`;
  const epoch=useRef(0);
  const eligible=task.status==='completed'&&task.completion?.status==='verified';
  useEffect(()=>{
    let stopped=false,inflight=false;
    const invalidate=()=>{epoch.current++;};
    const generation=++epoch.current;
    async function update(){
      if(inflight||!eligible)return;inflight=true;
      try{const result=await request<{items:Continuation[]}>(path);if(!stopped&&epoch.current===generation)setItems(result.items||[]);}
      catch(cause){if(!stopped)setError(cause instanceof Error?cause.message:'Learning status unavailable.');}
      finally{inflight=false;}
    }
    void update();const interval=window.setInterval(()=>void update(),3000);
    const clear=()=>{epoch.current++;setItems([]);setQuiz(null);setError('');};
    window.addEventListener(ACCOUNT_CHANGED,clear);
    return()=>{stopped=true;invalidate();window.clearInterval(interval);window.removeEventListener(ACCOUNT_CHANGED,clear);};
  },[path,eligible]);
  async function start(kind:'teach'|'quiz'){
    setBusy(true);setError('');const generation=epoch.current;
    const storageKey=`openlearn-agent-pending:learning:${task.id}:${kind}`;
    try{
      const saved=sessionStorage.getItem(storageKey);
      const pending=saved?JSON.parse(saved) as {key:string;revision:number}:{key:crypto.randomUUID(),revision:task.revision};
      sessionStorage.setItem(storageKey,JSON.stringify(pending));
      const result=await request<Continuation>(path,{method:'POST',headers:{'Idempotency-Key':pending.key},body:JSON.stringify({kind,expectedRevision:pending.revision})});
      if(generation!==epoch.current)return;
      sessionStorage.removeItem(storageKey);setItems(previous=>[...previous.filter(item=>item.id!==result.id),result]);
    }catch(cause){if(generation===epoch.current)setError(cause instanceof Error?cause.message:'Could not request learning.');}
    finally{if(generation===epoch.current)setBusy(false);}
  }
  if(!eligible)return null;
  return <section aria-label="Learn from this result">
    <p>Explain these verified files or practice with the existing quiz flow. Task completion does not establish mastery.</p>
    {(['teach','quiz'] as const).map(kind=>{const item=items.find(value=>value.kind===kind);return <button type="button" key={kind} disabled={busy||!!item&&item.status!=='failed'} onClick={()=>void start(kind)}>{item?.status==='failed'?'Retry ':''}{kind==='teach'?'Explain result':'Create practice quiz'}</button>;})}
    {items.map(item=><div key={item.id}>
      <p role="status">{item.kind==='teach'?'Explanation':'Quiz'}: {item.status}{item.status==='failed'?` · ${item.errorCode||'retry needed'}`:''}</p>
      {item.lesson?<div><strong>{item.lesson.title}</strong>{item.lesson.blocks.map(block=><div key={block.id}><strong>{block.heading}</strong><p style={{whiteSpace:'pre-wrap'}}>{block.body}</p></div>)}</div>:null}
      {item.quizId?<button type="button" onClick={()=>setQuiz(item.quizId!)}>Open practice quiz</button>:null}
    </div>)}
    {quiz?<Suspense fallback={<p role="status">Opening quiz…</p>}><QuizWorkspace sessionId={task.sessionId} quizId={quiz} inline compact/></Suspense>:null}
    {error?<p role="alert">{error}</p>:null}
  </section>;
}
