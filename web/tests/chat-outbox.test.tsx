import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { useChatOutbox } from '@/hooks/use-chat-outbox';
import { restoreOutbox } from '@/lib/chat-outbox';

let root:Root, container:HTMLDivElement;
const send=vi.fn();
let outbox:ReturnType<typeof useChatOutbox>;
function Probe({storageKey='test-outbox',enabled=true}:{storageKey?:string;enabled?:boolean}){const current=useChatOutbox({storageKey,enabled,turnCount:0,send});useEffect(()=>{outbox=current;});return <div>{current.messages.map(item=><span key={item.id}>{item.text}:{item.status}</span>)}</div>;}
beforeEach(()=>{sessionStorage.clear();vi.clearAllMocks();(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
it('shows messages immediately and sends one at a time in FIFO order',async()=>{
  let firstDone!:()=>void;send.mockImplementationOnce(()=>new Promise<void>(resolve=>{firstDone=resolve;})).mockResolvedValue(undefined);
  await act(async()=>root.render(<Probe/>));
  await act(async()=>{outbox.enqueue('First');outbox.enqueue('Second');});
  expect(container.textContent).toContain('First:sending');expect(container.textContent).toContain('Second:queued');expect(send).toHaveBeenCalledTimes(1);
  await act(async()=>firstDone());
  expect(send.mock.calls.map(call=>call[0].text)).toEqual(['First','Second']);expect(outbox.messages).toHaveLength(0);
});
it('starts the next queued message as soon as the prior message is durably accepted',async()=>{
  let acceptFirst!:()=>void;
  send.mockImplementationOnce((_message,onAccepted)=>new Promise<void>(()=>{acceptFirst=onAccepted;})).mockImplementationOnce(()=>new Promise<void>(()=>{}));
  await act(async()=>root.render(<Probe/>));
  await act(async()=>{outbox.enqueue('First');outbox.enqueue('Second');});
  expect(send).toHaveBeenCalledTimes(1);
  await act(async()=>acceptFirst());
  expect(send).toHaveBeenCalledTimes(2);
  expect(send.mock.calls.map(call=>call[0].text)).toEqual(['First','Second']);
  expect(outbox.messages.find(item=>item.text==='First')?.status).toBe('accepted');
});
it('retains a failed message while allowing later messages to send',async()=>{
  send.mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(undefined);
  await act(async()=>root.render(<Probe/>));
  await act(async()=>{outbox.enqueue('First');outbox.enqueue('Second');});
  expect(outbox.messages.find(item=>item.text==='First')?.status).toBe('failed');
  expect(send.mock.calls.map(call=>call[0].text)).toEqual(['First','Second']);
  const failed=outbox.messages.find(item=>item.text==='First')!;
  await act(async()=>outbox.retry(failed.id));
  expect(send.mock.calls.map(call=>call[0].text)).toEqual(['First','Second','First']);
});
it('retries an interrupted send with its original idempotency key after reload',async()=>{
  sessionStorage.setItem('test-outbox',JSON.stringify([{id:'saved',text:'Retain me',createdAt:1,status:'sending',baseTurn:0}]));
  let finish!:(value:void)=>void;send.mockImplementationOnce(()=>new Promise<void>(resolve=>{finish=resolve;}));
  await act(async()=>root.render(<Probe/>));
  expect(send).toHaveBeenCalledTimes(1);expect(send.mock.calls[0][0].id).toBe('saved');expect(outbox.messages[0].status).toBe('sending');
  await act(async()=>finish());expect(restoreOutbox('{broken')).toEqual([]);
});
it('restores saved text when the buddy identity finishes loading',async()=>{
  sessionStorage.setItem('test-outbox',JSON.stringify([{id:'saved',text:'Keep this draft',createdAt:1,status:'queued',baseTurn:0}]));
  send.mockImplementationOnce(()=>new Promise<void>(()=>{}));
  await act(async()=>root.render(<Probe storageKey="connecting" enabled={false}/>));
  await act(async()=>root.render(<Probe/>));
  expect(outbox.messages[0].text).toBe('Keep this draft');
  expect(send).toHaveBeenCalledTimes(1);expect(send.mock.calls[0][0].id).toBe('saved');
});
it('pauses for a mode decision and preserves an in-flight message when removing another',async()=>{
  let done!:(result:'choice')=>void;send.mockImplementationOnce(()=>new Promise<'choice'>(resolve=>{done=resolve;})).mockResolvedValue(undefined);
  await act(async()=>root.render(<Probe/>));await act(async()=>{outbox.enqueue('First');outbox.enqueue('Second');});
  await act(async()=>outbox.remove(outbox.messages[1].id));expect(outbox.messages[0].status).toBe('sending');
  await act(async()=>{outbox.enqueue('Third');done('choice');});expect(send).toHaveBeenCalledTimes(1);
  await act(async()=>outbox.resolveChoice());expect(send.mock.calls.map(call=>call[0].text)).toEqual(['First','Third']);
});
