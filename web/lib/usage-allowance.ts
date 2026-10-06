"use client";
import { useEffect, useSyncExternalStore } from 'react';
import { request } from './api';
import { ACCOUNT_CHANGED, sessionToken } from './account-session';
export type Allowance = {windowId:string|null;windowState:'ready'|'active';serverTime:number;resetsAt:number|null;grantedMicrocredits:number;usedMicrocredits:number;heldMicrocredits:number;availableMicrocredits:number;revision:number;availability:string;reasonCode:string|null};
type UsageEventPage={events:Array<{id:string;revision:number;kind:string;createdAt:number}>;nextRevision:number;latestRevision:number;hasMore:boolean;resnapshotRequired:boolean};
type State={snapshot:Allowance|null;error:string;fetchedAt:number};
const empty:State={snapshot:null,error:'',fetchedAt:0};
const usageCursorKey='openlearn.usage-events.cursor.v1';
let state=empty,generation=0,pending:Promise<Allowance|null>|null=null;
let eventPending:Promise<boolean>|null=null,eventCursor:{scope:string;revision:number}|null=null;
const listeners=new Set<()=>void>();
function emit(next:State){state=next;listeners.forEach(fn=>fn());}
async function boundedUsageRequest<T>(path:string):Promise<T>{
 const controller=new AbortController();const timer=window.setTimeout(()=>controller.abort(),10000);
 try{return await request<T>(path,{signal:controller.signal});}
 finally{clearTimeout(timer);}
}
export function usagePercent(s:Allowance){
 const amounts=[s.grantedMicrocredits,s.usedMicrocredits,s.heldMicrocredits,s.availableMicrocredits];
 if(!amounts.every(Number.isSafeInteger)||s.grantedMicrocredits<=0||s.usedMicrocredits<0||s.heldMicrocredits<0||s.availableMicrocredits<0||s.usedMicrocredits+s.heldMicrocredits>s.grantedMicrocredits||s.availableMicrocredits!==Math.max(0,s.grantedMicrocredits-s.usedMicrocredits-s.heldMicrocredits))return null;
 const used=Math.max(0,Math.min(100,s.usedMicrocredits*100/s.grantedMicrocredits));
 const held=Math.max(0,Math.min(100-used,s.heldMicrocredits*100/s.grantedMicrocredits));
 return{used,held,available:Math.max(0,100-used-held),label:used===100?'100%':used>0&&Math.round(used)===0?'<1%':`${Math.min(99,Math.round(used))}%`};
}
export function usageActivityLabel(input:{used:number;held:number;grant:number;status?:'pending'|'in_progress'|'settled'}){
 const percentage=(amount:number)=>`${Math.min(100,Math.max(0,amount/input.grant*100)).toFixed(1).replace(/\.0$/,'')}%`;
 const used=Math.max(0,input.used),held=Math.max(0,input.held);
 const status=input.status==='pending'?'Pending':input.status==='in_progress'?'In progress':input.status==='settled'?'Settled':used===0&&held>0?'In progress':'Settled';
 if(used===0&&held>0)return`${percentage(held)} reserved · ${status}`;
 if(used===0&&status!=='Settled')return`${status} · awaiting usage`;
 return`${percentage(used)} used${held>0?` · ${percentage(held)} reserved`:''} · ${status}`;
}
export function parseUsageEventPage(value:unknown,afterRevision:number):UsageEventPage|null{
 if(!value||typeof value!=='object')return null;
 const page=value as Partial<UsageEventPage>;
 if(!Number.isSafeInteger(page.nextRevision)||!Number.isSafeInteger(page.latestRevision)||typeof page.hasMore!=='boolean'||typeof page.resnapshotRequired!=='boolean'||!Array.isArray(page.events))return null;
 const next=page.nextRevision as number,latest=page.latestRevision as number;
 if(next<afterRevision||latest<next)return null;
 if(page.resnapshotRequired)return page.events.length===0?{events:[],nextRevision:next,latestRevision:latest,hasMore:false,resnapshotRequired:true}:null;
 let expected=afterRevision;
 const events=[];
 for(const item of page.events){
  if(!item||typeof item!=='object')return null;
  const event=item as UsageEventPage['events'][number];
  if(typeof event.id!=='string'||!event.id||!Number.isSafeInteger(event.revision)||event.revision!==expected+1||typeof event.kind!=='string'||!Number.isFinite(event.createdAt))return null;
  expected=event.revision;events.push(event);
 }
 if(expected!==next||(events.length===0&&(next!==afterRevision||latest!==afterRevision)))return null;
 return{events,nextRevision:next,latestRevision:latest,hasMore:page.hasMore,resnapshotRequired:false};
}
async function allowanceAccountScope(){
 const token=await sessionToken();
 if(!token)return'local';
 try{
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token));
  return`session:${Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('')}`;
 }catch{return`session:${generation}`;}
}
function readUsageCursor(scope:string,initialRevision:number){
 if(eventCursor?.scope===scope)return eventCursor.revision;
 let revision=initialRevision;
 try{
  const saved=JSON.parse(sessionStorage.getItem(usageCursorKey)||'null') as {scope?:unknown;revision?:unknown}|null;
  if(saved?.scope===scope&&Number.isSafeInteger(saved.revision)&&(saved.revision as number)>=0)revision=Math.max(revision,saved.revision as number);
 }catch{/* Session storage is an optional replay optimization. */}
 eventCursor={scope,revision};return revision;
}
function saveUsageCursor(scope:string,revision:number){
 eventCursor={scope,revision};
 try{sessionStorage.setItem(usageCursorKey,JSON.stringify({scope,revision}));}catch{/* Replay starts from the current snapshot if storage is unavailable. */}
}
export async function refreshAllowance():Promise<Allowance|null>{
 if(pending)return pending;const fence=generation;
 const work=(async()=>{
  try{
   const snapshot=await boundedUsageRequest<Allowance>('/v1/usage/allowance');
   if(fence!==generation)return null;
   if(!usagePercent(snapshot)||!Number.isSafeInteger(snapshot.revision)||snapshot.revision<0)throw new Error('Invalid allowance');
   if(!state.snapshot||snapshot.revision>state.snapshot.revision)emit({snapshot,error:'',fetchedAt:Date.now()});
   else if(snapshot.revision===state.snapshot.revision){
    const old=state.snapshot;
    if(snapshot.usedMicrocredits!==old.usedMicrocredits||snapshot.heldMicrocredits!==old.heldMicrocredits||snapshot.availableMicrocredits!==old.availableMicrocredits||snapshot.availability!==old.availability||snapshot.reasonCode!==old.reasonCode)emit({snapshot,error:'',fetchedAt:Date.now()});
   }
   return snapshot;
  }catch{if(fence===generation)emit({...state,error:'Usage is temporarily unavailable.'});return null;}
  finally{if(fence===generation)pending=null;}
 })();pending=work;return work;
}
async function pollUsageEvents():Promise<boolean>{
 if(eventPending)return eventPending;
 const fence=generation;
 const work=(async()=>{
  try{
   const scope=await allowanceAccountScope();if(fence!==generation)return false;
   const afterRevision=readUsageCursor(scope,state.snapshot?.revision??0);
   const page=parseUsageEventPage(await boundedUsageRequest<unknown>(`/v1/usage/events?afterRevision=${afterRevision}&limit=50`),afterRevision);
   if(!page||fence!==generation)return false;
   if(page.resnapshotRequired){
    const snapshot=await refreshAllowance();
    if(!snapshot||fence!==generation||snapshot.revision<page.latestRevision)return false;
    saveUsageCursor(scope,Math.max(page.latestRevision,snapshot.revision));return true;
   }
   if(page.events.length){
    const snapshot=await refreshAllowance();
    if(!snapshot||fence!==generation||snapshot.revision<page.nextRevision)return false;
    saveUsageCursor(scope,Math.max(page.nextRevision,snapshot.revision));
   }
   return true;
  }catch{return false;}
  finally{if(fence===generation)eventPending=null;}
 })();eventPending=work;return work;
}
function subscribe(fn:()=>void){listeners.add(fn);return()=>{listeners.delete(fn);};}
export function useAllowance(active=false){
 const value=useSyncExternalStore(subscribe,()=>state,()=>empty);
 const hasSnapshot=Boolean(value.snapshot);
 useEffect(()=>{void refreshAllowance();const refresh=()=>{if(document.visibilityState==='visible')void refreshAllowance();};const reset=()=>{generation++;pending=null;eventPending=null;eventCursor=null;try{sessionStorage.removeItem(usageCursorKey);}catch{/* Session storage is optional. */}emit(empty);void refreshAllowance();};window.addEventListener(ACCOUNT_CHANGED,reset);window.addEventListener('focus',refresh);window.addEventListener('openlearn-usage-updated',refresh);document.addEventListener('visibilitychange',refresh);const timer=active?window.setInterval(refresh,15000):undefined;return()=>{window.removeEventListener(ACCOUNT_CHANGED,reset);window.removeEventListener('focus',refresh);window.removeEventListener('openlearn-usage-updated',refresh);document.removeEventListener('visibilitychange',refresh);if(timer)clearInterval(timer);};},[active]);
 useEffect(()=>{
  if(!hasSnapshot)return;
  let live=true,timer:number|undefined,failures=0;
  let inFlight=false;
  const cadence=active?15000:60000;
  const schedule=(delay:number)=>{if(live)timer=window.setTimeout(()=>void poll(),delay);};
  const poll=async()=>{
   if(!live||inFlight)return;
   inFlight=true;
   try{
    if(document.visibilityState!=='visible'){schedule(cadence);return;}
    const succeeded=await pollUsageEvents();if(!live)return;
    failures=succeeded?0:Math.min(5,failures+1);
    schedule(Math.min(300000,cadence*2**failures));
   }finally{inFlight=false;}
  };
  const visible=()=>{if(document.visibilityState==='visible'){if(timer)clearTimeout(timer);void poll();}};
  void poll();document.addEventListener('visibilitychange',visible);window.addEventListener('focus',visible);
  return()=>{live=false;if(timer)clearTimeout(timer);document.removeEventListener('visibilitychange',visible);window.removeEventListener('focus',visible);};
 },[active,hasSnapshot]);
 useEffect(()=>{if(!value.snapshot?.resetsAt)return;const delay=Math.max(1000,(value.snapshot.resetsAt-value.snapshot.serverTime)*1000-(Date.now()-value.fetchedAt));const timer=setTimeout(()=>void refreshAllowance(),Math.min(delay,2147483647));return()=>clearTimeout(timer);},[value]);return value;
}
