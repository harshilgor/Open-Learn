"use client";
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {WORKSPACE_PASSAGE_MENTION_EVENT} from '@/lib/workspace-events';
import {openSideChat} from '@/lib/workspace-side-chat-events';

/** Source content is attached as bounded evidence, never as system instructions. */
export function PassageSelection({children,title,itemContext}:{children:ReactNode;title:string;itemContext?:string}) {
  const root=useRef<HTMLDivElement>(null);
  const [selection,setSelection]=useState<{excerpt:string;x:number;y:number}|null>(null);
  function inspect(){const value=window.getSelection();if(!value?.rangeCount||!root.current?.contains(value.anchorNode)||!root.current.contains(value.focusNode))return;const excerpt=value.toString().trim();if(!excerpt||excerpt.length>6000){setSelection(null);return;}const bounds=value.getRangeAt(0).getBoundingClientRect();setSelection({excerpt,x:Math.max(8,Math.min(bounds.left,window.innerWidth-310)),y:Math.max(8,bounds.top-42)});}
  useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setSelection(null);};const dismiss=()=>setSelection(null);window.addEventListener('keydown',escape);window.addEventListener('resize',dismiss);return()=>{window.removeEventListener('keydown',escape);window.removeEventListener('resize',dismiss);};},[]);
  return <div ref={root} onMouseUp={inspect} onKeyUp={inspect} onTouchEnd={inspect} onContextMenu={event=>{if(!itemContext)return;event.preventDefault();setSelection({excerpt:itemContext.slice(0,6000),x:Math.max(8,Math.min(event.clientX,window.innerWidth-310)),y:Math.max(8,Math.min(event.clientY,window.innerHeight-48))});}} style={{display:'contents'}}>{children}{selection?createPortal(<div role="toolbar" aria-label="Selected source passage" className="fixed z-[70] flex rounded-lg border bg-popover p-1 text-popover-foreground shadow-md" style={{left:selection.x,top:selection.y}} onMouseDown={event=>event.preventDefault()}>{['Add to chat','Explain','Ask in side chat'].map(action=><button className="rounded px-2 py-2 text-xs hover:bg-accent focus-visible:outline-2" key={action} onClick={()=>{if(action==='Ask in side chat')openSideChat({id:crypto.randomUUID(),title,excerpt:selection.excerpt});else window.dispatchEvent(new CustomEvent(WORKSPACE_PASSAGE_MENTION_EVENT,{detail:{title,excerpt:selection.excerpt,submit:action==='Explain'}}));setSelection(null);}}>{action}</button>)}</div>,document.body):null}</div>;
}
