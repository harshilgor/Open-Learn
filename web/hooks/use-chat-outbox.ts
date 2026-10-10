"use client";
import { useEffect, useRef, useState } from 'react';
import { nextOutboxMessage, restoreOutbox, type OutboxMessage } from '@/lib/chat-outbox';

export function useChatOutbox({ storageKey, enabled, turnCount, send }: {
  storageKey: string; enabled: boolean; turnCount: number;
  send: (message: OutboxMessage, onAccepted: () => void) => Promise<'choice' | void>;
}) {
  const [messages, setMessages] = useState<OutboxMessage[]>(()=>{try{return restoreOutbox(sessionStorage.getItem(storageKey));}catch{return [];}});
  const active = useRef(new Set<string>());
  const sender = useRef(send);
  const alive = useRef(true);
  const previousKey = useRef(storageKey);
  useEffect(()=>{sender.current=send;});
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    try {
      if(previousKey.current!==storageKey&&!messages.length){
        const restored=restoreOutbox(sessionStorage.getItem(storageKey));
        previousKey.current=storageKey;
        if(restored.length){queueMicrotask(()=>{if(alive.current)setMessages(restored);});return;}
      }
      if (messages.length) sessionStorage.setItem(storageKey, JSON.stringify(messages));
      else sessionStorage.removeItem(storageKey);
      if(previousKey.current!==storageKey)sessionStorage.removeItem(previousKey.current);
      previousKey.current=storageKey;
    } catch { /* Sending still works when optional recovery storage is unavailable. */ }
  },[messages,storageKey]);
  useEffect(()=>{
    // Once the accepted server turn is in the hydrated conversation, its
    // durable copy is authoritative and the local receipt can be discarded.
    const reconciled = messages.filter(item => item.status === 'accepted' && turnCount > item.baseTurn);
    if (reconciled.length) queueMicrotask(() => setMessages(current => current.filter(item => !reconciled.some(done => done.id === item.id))));
  },[messages,turnCount]);
  useEffect(()=>{
    // Only one request may be awaiting durable acceptance at a time. As soon
    // as it is accepted, the next queued message can be delivered while the
    // previous generation continues streaming.
    if(!enabled || messages.some(item => item.status === 'sending' || item.status === 'choice')) return;
    const next=nextOutboxMessage(messages);
    if(!next || active.current.has(next.id))return;
    active.current.add(next.id);
    const sending={...next,status:'sending' as const,baseTurn:turnCount};
    setMessages(current=>current.map(item=>item.id===next.id?sending:item));
    const onAccepted = () => {
      if(!alive.current)return;
      setMessages(current=>current.map(item=>item.id===next.id?{...item,status:'accepted',error:undefined}:item));
    };
    void sender.current(sending,onAccepted).then(result=>{
      if(!alive.current)return;
      setMessages(current=>result==='choice'
        ?current.map(item=>item.id===next.id?{...item,status:'choice'}:item)
        :current.filter(item=>item.id!==next.id));
    }).catch(cause=>{
      if(alive.current)setMessages(current=>current.flatMap(item=>item.id!==next.id? [item] : item.status==='accepted' ? [] : [{...item,status:'failed',error:cause instanceof Error?cause.message:'Could not send. Your message is retained.'}]));
    }).finally(()=>{active.current.delete(next.id);});
  },[enabled,messages,turnCount]);
  return {
    messages,
    enqueue(text:string){if(messages.length>=30)return false;setMessages(current=>[...current,{id:crypto.randomUUID(),text,createdAt:Date.now(),status:'queued',baseTurn:turnCount}]);return true;},
    retry(id:string){setMessages(current=>current.map(item=>item.id===id?{...item,status:'queued',error:undefined}:item));},
    remove(id:string){setMessages(current=>current.filter(item=>item.id!==id||item.status==='sending'||item.status==='accepted'));},
    resolveChoice(){setMessages(current=>current.filter(item=>item.status!=='choice'));},
  };
}
