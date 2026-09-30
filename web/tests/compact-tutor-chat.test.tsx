import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CompactTutorChat } from '@/components/compact-tutor-chat';
const mocks=vi.hoisted(()=>({create:vi.fn(),start:vi.fn(),journey:vi.fn()}));
vi.mock('@/lib/api',async original=>({...await original<object>(),learningApi:{createSession:mocks.create}}));
vi.mock('@/lib/generation-stream',()=>({GenerationStream:class{wasCancelled=false;start=mocks.start;stop=async()=>{};}}));
vi.mock('@/lib/learning-workflows',()=>({getJourney:mocks.journey}));
vi.mock('@/components/rich-content',()=>({RichContent:({body}:{body:string})=><p>{body}</p>}));
vi.mock('@/components/chat-composer',()=>({ChatComposer:({value,onChange,onSubmit,busy}:{value:string;onChange:(s:string)=>void;onSubmit:()=>void;busy:boolean})=><><textarea aria-label="Question" value={value} onChange={e=>onChange(e.target.value)}/><button disabled={busy} onClick={onSubmit}>Send</button></>}));
let root:Root, container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;localStorage.clear();vi.clearAllMocks();HTMLElement.prototype.scrollTo=vi.fn();container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);mocks.create.mockResolvedValue({id:'discussion-1'});mocks.start.mockResolvedValue(undefined);mocks.journey.mockResolvedValue({revision:2,turns:[{question:'Explain weights',sessionId:'discussion-1',lesson:{blocks:[{id:'b1',body:'Weights combine inputs.'}]}}]});});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function ask(){const area=container.querySelector('textarea')!;act(()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(area,'Explain weights');area.dispatchEvent(new Event('input',{bubbles:true}));});await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Send')!.click());}
it('creates a separate course-linked discussion, sends revision-safe note context and preserves the main URL',async()=>{
  const url=window.location.href;act(()=>root.render(<CompactTutorChat context={{id:'n1',title:'Weights',courseId:'physics',excerpt:'Weights combine inputs.',note:{noteId:'n1',expectedRevision:3,startOffset:0,endOffset:23}}} onClose={()=>{}}/>));
  expect(document.activeElement).toBe(container.querySelector('textarea'));await ask();
  expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({courseId:'physics',gear:'Quick'}));
  expect(mocks.start).toHaveBeenCalledWith('discussion-1',expect.objectContaining({mode:'ask',expectedRevision:1,noteContext:{notes:[{noteId:'n1',expectedRevision:3,startOffset:0,endOffset:23}]}}),expect.anything());
  expect(container.textContent).toContain('Weights combine inputs.');expect(window.location.href).toBe(url);expect(localStorage.getItem('forma:context-chat:n1')).toBe('discussion-1');
});
it('recovers the conversation revision after a failed request and keeps the user question for retry',async()=>{
  mocks.start.mockRejectedValueOnce(new Error('Connection interrupted'));
  act(()=>root.render(<CompactTutorChat context={{id:'n2',title:'Weights',excerpt:'Weights'}} onClose={()=>{}}/>));await ask();
  expect(container.textContent).toContain('Connection interrupted');expect(container.querySelector('textarea')?.value).toBe('Explain weights');
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Send')!.click());
  expect(mocks.start.mock.calls[1][1].expectedRevision).toBe(2);
});
