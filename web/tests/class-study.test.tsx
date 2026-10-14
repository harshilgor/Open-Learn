import React,{act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {ClassVisualEditor} from '@/components/class-visual-editor';
import type {VisualSpec} from '@/components/class-visual';
import {layoutClassVisual} from '@/lib/class-visual-layout';
import {restoreOutbox} from '@/lib/chat-outbox';
import {ClassDocument} from '@/components/class-document';

const {request}=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>({request,learningApi:{}}));

let root:Root,container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
const spec:VisualSpec={kind:'concept_map',title:'Cell',description:'Parts of a cell',nodes:[{id:'cell',label:'Cell'},{id:'membrane',label:'Membrane'}],edges:[{source:'cell',target:'membrane',label:'has'}],columns:[],rows:[],steps:[],points:[],xLabel:'',yLabel:''};
it('lets students edit diagram labels while preserving source relationships',()=>{
  const save=vi.fn();act(()=>root.render(<ClassVisualEditor spec={spec} busy={false} onSave={save} onCancel={()=>{}}/>));
  const label=[...container.querySelectorAll('label')].find(label=>label.textContent?.startsWith('Concept 2'))!;const input=label.querySelector('input')!;
  act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Cell boundary');input.dispatchEvent(new Event('input',{bubbles:true}));});
  act(()=>container.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(save.mock.calls[0][0].nodes[1]).toEqual({id:'membrane',label:'Cell boundary'});
  expect(save.mock.calls[0][0].edges).toEqual(spec.edges);
  expect(spec.nodes[1].label).toBe('Membrane');
});
it('places a directed root above its child and honors explicit schematic coordinates',()=>{
  const layout=layoutClassVisual(spec);expect(layout.positions.get('cell')!.y).toBeLessThan(layout.positions.get('membrane')!.y);
  const explicit=layoutClassVisual({...spec,nodes:[{id:'cell',label:'Cell',x:0,y:1}]});expect(explicit.positions.get('cell')!.x).toBe(90);
});
it('retains the original class moment and selected note when a pending message is restored',()=>{
  const context={classId:'class_one',anchorMs:90000,noteRefs:[{blockId:'note_one',revision:2}]};
  const restored=restoreOutbox(JSON.stringify([{id:'question',text:'Why?',createdAt:1,status:'sending',baseTurn:0,classContext:context}]));
  expect(restored[0].status).toBe('queued');expect(restored[0].classContext).toEqual(context);
});
it('preserves an unsaved note draft when background source updates arrive',async()=>{
  let revision=1;
  request.mockImplementation(async(path:string)=>path.endsWith('/document')?{items:[{id:'note',revision,title:'Cell',body:revision===1?'Original text':'Updated generated text',studentEdited:false,state:'ready',generated:{title:'Cell',body:'Original text',segmentIds:[]},suggestion:null}],nextCursor:null,totalCount:1}:{items:[],nextCursor:null});
  await act(async()=>root.render(<ClassDocument classId="class_one" version={1}/>));
  const edit=[...container.querySelectorAll('button')].find(button=>button.textContent==='Edit notes')!;
  act(()=>edit.click());const input=container.querySelector('textarea')!;
  act(()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'My unsaved explanation');input.dispatchEvent(new Event('input',{bubbles:true}));});
  revision=2;await act(async()=>root.render(<ClassDocument classId="class_one" version={2}/>));
  expect(container.querySelector('textarea')!.value).toBe('My unsaved explanation');
  expect([...container.querySelectorAll('button')].some(button=>button.textContent==='Save')).toBe(true);
});
