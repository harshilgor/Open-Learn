"use client";
import { Fragment, createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Plus, Settings, Home, RefreshCw } from 'lucide-react';
import { buddyApi, type Buddy, type BuddyInput, type BuddySnapshot } from '@/lib/buddies';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { clearChatDraftFiles } from '@/lib/chat-draft-files';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from './ui/dialog';
import { Button } from './ui/button';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from './ui/sheet';
import './buddies.css';

const icons = { spark:'✦', owl:'🦉', cat:'🐱', leaf:'🌿', planet:'🪐' };
type BuddyContext = { snapshot:BuddySnapshot|null; active:Buddy|undefined; select:(id:string)=>void; refresh:()=>Promise<void>; edit:(buddy?:Buddy)=>void; error:string };
const Context=createContext<BuddyContext>({snapshot:null,active:undefined,select:()=>{},refresh:async()=>{},edit:()=>{},error:''});
export const useBuddies=()=>useContext(Context);
export function BuddyAvatar({buddy}:{buddy:Buddy}) { return <span className={`buddy-avatar buddy-${buddy.color}`} aria-hidden="true">{icons[buddy.avatar]}</span>; }

export function BuddyProvider({children}:{children:ReactNode}) {
  const [snapshot,setSnapshot]=useState<BuddySnapshot|null>(null),[activeId,setActiveId]=useState(''),[error,setError]=useState('');
  const [editor,setEditor]=useState<{buddy?:Buddy}|null>(null);
  const generation=useRef(0);
  const invalidate=useCallback(()=>{generation.current++;},[]);
  const [accountEpoch,setAccountEpoch]=useState(0);
  const refresh=useCallback(async()=>{const request=++generation.current;try{const next=await buddyApi.snapshot();if(request!==generation.current)return;setSnapshot(next);setActiveId(current=>next.profiles.some(p=>p.id===current)?current:next.defaultBuddyId);setError('');}catch(e){if(request===generation.current)setError(e instanceof Error?e.message:'Could not load Buddies.');}},[]);
  useEffect(()=>{const reset=()=>{clearChatDraftFiles();generation.current++;setSnapshot(null);setActiveId('');setEditor(null);setError('');setAccountEpoch(value=>value+1);void refresh();};const timer=setTimeout(()=>void refresh(),0);window.addEventListener(ACCOUNT_CHANGED,reset);return()=>{invalidate();clearTimeout(timer);window.removeEventListener(ACCOUNT_CHANGED,reset);};},[refresh,invalidate]);
  const active=snapshot?.profiles.find(p=>p.id===activeId);
  return <Context.Provider value={{snapshot,active,select:setActiveId,refresh,edit:buddy=>setEditor({buddy}),error}}><Fragment key={accountEpoch}>{children}</Fragment>{editor?<BuddyEditor existing={editor.buddy} onClose={()=>setEditor(null)} onSaved={async()=>{await refresh();setEditor(null);}}/>:null}</Context.Provider>;
}

