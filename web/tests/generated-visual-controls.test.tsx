import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {it,expect,vi} from 'vitest';
import {GeneratedVisualCard} from '@/components/generated-visual/generated-visual';
import {parseGeneratedVisual} from '@/lib/generated-visual';
const mocks=vi.hoisted(()=>({request:vi.fn(),focus:vi.fn()}));
vi.mock('@/lib/api',()=>({request:mocks.request}));
vi.mock('@/lib/voice/client',()=>({reportVoiceFocus:mocks.focus}));
vi.mock('@/components/generated-visual/upstream/renderer',async()=>{
  const {useSandboxFunctions}=await import('@/components/generated-visual/sandbox-context');
  return {OpenGenUIActivityRenderer:()=>{
    const functions=useSandboxFunctions();
    return <button onClick={()=>{void functions.find(value=>value.name==='saveControl')!.handler({id:'mass',value:5});}}>Change mass</button>;
  }};
});
it('serializes numeric saves and updates voice focus to the saved revision',async()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  const visual=parseGeneratedVisual({version:2,type:'generated_ui',id:'v',revision:1,title:'Force',renderer:'open_generative_ui',content:{html:['<p>Force</p>']},controls:[{id:'mass',label:'Mass',minimum:1,maximum:10,initial:2}],controlValues:{}})!;
  mocks.request.mockImplementation(async(_path:string,init:RequestInit)=>{const input=JSON.parse(init.body as string);return {...visual,revision:input.expectedRevision+1,controlValues:{mass:5}};});
  const container=document.createElement('div');document.body.appendChild(container);const root=createRoot(container);
  await act(async()=>root.render(<GeneratedVisualCard visual={visual} lessonId="lesson-owned"/>));
  await act(async()=>{const button=Array.from(container.querySelectorAll('button')).find(value=>value.textContent==='Change mass')!;button.click();button.click();await new Promise(resolve=>setTimeout(resolve,10));});
  expect(mocks.request).toHaveBeenCalledTimes(2);
  expect(JSON.parse(mocks.request.mock.calls[0][1].body).expectedRevision).toBe(1);
  expect(JSON.parse(mocks.request.mock.calls[1][1].body).expectedRevision).toBe(2);
  expect(mocks.focus).toHaveBeenLastCalledWith({lesson_id:'lesson-owned',visualization_id:'v',expected_revision:3});
  act(()=>root.unmount());container.remove();
});
