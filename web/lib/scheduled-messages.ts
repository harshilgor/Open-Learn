'use client';
import { useEffect, useState } from 'react';
import { request } from './api';
import { ACCOUNT_CHANGED } from './account-session';

export type ScheduledMessage = {id:string;title:string;body:string;url:string;taskId?:string};

export function useScheduledMessages(sessionId:string|null) {
  const [messages,setMessages]=useState<ScheduledMessage[]>([]);
  useEffect(()=>{
    setMessages([]);
    if(!sessionId)return;
    let live=true;
    let pending=false;
    const controller=new AbortController();
    const load=async()=>{
      if(!live||pending||document.visibilityState==='hidden')return;
      pending=true;
      try {
        const result=await request<{messages:ScheduledMessage[]}>('/v1/reminder-messages?sessionId='+encodeURIComponent(sessionId),{signal:controller.signal});
        if(live&&Array.isArray(result.messages))setMessages(result.messages);
      } catch {/* Persisted results recover on the next visible refresh. */}
      finally {pending=false;}
    };
    void load();
    const timer=window.setInterval(()=>void load(),5000);
    const refresh=()=>void load();
    const accountChanged=()=>{live=false;controller.abort();setMessages([]);};
    document.addEventListener('visibilitychange',refresh);
    window.addEventListener('focus',refresh);
    window.addEventListener(ACCOUNT_CHANGED,accountChanged);
    return()=>{live=false;controller.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);window.removeEventListener('focus',refresh);window.removeEventListener(ACCOUNT_CHANGED,accountChanged);};
  },[sessionId]);
  return messages;
}
