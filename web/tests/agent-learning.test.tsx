import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {LearningContinuationPanel} from '@/components/assistant/learning-continuation';
import type {AgentTask} from '@/lib/assistant-client';
const mocks=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>mocks);
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'account-changed'}));
vi.mock('@/components/quiz-workspace',()=>({QuizWorkspace:({quizId}:{quizId:string})=><p>Existing quiz {quizId}</p>}));
let root:Root,container:HTMLDivElement;
const task:AgentTask={schemaVersion:2,id:'task',revision:9,sessionId:'session',kind:'sandbox_lab',message:'Lab',status:'completed',phase:'complete',completion:{status:'verified'},artifacts:[],pendingRequests:[],allowedCommands:[]};
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.clearAllMocks();sessionStorage.clear();mocks.request.mockResolvedValue({items:[]});container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function mount(value=task){await act(async()=>root.render(<LearningContinuationPanel task={value}/>));}
it('requests teaching with exact completed revision and displays safe content',async()=>{
  await mount();mocks.request.mockResolvedValueOnce({id:'learning',kind:'teach',status:'completed',lesson:{title:'Speed',blocks:[{id:'block',heading:'Calculation',body:'<script>unsafe()</script> 5 cm/s'}]}});
  await act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Explain result')!.click());
  expect(mocks.request).toHaveBeenCalledWith('/v1/assistant/tasks/task/continuations',expect.objectContaining({method:'POST',headers:{'Idempotency-Key':expect.any(String)},body:JSON.stringify({kind:'teach',expectedRevision:9})}));
  expect(container.textContent).toContain('5 cm/s');expect(container.querySelector('script')).toBeNull();
});
it('retries a lost response using its same identity',async()=>{
  await mount();mocks.request.mockRejectedValueOnce(new Error('Connection lost'));
  const button=[...container.querySelectorAll('button')].find(button=>button.textContent==='Explain result')!;
  await act(async()=>button.click());const first=mocks.request.mock.calls.at(-1);
  mocks.request.mockResolvedValueOnce({id:'learning',kind:'teach',status:'pending'});
  await act(async()=>button.click());expect(mocks.request.mock.calls.at(-1)).toEqual(first);
});
it('does not allow an unverified or partial result to create learning',async()=>{
  await mount({...task,status:'completed_partial',completion:{status:'partial'}});
  expect(container.textContent).toBe('');expect(mocks.request).not.toHaveBeenCalled();
});
it('restores durable quiz and opens the existing quiz workspace',async()=>{
  mocks.request.mockResolvedValue({items:[{id:'learning',kind:'quiz',status:'completed',quizId:'quiz-owned'}]});
  await mount();await act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Open practice quiz')!.click());
  expect(container.textContent).toContain('Existing quiz quiz-owned');
  act(()=>window.dispatchEvent(new Event('account-changed')));expect(container.textContent).not.toContain('Existing quiz quiz-owned');
});
