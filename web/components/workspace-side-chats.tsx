"use client";

import { useEffect, useRef, useState } from 'react';
import { Minus, MessageCircle, MoreHorizontal } from 'lucide-react';
import {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuItem} from './ui/dropdown-menu';
import { CompactTutorChat, type TutorChatContext } from './compact-tutor-chat';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { request } from '@/lib/api';
import styles from './workspace-side-chats.module.css';

import {SIDE_CHAT_OPEN} from '@/lib/workspace-side-chat-events';
export {openSideChat} from '@/lib/workspace-side-chat-events';
type WindowState = {context:TutorChatContext; x:number; y:number; minimized:boolean};

export function WorkspaceSideChats() {
  const [windows,setWindows] = useState<WindowState[]>([]);
  const [owner,setOwner] = useState<string|null>(null);
  const [active,setActive] = useState('');
  const ownerRef=useRef<string|null>(null);
  useEffect(()=>{ownerRef.current=owner;},[owner]);
  const drag = useRef<{id:string; x:number; y:number}|null>(null);
  useEffect(() => {
    let epoch=0;
    const load=()=>{const current=++epoch;ownerRef.current=null;setOwner(null);setWindows([]);setActive('');void request<{ownerId:string}>('/v1/account').then(account=>{if(current!==epoch)return;ownerRef.current=account.ownerId;setOwner(account.ownerId);try {const saved=JSON.parse(localStorage.getItem(`workspace-side-chats:${account.ownerId}`)||'[]');if(Array.isArray(saved)){const restored=saved.filter(item=>typeof item?.context?.id==='string'&&typeof item.context.title==='string'&&typeof item.context.excerpt==='string'&&item.context.excerpt.length<=6000&&Number.isFinite(item.x)&&Number.isFinite(item.y)).slice(0,100);setWindows(restored);setActive(restored.at(-1)?.context.id||'');}}catch{/* Optional local layout. */}}).catch(()=>{});};
    const timer=window.setTimeout(load,0);window.addEventListener(ACCOUNT_CHANGED,load);return()=>{epoch++;window.clearTimeout(timer);window.removeEventListener(ACCOUNT_CHANGED,load);};
  },[]);
  useEffect(()=>{if(owner)try{localStorage.setItem(`workspace-side-chats:${owner}`,JSON.stringify(windows));}catch{/* Server chats remain saved. */}},[windows,owner]);
  useEffect(()=>{
    const open=(event:Event)=>{const context=(event as CustomEvent<TutorChatContext>).detail;if(!ownerRef.current||!context?.id||!context.excerpt||context.excerpt.length>6000)return;setWindows(current=>[...current,{context,x:Math.max(8,window.innerWidth-400-(current.length%3)*36),y:Math.max(8,window.innerHeight-550-(current.length%3)*28),minimized:false}]);setActive(context.id);};
    const move=(event:PointerEvent)=>{const current=drag.current;if(!current)return;setWindows(items=>items.map(item=>item.context.id===current.id?{...item,x:Math.max(8,Math.min(window.innerWidth-360,event.clientX-current.x)),y:Math.max(8,Math.min(window.innerHeight-Math.min(510,window.innerHeight*.75)-44,event.clientY-current.y))}:item));};
    const stop=()=>{drag.current=null;};
    window.addEventListener(SIDE_CHAT_OPEN,open);window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop);return()=>{window.removeEventListener(SIDE_CHAT_OPEN,open);window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop);};
  },[]);
  return <><div className={styles.chips} aria-label="Side conversations">{windows.map(item=><button key={item.context.id} onClick={()=>{setActive(item.context.id);setWindows(items=>items.map(value=>value.context.id===item.context.id?{...value,minimized:false}:value));}}><MessageCircle size={13}/>{item.context.title}</button>)}</div>{windows.map(item=><section key={item.context.id} hidden={item.minimized} data-active={active===item.context.id} className={styles.window} style={{left:`min(${item.x}px, max(8px, calc(100vw - 370px)))`,top:`min(${item.y}px, max(8px, calc(100dvh - min(510px,75dvh) - 44px)))`,zIndex:active===item.context.id?61:60}} onPointerDown={()=>setActive(item.context.id)} onFocus={()=>setActive(item.context.id)} aria-label={`Side chat: ${item.context.title}`}>
    <div className={styles.handle} onPointerDown={event=>{if((event.target as HTMLElement).closest('button'))return;event.currentTarget.setPointerCapture(event.pointerId);drag.current={id:item.context.id,x:event.clientX-item.x,y:event.clientY-item.y};}}><span>{item.context.title}</span><DropdownMenu><DropdownMenuTrigger asChild><button aria-label={`Actions for ${item.context.title}`}><MoreHorizontal size={15}/></button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem onSelect={()=>setWindows(items=>items.filter(value=>value.context.id!==item.context.id))}>Close popup · saved chat stays in history</DropdownMenuItem></DropdownMenuContent></DropdownMenu><button aria-label={`Minimize ${item.context.title}`} onClick={()=>setWindows(items=>items.map(value=>value.context.id===item.context.id?{...value,minimized:true}:value))}><Minus size={16}/></button></div>
    <CompactTutorChat context={{...item.context,floating:true,storageOwner:owner||undefined}} onClose={()=>setWindows(items=>items.filter(value=>value.context.id!==item.context.id))}/>
  </section>)}</>;
}
