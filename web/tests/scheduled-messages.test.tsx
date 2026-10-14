import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {useScheduledMessages} from '@/lib/scheduled-messages';
import {ACCOUNT_CHANGED} from '@/lib/account-session';

const {request}=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>({request}));
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'openlearn-account-changed'}));
let root:Root,container:HTMLDivElement;
function View({session}:{session:string|null}) {
  const messages=useScheduledMessages(session);
  return <div>{messages.map(m=><p key={m.id}>{m.body}</p>)}</div>;
}
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.useFakeTimers(); request.mockReset(); request.mockResolvedValue({messages:[{id:'one',body:'Ready'}]});
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
  Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.useRealTimers();});
it('loads persisted results for the selected conversation and aborts on unmount',async()=>{
  await act(async()=>root.render(<View session="session / one"/>));
  expect(request.mock.calls[0][0]).toContain('sessionId=session%20%2F%20one');
  expect(container.textContent).toBe('Ready');
  const signal=request.mock.calls[0][1].signal;
  await act(async()=>root.render(<View session={null}/>));
  expect(signal.aborted).toBe(true);expect(container.textContent).toBe('');
});
it('discards late results when switching conversations',async()=>{
  let resolve!:(value:unknown)=>void;
  request.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  await act(async()=>root.render(<View session="old"/>));
  request.mockResolvedValue({messages:[{id:'two',body:'New session'}]});
  await act(async()=>root.render(<View session="new"/>));
  await act(async()=>resolve({messages:[{id:'old',body:'Private old result'}]}));
  expect(container.textContent).toBe('New session');
});
it('clears account results and stops further requests after account change',async()=>{
  await act(async()=>root.render(<View session="session"/>));
  await act(async()=>window.dispatchEvent(new Event(ACCOUNT_CHANGED)));
  await act(async()=>vi.advanceTimersByTime(15000));
  expect(container.textContent).toBe('');expect(request).toHaveBeenCalledTimes(1);
});
it('avoids hidden polling and recovers on visibility change',async()=>{
  Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
  await act(async()=>root.render(<View session="session"/>));
  await act(async()=>vi.advanceTimersByTime(10000));
  expect(request).not.toHaveBeenCalled();
  Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
  await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  expect(container.textContent).toBe('Ready');
});
