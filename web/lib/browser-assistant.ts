'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {request,requestStream} from './api';
import {ACCOUNT_CHANGED} from './account-session';
import {admitConversation} from './conversation-admission';
import type {ConversationReplyTarget} from './conversation-admission';

export type SiteConnection = {id:string;revision:number;label:string;origin:string;status:string;platform:'canvas'|'generic';executor:'local'|'cloud'|'public_fetch';preferred:boolean;cloudLogin?:boolean;timezone:string;aliases:string[];approvedOrigins?:string[];lastSuccessfulSync?:number|null};
export type AcademicFact = {entityId?:string;courseId?:string;title:string;kind:string;date?:{kind:string;value?:string|null}|null;conflict?:boolean;saved?:boolean;source?:{locator:string;quote?:string;revision?:string;extractionMethod?:string;confirmation?:string}};
export type BrowserInputRequest = {requestId:string;taskId:string;revision:number;question:string;required:boolean;inputKind:'text'|'action';state:'open'};
export type BrowserTaskEvent = {sequence:number;type:string;message?:string;status?:string;request?:BrowserInputRequest;tool?:string;createdAt?:number};
export type BrowserTask = {id:string;revision:number;sessionId?:string|null;message:string;status:string;connectionId?:string|null;summary?:string|null;question?:string|null;error?:string|null;facts:AcademicFact[];studyTasks?:{id:string;courseId:string;reason:string}[];coverage:{key:string;complete:boolean;status:string;url:string}[];actionsUsed:number;createdAt:number;pendingRequests?:BrowserInputRequest[];activity?:BrowserTaskEvent[];browserControl?:{owner:'agent'|'requesting'|'human'|'returning';generation:string;executor:'local'|'cloud'}|null};
export type BrowserReplyTarget = ConversationReplyTarget & {question:string};
export const finishedTask = (status:string) => ['completed','completed_partial','cancelled','failed'].includes(status);
export const SITE_CHANGED = 'openlearn-sites-changed';

export function browserReplyTargets(tasks:BrowserTask[]):BrowserReplyTarget[]{
  return tasks.flatMap(task => (task.pendingRequests || [])
    .filter(request => request.state==='open' && request.inputKind==='text' && request.taskId===task.id)
    .map(request => ({targetTaskId:task.id,replyToRequestId:request.requestId,expectedRevision:task.revision,
      expectedRequestRevision:request.revision,question:request.question})));
}

function abortableDelay(ms:number,signal:AbortSignal){
  return new Promise<void>(resolve=>{
    if(signal.aborted){resolve();return;}
    const timer=window.setTimeout(done,ms);
    function done(){signal.removeEventListener('abort',done);window.clearTimeout(timer);resolve();}
    signal.addEventListener('abort',done,{once:true});
  });
}