function BuddyEditor({existing,onClose,onSaved}:{existing?:Buddy;onClose:()=>void;onSaved:(buddy:Buddy)=>Promise<void>}) {
  const {snapshot,refresh}=useBuddies();
  const [input,setInput]=useState<BuddyInput>(existing||{name:'',avatar:'spark',color:'sage',style:'encouraging',concise:true,examples:true,proactive:false});
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[replacement,setReplacement]=useState('');
  const preview={...input,id:'preview',revision:1,archived:false};
  async function save(){setBusy(true);setError('');try{await onSaved(await buddyApi.save(input,existing));}catch(e){setError(e instanceof Error?e.message:'Could not save.');}finally{setBusy(false);}}
  async function archive(){if(!existing||!replacement)return;setBusy(true);try{await buddyApi.archive(existing,replacement);await refresh();onClose();}catch(e){setError(e instanceof Error?e.message:'Could not archive.');}finally{setBusy(false);}}
  return <Dialog open onOpenChange={value=>{if(!value&&!busy)onClose();}}><DialogContent><DialogTitle>{existing?'Customize':'Create'} Buddy</DialogTitle><DialogDescription>Give your study partner a look and communication style.</DialogDescription>
    <div className="buddy-preview"><BuddyAvatar buddy={preview}/><strong>{input.name||'Your Buddy'}</strong><p>{input.style==='direct'?"Let's get started. What are we working on?":input.style==='playful'?"Ready to untangle something together?":input.style==='calm'?"One step at a time. What would you like to explore?":"You've got this. What are we figuring out today?"}</p></div>
    <label>Name<input maxLength={60} value={input.name} onChange={e=>setInput({...input,name:e.target.value})}/></label>
    <div className="buddy-fields">{(['avatar','color','style'] as const).map(field=><label key={field}>{field}<select value={input[field]} onChange={e=>setInput({...input,[field]:e.target.value})}>{(field==='avatar'?Object.keys(icons):field==='color'?['sage','blue','violet','rose','amber']:['calm','encouraging','playful','direct']).map(value=><option key={value}>{value}</option>)}</select></label>)}</div>
    <label><input type="checkbox" checked={input.concise} onChange={e=>setInput({...input,concise:e.target.checked})}/>Prefer concise explanations</label><label><input type="checkbox" checked={input.examples} onChange={e=>setInput({...input,examples:e.target.checked})}/>Use examples</label>
    <p className="text-xs text-muted-foreground">Automatic preparation will be available when course scheduling is connected.</p>
    {error?<p role="alert">{error}</p>:null}<Button disabled={busy||!input.name.trim()} onClick={()=>void save()}>{busy?'Saving…':'Save Buddy'}</Button>
    {existing?<><Button variant="outline" disabled={busy} onClick={async()=>{setBusy(true);try{await buddyApi.makeDefault(existing.id);await refresh();}catch(e){setError(String(e));}finally{setBusy(false);}}}>Use as my default</Button><details><summary>Archive Buddy</summary><p>{Object.values(snapshot?.courses||{}).filter(id=>id===existing.id).length} assigned courses and {snapshot?.responsibilities?.[existing.id]||0} responsibility records will transfer to the replacement. Chats stay attributed to this Buddy in All chats. Existing reminder and task IDs remain unchanged.</p><select aria-label="Replacement Buddy" value={replacement} onChange={e=>setReplacement(e.target.value)}><option value="">Choose replacement</option>{snapshot?.profiles.filter(p=>!p.archived&&p.id!==existing.id).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><Button variant="outline" disabled={busy||!replacement} onClick={()=>void archive()}>Archive and reassign</Button></details></>:null}
  </DialogContent></Dialog>;
}

export function BuddyRail({onSwitch,onHome,onSettings}:{onSwitch:(id:string)=>void;onHome:()=>void;onSettings:()=>void}) {
  const {snapshot,active,edit,error,refresh}=useBuddies();
  return <nav className="buddy-rail" aria-label="Study companions"><button aria-label="Home and Today" onClick={onHome}><Home size={20}/></button>{snapshot?.profiles.filter(p=>!p.archived).map(p=><button key={p.id} aria-label={`Open ${p.name}`} aria-pressed={active?.id===p.id} title={p.name} onClick={()=>onSwitch(p.id)}><BuddyAvatar buddy={p}/>{(snapshot.unread?.[p.id]||0)>0?<small aria-label={`${snapshot.unread?.[p.id]} unread reminders`}>{snapshot.unread?.[p.id]}</small>:null}</button>)}<button aria-label="Create Buddy" disabled={!snapshot} onClick={()=>edit()}><Plus size={20}/></button><button aria-label="Settings" onClick={onSettings}><Settings size={20}/></button>{error?<button aria-label="Retry loading Buddies" title={error} onClick={()=>void refresh()}><RefreshCw size={20}/></button>:null}</nav>;
}

export function BuddyHeader({onSwitch}:{onSwitch:(id:string)=>void}) {
  const {snapshot,active,edit,error}=useBuddies();
  const [open,setOpen]=useState(false);
  return <div className="buddy-header">{active?<><div className="buddy-desktop-switch"><BuddyAvatar buddy={active}/><select aria-label="Select Buddy" value={active.id} onChange={e=>onSwitch(e.target.value)}>{snapshot?.profiles.filter(p=>!p.archived||p.id===active.id).map(p=><option key={p.id} value={p.id}>{p.name}{p.archived?' (archived history)':''}</option>)}</select></div><button className="buddy-mobile-switch" aria-label="Switch Buddy" onClick={()=>setOpen(true)}><BuddyAvatar buddy={active}/><strong>{active.name}</strong></button><button disabled={active.archived} aria-label={`Customize ${active.name}`} onClick={()=>edit(active)}><Settings size={16}/></button><button aria-label="Create Buddy" onClick={()=>edit()}><Plus size={16}/></button><Sheet open={open} onOpenChange={setOpen}><SheetContent side="bottom"><SheetHeader><SheetTitle>Your Buddies</SheetTitle><SheetDescription>Each study partner has its own conversations.</SheetDescription></SheetHeader><div className="p-4 space-y-3">{snapshot?.profiles.filter(p=>!p.archived||p.id===active.id).map(buddy=><button className="course-buddy w-full" key={buddy.id} aria-pressed={buddy.id===active.id} onClick={()=>{onSwitch(buddy.id);setOpen(false);}}><BuddyAvatar buddy={buddy}/>{buddy.name}{buddy.archived?' (archived history)':''}</button>)}<Button onClick={()=>{setOpen(false);edit();}}>Create Buddy</Button><Button disabled={active.archived} variant="outline" onClick={()=>{setOpen(false);edit(active);}}>Customize {active.name}</Button></div></SheetContent></Sheet></>:<span role="status">{error||'Loading your Buddies…'}</span>}</div>;
}

export function CourseBuddy({courseId,onChat}:{courseId:string;onChat:()=>void}) {
  const {snapshot,refresh}=useBuddies();const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const id=snapshot?.courses[courseId]||snapshot?.defaultBuddyId;const buddy=snapshot?.profiles.find(p=>p.id===id);
  return <section className="course-buddy" aria-label="Course companion">{buddy?<BuddyAvatar buddy={buddy}/>:null}<label>Study partner<select disabled={busy||!snapshot} value={snapshot?.courses[courseId]||''} onChange={async e=>{setBusy(true);setError('');try{await buddyApi.assign(courseId,e.target.value||null);await refresh();}catch(cause){setError(String(cause));}finally{setBusy(false);}}}><option value="">My default Buddy{snapshot?.profiles.find(p=>p.id===snapshot.defaultBuddyId)?` (${snapshot.profiles.find(p=>p.id===snapshot.defaultBuddyId)?.name})`:''}</option>{snapshot?.profiles.filter(p=>!p.archived).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><Button disabled={!buddy||busy} onClick={onChat}>Ask {buddy?.name||'Buddy'} about this course</Button>{error?<p role="alert">{error}</p>:null}</section>;
}
