import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkspaceSplit } from '@/components/workspace-split';
import { setWorkspacePanelCollapsed } from '@/lib/workspace-events';

const state = vi.hoisted(()=>({mounts:0}));
vi.mock('@/lib/use-app-reduced-motion',()=>({useAppReducedMotion:()=>true}));
vi.mock('@/components/workspace-panel',()=>({WorkspacePanel:()=>{
  const [value,setValue]=useState(()=>{state.mounts++;return '';});
  return <div><button type="button">Study control</button><textarea aria-label="Unsaved note" value={value} onChange={event=>setValue(event.target.value)}/></div>;
}}));
let root:Root,container:HTMLDivElement;
let change: (()=>void)|undefined;
let compact=true;
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  state.mounts=0;compact=true;localStorage.clear();
  vi.stubGlobal('matchMedia',()=>({matches:compact,addEventListener:(_name:string,callback:()=>void)=>{change=callback;},removeEventListener:()=>{}}));
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.unstubAllGlobals();});
it('preserves unsaved study content through close, navigation and breakpoint changes',async()=>{
  await act(async()=>root.render(<WorkspaceSplit><button>Chat</button></WorkspaceSplit>));
  act(()=>setWorkspacePanelCollapsed(false));
  const note=container.querySelector('textarea')!;
  act(()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(note,'My unsaved lecture correction');note.dispatchEvent(new Event('input',{bubbles:true}));});
  act(()=>setWorkspacePanelCollapsed(true));
  act(()=>setWorkspacePanelCollapsed(false));
  act(()=>root.render(<WorkspaceSplit hidePanel><button>Courses</button></WorkspaceSplit>));
  act(()=>root.render(<WorkspaceSplit><button>Chat</button></WorkspaceSplit>));
  act(()=>{compact=false;change?.();});
  expect(container.querySelector('textarea')).toBe(note);
  expect(note.value).toBe('My unsaved lecture correction');
  expect(state.mounts).toBe(1);
});
it('returns focus to chat after Escape closes the expanded study view',async()=>{
  await act(async()=>root.render(<WorkspaceSplit><button>Chat</button></WorkspaceSplit>));
  const chat=container.querySelector('button')!;chat.focus();
  act(()=>setWorkspacePanelCollapsed(false));
  const dialog=container.querySelector('[role="dialog"]')!;
  expect(document.activeElement?.textContent).toBe('Study control');
  act(()=>dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(dialog.hasAttribute('hidden')).toBe(true);
  expect(document.activeElement).toBe(chat);
});

it('keeps a class opened during initial layout restoration visible',async()=>{
 await act(async()=>root.render(<WorkspaceSplit><button>Chat</button></WorkspaceSplit>));
 act(()=>window.dispatchEvent(new CustomEvent('openlearn-class-open',{detail:{classId:'class-one'}})));
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
 expect(container.querySelector('[role="dialog"]')?.hasAttribute('hidden')).toBe(false);
});