export function useBrowserAssistant(sessionId:string|null, courseId?:string|null) {
  const [tasks,setTasks] = useState<BrowserTask[]>([]);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [replyTarget,setReplyTargetState] = useState<BrowserReplyTarget|null>(null);
  const [dismissedRequestIds,setDismissedRequestIds] = useState<string[]>([]);
  const alive = useRef(true);
  const generation = useRef(0);
  const eventCursors = useRef(new Map<string,number>());
  const replyTargetRef = useRef<BrowserReplyTarget|null>(null);
  const dismissedRequests = useRef(new Set<string>());
  const refreshTimer = useRef<number|undefined>(undefined);
  const updateDismissedRequest = useCallback((requestId:string,dismiss:boolean) => {
    const next = new Set(dismissedRequests.current);
    if(dismiss)next.add(requestId);else next.delete(requestId);
    dismissedRequests.current=next;
    setDismissedRequestIds([...next]);
  },[]);
  const setReplyTarget = useCallback((target:BrowserReplyTarget|null, dismissCurrent=false) => {
    if(dismissCurrent && replyTargetRef.current) updateDismissedRequest(replyTargetRef.current.replyToRequestId,true);
    if(target) updateDismissedRequest(target.replyToRequestId,false);
    replyTargetRef.current=target;
    setReplyTargetState(target);
  },[updateDismissedRequest]);
  const refresh = useCallback(async ():Promise<BrowserTask[]> => {
    if(!sessionId) return [];
    const current=generation.current;
    const result = await request<{tasks:BrowserTask[]}>(`/v1/assistant/tasks?sessionId=${encodeURIComponent(sessionId)}`);
    const ordered=result.tasks.slice().reverse();
    if(alive.current && current===generation.current) setTasks(previous=>ordered.map(task=>({...task,activity:previous.find(item=>item.id===task.id)?.activity || []})));
    return ordered;
  },[sessionId]);
  useEffect(()=>{
    alive.current=true;
    generation.current++;
    let loading=false;
    // This endpoint is polled to discover real browser tasks. A network failure
    // here does not mean a browser task failed, so keep it out of the task dock.
    // Explicit task commands still report their own errors below.
    const update=()=>{if(loading)return;loading=true;void refresh().catch(()=>undefined).finally(()=>{loading=false;});};
    const timer=window.setTimeout(()=>{setTasks([]);setError('');setNotice('');update();},0);
    const interval=window.setInterval(update,5000);
    const clear=()=>{generation.current++;eventCursors.current.clear();dismissedRequests.current.clear();setDismissedRequestIds([]);setReplyTarget(null);setTasks([]);setError('');setNotice('');update();};
    window.addEventListener(ACCOUNT_CHANGED,clear);
    window.addEventListener('openlearn-browser-task-changed',update);
    return()=>{alive.current=false;window.clearTimeout(timer);window.clearInterval(interval);window.removeEventListener(ACCOUNT_CHANGED,clear);window.removeEventListener('openlearn-browser-task-changed',update);};
  },[refresh,setReplyTarget]);

  const activeTaskKey=tasks.filter(task=>!finishedTask(task.status)).map(task=>task.id).sort().join('|');
  useEffect(()=>{
    if(!activeTaskKey)return;
    const controllers=new Map<string,AbortController>();
    let disposed=false;
    const refreshSoon=()=>{
      if(refreshTimer.current!==undefined)return;
      refreshTimer.current=window.setTimeout(()=>{refreshTimer.current=undefined;void refresh().catch(()=>undefined);},120);
    };
    async function streamTask(taskId:string,controller:AbortController){
      const {signal}=controller;
      let retry=250;
      while(!signal.aborted && !disposed){
        try{
          const cursor=eventCursors.current.get(taskId)||0;
          const response=await requestStream(`/v1/assistant/tasks/${encodeURIComponent(taskId)}/events?stream=true&after=${cursor}`,{signal,cache:'no-store'});
          if(!response.body)throw new Error('Browser event stream is unavailable.');
          const reader=response.body.getReader(),decoder=new TextDecoder();
          let buffer='';
          while(!signal.aborted){
            const {done,value}=await reader.read();
            if(done)break;
            buffer+=decoder.decode(value,{stream:true}).replaceAll('\r\n','\n');
            let boundary=buffer.indexOf('\n\n');
            while(boundary>=0){
              const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
              let frameId='';let data='';
              for(const line of frame.split('\n')){if(line.startsWith('id:'))frameId=line.slice(3).trim();else if(line.startsWith('data:'))data+=line.slice(5).trim();}
              if(data){
                try{
                  const event=JSON.parse(data) as BrowserTaskEvent;
                  const sequence=Number(event.sequence || frameId);
                  const known=eventCursors.current.get(taskId)||0;
                  if(Number.isFinite(sequence)&&sequence>known){
                    event.sequence=sequence;eventCursors.current.set(taskId,sequence);
                    if(alive.current)setTasks(previous=>previous.map(task=>task.id===taskId?{...task,activity:[...(task.activity||[]),event].slice(-30)}:task));
                    refreshSoon();
                  }
                }catch{/* Ignore malformed replay frames; the snapshot/poll fallback remains authoritative. */}
              }
              boundary=buffer.indexOf('\n\n');
            }
          }
          retry=250;
        }catch{if(signal.aborted || disposed)return;}
        if(!signal.aborted && !disposed){await abortableDelay(retry,signal);retry=Math.min(5000,retry*2);}
      }
    }
    for(const taskId of activeTaskKey.split('|').filter(Boolean)){
      const controller=new AbortController();controllers.set(taskId,controller);void streamTask(taskId,controller);
    }
    return()=>{disposed=true;for(const controller of controllers.values())controller.abort();};
  },[activeTaskKey,refresh]);

  useEffect(()=>{
    const targets=browserReplyTargets(tasks).filter(target=>!dismissedRequests.current.has(target.replyToRequestId));
    const current=replyTargetRef.current;
    if(current){
      const refreshed=targets.find(target=>target.replyToRequestId===current.replyToRequestId);
      if(refreshed){if(refreshed.expectedRevision!==current.expectedRevision)setReplyTarget(refreshed);return;}
      setReplyTarget(null);return;
    }
    if(targets.length===1)setReplyTarget(targets[0]);
  },[tasks,dismissedRequestIds,setReplyTarget]);

  const tryStart = async(message:string,sid:string,attachments:{versionId:string;name:string}[] = [],presentation:'conversation'|'ask'|'learn'|'quiz'='conversation') => {
    const latest=await refresh();
    const scoped=latest.filter(task=>task.sessionId===sid);
    const allTargets=browserReplyTargets(scoped);
    const available=allTargets.filter(target=>!dismissedRequests.current.has(target.replyToRequestId));
    const selected=replyTargetRef.current && available.find(target=>target.replyToRequestId===replyTargetRef.current?.replyToRequestId);
    if(replyTargetRef.current && !selected){setReplyTarget(null);throw new Error('That browser question changed. Review the latest task update before replying.');}
    if(!selected && available.length>1)throw new Error('More than one browser task is waiting for an answer. Choose the question to reply to in Browser activity first.');
    const target=selected || (available.length===1?available[0]:undefined);
    if(target)setReplyTarget(target);
    const admission = await admitConversation(message, sid, courseId, undefined, attachments, presentation, target);
    if (!admission.handled) {
      if(target)throw new Error('Buddy could not apply that reply to the selected website question. Refresh the task and try again.');
      return false;
    }
    if (admission.calendarReceipt) {
      window.dispatchEvent(new Event('openlearn-calendar-changed'));
      if(alive.current)setNotice('');
      return true;
    }
    if (admission.question || admission.message) {
      if (alive.current) setNotice(admission.question || admission.message || '');
    }
    const targetTaskId=target?.targetTaskId || (admission.references as {id?:string}[]|undefined)?.[0]?.id;
    if ((target || admission.runtimeOwner === 'browser_legacy') && targetTaskId) {
      const task = await request<BrowserTask>(`/v1/assistant/tasks/${targetTaskId}`);
      if (alive.current) setTasks(previous=>[...previous.filter(t=>t.id!==task.id),task]);
    }
    if(target)setReplyTarget(null);
    return true;
  };
  const command=async(task:BrowserTask,action:'pause'|'cancel'|'resume'|'resolve',connectionId?:string,answer?:string,courseId?:string)=>{
    try {
      const pending=task.pendingRequests?.find(item=>item.state==='open');
      const updated=await request<BrowserTask>(`/v1/assistant/tasks/${task.id}/commands`,{method:'POST',body:JSON.stringify({action,expectedRevision:task.revision,connectionId,answer,courseId,
        ...(pending?{replyToRequestId:pending.requestId,expectedRequestRevision:pending.revision}:{})})});
      if(alive.current)setTasks(previous=>previous.map(item=>item.id===task.id?updated:item));setError('');
    } catch(cause) {if(alive.current)setError(cause instanceof Error?cause.message:'Could not update this task.');await refresh();}
  };
  return {tasks,error,notice,replyTarget,replyTargets:browserReplyTargets(tasks).filter(target=>!dismissedRequestIds.includes(target.replyToRequestId)),setReplyTarget:(target:BrowserReplyTarget|null)=>setReplyTarget(target,target===null),tryStart,command,refresh};
}
