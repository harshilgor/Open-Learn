'use client';
import {useEffect,useRef,useState} from 'react';
import {Button} from './ui/button';
import {request} from '@/lib/api';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import {finishedTask,type BrowserTask} from '@/lib/browser-assistant';
import styles from './browser-assistant.module.css';

type View={kind:'local'|'cloud';url?:string;expiresAt?:number;generation:string;message?:string};
type Preview={state:'waiting'|'available';message?:string;title?:string;url?:string;observedAt?:number;blocks?:{text:string}[];image?:string};
export function BrowserControlPanel({task}:{task:BrowserTask}) {
  const [view,setView]=useState<View|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const epoch=useRef(0),dialog=useRef<HTMLDialogElement>(null);
  const [preview,setPreview]=useState<Preview|null>(null);
  const control=task.browserControl;
  const state=control?.owner || 'agent';
  useEffect(()=>{
    const sequence=epoch;
    const clear=()=>{sequence.current++;setView(null);setPreview(null);setError('');dialog.current?.close?.();};
    window.addEventListener(ACCOUNT_CHANGED,clear);
    return()=>{sequence.current++;window.removeEventListener(ACCOUNT_CHANGED,clear);};
  },[task.id,control?.generation,state]);
  useEffect(()=>{
    if(!view?.expiresAt)return;
    const timer=window.setTimeout(()=>{setView(null);dialog.current?.close?.();},Math.max(0,view.expiresAt*1000-Date.now()));
    return()=>window.clearTimeout(timer);
  },[view]);
  async function command(action:'takeover'|'return_control') {
    const current=epoch.current;setBusy(true);setError('');setView(null);setPreview(null);dialog.current?.close?.();
    try {
      await request(`/v1/assistant/tasks/${task.id}/commands`,{method:'POST',body:JSON.stringify({action,expectedRevision:task.revision})});
      if(current===epoch.current)window.dispatchEvent(new Event('openlearn-browser-task-changed'));
    } catch(cause){if(current===epoch.current)setError(cause instanceof Error?cause.message:'Could not change browser control.');}
    finally{setBusy(false);}
  }
  async function openView() {
    const current=epoch.current;setBusy(true);setError('');
    try {
      const result=await request<View>(`/v1/assistant/tasks/${task.id}/browser-view`);
      if(current===epoch.current && result.generation===control?.generation)setView(result);
    } catch(cause){if(current===epoch.current)setError(cause instanceof Error?cause.message:'Browser view unavailable.');}
    finally{setBusy(false);}
  }
  async function inspect() {
    const current=epoch.current;setBusy(true);setError('');
    try {
      const result=await request<Preview>(`/v1/assistant/tasks/${task.id}/browser-preview`);
      if(current===epoch.current)setPreview(result);
    }catch(cause){if(current===epoch.current)setError(cause instanceof Error?cause.message:'Page observation unavailable.');}
    finally{setBusy(false);}
  }
  if(finishedTask(task.status) || !task.connectionId)return null;
  const currentView=state==='human' && view?.generation===control?.generation?view:null;
  return <div className={styles.control} aria-label="Browser control">
    <p role="status">{state==='requesting'?'Waiting for automation to stop. If the desktop is offline, reconnect it.':state==='human'?'You control the browser. Automation is paused.':state==='returning'?'Closing the human session before automation reconnects.':'Browser automation controls the connected session.'}</p>
    <div className={styles.actions}>
      {state==='agent'?<Button variant="outline" disabled={busy} onClick={()=>void command('takeover')}>Take control</Button>:null}
      {state==='agent'?<Button variant="ghost" disabled={busy || task.status==='waiting_for_login'} onClick={()=>void inspect()}>Inspect browser</Button>:null}
      {state==='human'?<Button variant="outline" disabled={busy} onClick={()=>void openView()}>Open browser</Button>:null}
      {state==='human' || state==='returning'?<Button disabled={busy} onClick={()=>void command('return_control')}>Return control</Button>:null}
    </div>
    {state==='agent' && preview?<div aria-label="Read-only browser observation">
      {preview.state==='waiting'?<p>{preview.message}</p>:<><p><strong>{preview.title || 'Observed page'}</strong> · {preview.observedAt?new Date(preview.observedAt*1000).toLocaleTimeString():''}</p><p className={styles.muted}>Latest retained observation · {preview.url}</p>{preview.blocks?.map((block,index)=><p key={index}>{block.text}</p>)}{preview.image?
      /* Authenticated inline evidence must not enter an external image optimizer. */
      // eslint-disable-next-line @next/next/no-img-element
      <img className={styles.browserImage} src={preview.image} alt="Last verified browser screenshot"/>:null}</>}
    </div>:null}
    {currentView?.kind==='local'?<p>{currentView.message} Phone access waits for the paired desktop.</p>:null}
    {currentView?.kind==='cloud' && currentView.url?<>
      <p className={styles.muted}>This private view expires shortly. Returning control reconnects the browser and checks the page again.</p>
      <iframe className={styles.browserFrame} title="Browser under your control" src={currentView.url} referrerPolicy="no-referrer" allow="clipboard-read; clipboard-write"/>
      <Button variant="outline" onClick={()=>dialog.current?.showModal()}>Full-screen browser</Button>
      <dialog ref={dialog} className={styles.browserDialog}>
        <Button variant="outline" onClick={()=>dialog.current?.close()}>Close full-screen</Button>
        <iframe className={styles.browserFrame} title="Full-screen browser under your control" src={currentView.url} referrerPolicy="no-referrer" allow="clipboard-read; clipboard-write"/>
      </dialog>
    </>:null}
    {error?<p role="alert" className={styles.error}>{error}</p>:null}
  </div>;
}
