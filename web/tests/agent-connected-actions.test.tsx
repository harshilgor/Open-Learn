import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ConnectedTaskPanel} from '@/components/assistant/connected-task-panel';
import type {AgentTask} from '@/lib/assistant-client';
const mocks=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>mocks);
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'account-changed'}));
let root:Root,container:HTMLDivElement;
const task:AgentTask={schemaVersion:2,id:'task',revision:7,sessionId:'session',kind:'research',message:'Report',status:'completed',phase:'complete',artifacts:[],pendingRequests:[],allowedCommands:[]};
const action={id:'action',revision:1,status:'draft',actionHash:'a'.repeat(64),expiresAt:1900000000,account:'student@example.com',kind:'gmail_send',mail:{to:['professor@example.com'],cc:[],subject:'Office hours',body:'<script>do not execute</script>'},attachments:[{id:'file',name:'report.md',size:200}]};
let actions:unknown[]=[];
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.clearAllMocks();actions=[action];mocks.request.mockImplementation(async(path:string)=>path.endsWith('app-connections')?{items:[],enabled:true,delegationEnabled:true}:path.endsWith('/actions')?{items:actions}:{items:[]});container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function mount(){await act(async()=>root.render(<ConnectedTaskPanel task={task}/>));const details=container.querySelector('details')!;await act(async()=>{details.open=true;details.dispatchEvent(new Event('toggle'));});}
function button(label:string){return [...container.querySelectorAll('button')].find(value=>value.textContent===label)!;}
it('shows exact account recipients files and plain content before approval',async()=>{
  await mount();expect(container.textContent).toContain('student@example.com');expect(container.textContent).toContain('professor@example.com');expect(container.textContent).toContain('report.md (200 bytes)');expect(container.querySelector('script')).toBeNull();
  expect(mocks.request.mock.calls.every(call=>call[1]?.method!=='POST')).toBe(true);
  await act(async()=>button('Approve this exact action').click());
  expect(mocks.request).toHaveBeenCalledWith('/v1/assistant/approvals/action/decision',expect.objectContaining({headers:{'Idempotency-Key':expect.any(String)},body:JSON.stringify({decision:'approve',expectedRevision:1,actionHash:'a'.repeat(64)})}));
});
it('retries a lost decision with its same identity',async()=>{
  await mount();mocks.request.mockRejectedValueOnce(new Error('Lost response'));
  await act(async()=>button('Approve this exact action').click());const first=mocks.request.mock.calls.at(-1);
  await act(async()=>button('Approve this exact action').click());expect(mocks.request.mock.calls.findLast(call=>call[0].endsWith('/decision'))).toEqual(first);
});
it('unknown outcomes offer reconciliation rather than another send',async()=>{
  actions=[{...action,status:'outcome_unknown',operation:{status:'outcome_unknown',reasonCode:'timeout'}}];await mount();
  expect(button('Approve this exact action')).toBeUndefined();expect(container.textContent).toContain('will not be automatically sent again');
  await act(async()=>button('Check provider outcome').click());expect(mocks.request).toHaveBeenCalledWith('/v1/assistant/approvals/action/reconcile',{method:'POST'});
});
it('account change clears private review and late data',async()=>{
  await mount();expect(container.textContent).toContain('professor@example.com');
  await act(async()=>window.dispatchEvent(new Event('account-changed')));expect(container.textContent).not.toContain('professor@example.com');expect(container.textContent).not.toContain('student@example.com');
});
