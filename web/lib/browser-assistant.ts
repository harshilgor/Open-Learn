'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {request} from './api';
import {ACCOUNT_CHANGED} from './account-session';
import {admitConversation} from './conversation-admission';

export type SiteConnection = {id:string;revision:number;label:string;origin:string;status:string;platform:'canvas'|'generic';executor:'local'|'cloud'|'public_fetch';preferred:boolean;cloudLogin?:boolean;timezone:string;aliases:string[];approvedOrigins?:string[];lastSuccessfulSync?:number|null};
export type AcademicFact = {entityId?:string;courseId?:string;title:string;kind:string;date?:{kind:string;value?:string|null}|null;conflict?:boolean;saved?:boolean;source?:{locator:string;quote?:string;revision?:string;extractionMethod?:string;confirmation?:string}};
export type BrowserTask = {id:string;revision:number;sessionId?:string|null;message:string;status:string;connectionId?:string|null;summary?:string|null;question?:string|null;error?:string|null;facts:AcademicFact[];studyTasks?:{id:string;courseId:string;reason:string}[];coverage:{key:string;complete:boolean;status:string;url:string}[];actionsUsed:number;createdAt:number;browserControl?:{owner:'agent'|'requesting'|'human'|'returning';generation:string;executor:'local'|'cloud'}|null};
export const finishedTask = (status:string) => ['completed','completed_partial','cancelled','failed'].includes(status);
export const SITE_CHANGED = 'openlearn-sites-changed';

export function useBrowserAssistant(sessionId:string|null, courseId?:string|null) {
  const [tasks,setTasks] = useState<BrowserTask[]>([]);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const alive = useRef(true);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    if(!sessionId) return;
    const current=generation.current;
    const result = await request<{tasks:BrowserTask[]}>(`/v1/assistant/tasks?sessionId=${encodeURIComponent(sessionId)}`);
    if(alive.current && current===generation.current) setTasks(result.tasks.slice().reverse());
  },[sessionId]);
  useEffect(()=>{
    alive.current=true;
    generation.current++;
    let loading=false;
    const update=()=>{if(loading)return;loading=true;void refresh().catch(e=>{if(alive.current)setError(e.message);}).finally(()=>{loading=false;});};
    const timer=window.setTimeout(()=>{setTasks([]);setError('');setNotice('');update();},0);
    const interval=window.setInterval(update,2500);
    const clear=()=>{generation.current++;setTasks([]);setError('');setNotice('');update();};
    window.addEventListener(ACCOUNT_CHANGED,clear);
    window.addEventListener('openlearn-browser-task-changed',update);
    return()=>{alive.current=false;window.clearTimeout(timer);window.clearInterval(interval);window.removeEventListener(ACCOUNT_CHANGED,clear);window.removeEventListener('openlearn-browser-task-changed',update);};
  },[refresh]);
  const tryStart = async(message:string,sid:string,attachments:{versionId:string;name:string}[] = [],presentation:'conversation'|'ask'|'learn'|'quiz'='conversation') => {
    const previousTaskId = /\b(those|them|these|same website|same portal|open it|do that)\b|^(also |and |now )?remind me\b/i.test(message) && !/https:\/\//i.test(message) ? tasks.filter(task=>task.sessionId===sid).at(-1)?.id : undefined;
    const admission = await admitConversation(message, sid, courseId, previousTaskId, attachments, presentation);
    if (!admission.handled) return false;
    if (admission.question || admission.message) {
      if (alive.current) setNotice(admission.question || admission.message || '');
    }
    if (admission.runtimeOwner === 'browser_legacy' && admission.references[0]?.id) {
      const task = await request<BrowserTask>(`/v1/assistant/tasks/${admission.references[0].id}`);
      if (alive.current) setTasks(previous=>[...previous.filter(t=>t.id!==task.id),task]);
    }
    return true;
  };
  const command=async(task:BrowserTask,action:'pause'|'cancel'|'resume'|'resolve',connectionId?:string,answer?:string,courseId?:string)=>{
    try {
      const updated=await request<BrowserTask>(`/v1/assistant/tasks/${task.id}/commands`,{method:'POST',body:JSON.stringify({action,expectedRevision:task.revision,connectionId,answer,courseId})});
      if(alive.current)setTasks(previous=>previous.map(item=>item.id===task.id?updated:item));setError('');
    } catch(cause) {if(alive.current)setError(cause instanceof Error?cause.message:'Could not update this task.');await refresh();}
  };
  return {tasks,error,notice,tryStart,command,refresh};
}
