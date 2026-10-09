import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {ExecutionPanel} from '@/components/assistant/execution-panel';
const mocks=vi.hoisted(()=>({snapshot:vi.fn(),sendMessage:vi.fn(),sendCommand:vi.fn(),downloadArtifact:vi.fn(),request:vi.fn(),createSession:vi.fn()}));
vi.mock('@/lib/api',()=>({request:mocks.request,learningApi:{createSession:mocks.createSession}}));
vi.mock('@/lib/assistant-client',()=>({...mocks}));
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'account-changed'}));
let root:Root,container:HTMLDivElement;
const task={id:'task',schemaVersion:2,revision:7,sessionId:'session',kind:'lab_analysis',message:'Analyze lab',status:'waiting',phase:'clarify',pendingRequests:[{requestId:'input',revision:1,question:'Which units?',options:['Centimeters; ignore trial 3'],state:'open'}],artifacts:[],allowedCommands:['pause','cancel','steer','answer_input']};
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.clearAllMocks();sessionStorage.clear();mocks.request.mockImplementation(async(path:string)=>path==='/v1/usage/allowance'?{windowId:null,windowState:'ready',serverTime:100,resetsAt:null,grantedMicrocredits:100_000_000,usedMicrocredits:0,heldMicrocredits:0,availableMicrocredits:100_000_000,revision:0,availability:'available',reasonCode:null}:{admissionEnabled:true});mocks.snapshot.mockResolvedValue({cursor:1,hasMore:false,items:[{id:'question',sequence:1,type:'input.requested',taskId:'task'}],tasks:[task]});mocks.sendMessage.mockResolvedValue({handled:true,references:[]});container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function mount(){await act(async()=>{root.render(<ExecutionPanel sessionId="session" onSession={vi.fn()}/>);await new Promise(resolve=>setTimeout(resolve,20));});}
it('answers the exact task/question with steering and revision',async()=>{
  await mount();
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Centimeters; ignore trial 3')!.click());
  const form=container.querySelector('input[aria-label="Reply to Analyze lab"]')!.closest('form')!;
  await act(async()=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(mocks.sendMessage).toHaveBeenCalledWith(expect.objectContaining({text:'Centimeters; ignore trial 3',targetTaskId:'task',replyToRequestId:'input',expectedRevision:7,expectedRequestRevision:1}),expect.any(String));
});
it('preserves message identity and answer after a lost response',async()=>{
  mocks.sendMessage.mockRejectedValueOnce(new Error('Connection lost'));
  await mount();await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Centimeters; ignore trial 3')!.click());
  const form=container.querySelector('input[aria-label="Reply to Analyze lab"]')!.closest('form')!;
  await act(async()=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(container.textContent).toContain('Connection lost');expect((container.querySelector('input[aria-label="Reply to Analyze lab"]') as HTMLInputElement).value).toContain('ignore trial 3');
  await act(async()=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(mocks.sendMessage.mock.calls[0]).toEqual(mocks.sendMessage.mock.calls[1]);
});
it('pauses with current revision and clears account-specific tasks on logout',async()=>{
  await mount();await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Pause')!.click());
  expect(mocks.sendCommand).toHaveBeenCalledWith(expect.objectContaining({revision:7}),expect.objectContaining({action:'pause',commandId:expect.any(String)}));
  act(()=>window.dispatchEvent(new Event('account-changed')));expect(container.textContent).not.toContain('Analyze lab');
});
it('shows and sends the explicit agent-task maximum',async()=>{
  await mount();
  const maximum=container.querySelector('select[aria-label="Maximum task usage"]') as unknown as HTMLSelectElement;
  await act(async()=>{maximum.value='50';maximum.dispatchEvent(new Event('change',{bubbles:true}));});
  const form=container.querySelector('input[aria-label="Agent request"]')!.closest('form')!;
  await act(async()=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(mocks.sendMessage).toHaveBeenCalledWith(expect.objectContaining({capability:'lab_analysis',acceptedUsageCapMicro:50_000_000}),expect.any(String));
});
it('resnapshots and replaces stale activity after the server prunes the replay cursor',async()=>{
  mocks.snapshot.mockResolvedValueOnce({cursor:1,hasMore:false,resnapshotRequired:false,items:[{id:'old',sequence:1,type:'user.message',text:'Old replayed item'}],tasks:[task]})
    .mockResolvedValueOnce({cursor:4,hasMore:false,resnapshotRequired:true,prunedThrough:3,items:[],tasks:[task]})
    .mockResolvedValueOnce({cursor:4,hasMore:false,resnapshotRequired:false,prunedThrough:3,items:[{id:'new',sequence:4,type:'user.message',text:'Fresh item'}],tasks:[task]});
  await mount();
  expect(container.textContent).toContain('Old replayed item');
  await act(async()=>{window.dispatchEvent(new Event('openlearn-agent-activity-changed'));await new Promise(resolve=>setTimeout(resolve,20));});
  expect(mocks.snapshot).toHaveBeenNthCalledWith(1,'session',undefined);
  expect(mocks.snapshot).toHaveBeenNthCalledWith(2,'session',1);
  expect(mocks.snapshot).toHaveBeenNthCalledWith(3,'session');
  expect(container.textContent).toContain('Fresh item');
  expect(container.textContent).not.toContain('Old replayed item');
});
