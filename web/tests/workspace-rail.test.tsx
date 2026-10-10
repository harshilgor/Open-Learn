import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkspaceRail } from '@/components/workspace-rail';
import { ChatHistory } from '@/components/chat-history';

const { list, switchBuddy, open, navigate } = vi.hoisted(()=>({list:vi.fn(),switchBuddy:vi.fn(),open:vi.fn(),navigate:vi.fn()}));
vi.mock('@/components/buddies',()=>({
  useBuddies:()=>({active:{id:'nova',name:'Nova'},snapshot:{profiles:[{id:'nova',name:'Nova'},{id:'sage',name:'Sage'}],chats:{a:'nova',b:'nova',c:'sage'},unread:{}},refresh:async()=>{},edit:vi.fn()}),
  BuddyAvatar:({buddy}:{buddy:{name:string}})=><span>{buddy.name}</span>,
}));
vi.mock('@/components/account-access',()=>({AccountProfile:()=> <span>L</span>,AccountMenuActions:()=>null}));
vi.mock('@/lib/api',()=>({learningApi:{listChatSessions:list},LearningApiError:class extends Error {status=500;}}));
let container:HTMLDivElement,root:Root;
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);list.mockResolvedValue({sessions:[{id:'a',title:'Forces',goal:'Newton reasoning',updatedAt:new Date().toISOString(),turnCount:2},{id:'b',title:'Energy',goal:'Work and energy',updatedAt:new Date().toISOString(),turnCount:1},{id:'c',title:'Cells',goal:'Biology',courseId:'biology',updatedAt:new Date().toISOString(),turnCount:1}],total:3});});
afterEach(()=>{act(()=>root.unmount());container.remove();});
it('offers history only for the selected buddy with multiple chats and keeps switching separate',async()=>{
  await act(async()=>root.render(<WorkspaceRail activeSessionId="a" refreshKey={0} courses={[]} onSwitch={switchBuddy} onOpen={open} onNavigate={navigate}/>));
  expect(container.querySelector('[aria-label="Show chats with Nova"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Show chats with Sage"]')).toBeNull();
  act(()=> (container.querySelector('[aria-label="Open Sage"]') as HTMLButtonElement).click());
  expect(switchBuddy).toHaveBeenCalledWith('sage');expect(open).not.toHaveBeenCalled();
});
it('scopes buddy history, highlights the current chat, and opens the selected saved chat',async()=>{
  await act(async()=>{root.render(<ChatHistory activeSessionId="a" refreshKey={0} fixedBuddyId="nova" onOpen={open}/>);});
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
  expect(container.textContent).toContain('Forces');expect(container.textContent).not.toContain('Cells');
  expect(container.querySelector('[aria-current="true"]')?.getAttribute('title')).toBe('Forces');
  act(()=> (container.querySelector('button[title="Energy"]') as HTMLButtonElement).click());expect(open).toHaveBeenCalledWith('b');
});
it('finds chats across buddies by course name and puts pinned chats first',async()=>{
  localStorage.setItem('openlearn-pinned-chats-v1',JSON.stringify(['c']));
  await act(async()=>root.render(<ChatHistory activeSessionId="a" refreshKey={0} courses={[{id:'biology',name:'Biology 101'} as never]} onOpen={open}/>));
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
  expect(container.querySelector('ul button[title]')?.getAttribute('title')).toBe('Cells');
  const input=container.querySelector('input[type="search"]') as HTMLInputElement;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Biology 101');input.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(container.textContent).toContain('Cells');expect(container.textContent).not.toContain('Forces');
});
