import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {ResponsibilitiesPanel} from '@/components/assistant/responsibilities-panel';
const {request}=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>({request}));
let root:Root,container:HTMLDivElement;
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  request.mockReset();request.mockImplementation(async(path:string)=>path.endsWith('/responsibilities')?{responsibilities:[]}:{notifications:[]});
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();});
it('requires a course conversation and shows empty inbox',async()=>{
  await act(async()=>{root.render(<ResponsibilitiesPanel sessionId={null}/>);await new Promise(r=>setTimeout(r,20));});
  expect(container.textContent).toContain('Open a course conversation');expect(container.textContent).toContain('No responsibility updates');
});
it('previews three occurrences before enabling save',async()=>{
  await act(async()=>{root.render(<ResponsibilitiesPanel sessionId="session" courseId="course"/>);await new Promise(r=>setTimeout(r,20));});
  const save=()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Save responsibility') as HTMLButtonElement;
  expect(save().disabled).toBe(true);
  request.mockImplementation(async(path:string)=>path.endsWith('/preview')?{nextOccurrences:[1800000000,1800604800,1801209600]}:path.endsWith('/responsibilities')?{responsibilities:[]}:{notifications:[]});
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Preview schedule')!.click());
  expect(container.querySelectorAll('[aria-label="Next three occurrences"] li')).toHaveLength(3);expect(save().disabled).toBe(false);
});
it('distinguishes disabling future work from stopping all with revision',async()=>{
  request.mockImplementation(async(path:string)=>path.endsWith('/responsibilities')?{responsibilities:[{id:'r',revision:4,status:'active',spec:{goal:'Prepare physics',timezone:'America/Los_Angeles'},nextOccurrences:[]}]}:{notifications:[]});
  await act(async()=>{root.render(<ResponsibilitiesPanel sessionId="session" courseId="course"/>);await new Promise(r=>setTimeout(r,20));});
  await act(async()=>{await new Promise(r=>setTimeout(r,40));});
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Disable future runs')!.click());
  expect(request).toHaveBeenCalledWith('/v1/assistant/responsibilities/r/commands',expect.objectContaining({body:JSON.stringify({action:'disable',expectedRevision:4})}));
  expect(container.textContent).toContain('Stop all');
});
