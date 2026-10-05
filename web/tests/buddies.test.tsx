import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BuddyProvider, BuddyRail, useBuddies } from '@/components/buddies';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import type { BuddySnapshot } from '@/lib/buddies';
const {snapshot}=vi.hoisted(()=>({snapshot:vi.fn()}));
vi.mock('@/lib/buddies',()=>({buddyApi:{snapshot}}));
let root:Root,container:HTMLDivElement;
const data=(name:string):BuddySnapshot=>({profiles:[{id:name,name,avatar:'owl',color:'violet',style:'calm',concise:true,examples:true,proactive:false,revision:1,archived:false}],defaultBuddyId:name,courses:{},chats:{},modes:{},classes:[],responsibilities:{},lastChats:{},unread:{}});
function Probe(){const buddies=useBuddies();return <><span data-testid="identity">{buddies.active?.name||'loading'}</span><button onClick={()=>void buddies.refresh()}>Refresh</button><BuddyRail onSwitch={buddies.select} onHome={()=>{}} onSettings={()=>{}}/></>;}
beforeEach(()=>{vi.useFakeTimers();vi.clearAllMocks();(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.useRealTimers();});
async function render(node:ReactNode){await act(async()=>{root.render(node);});await act(async()=>{await vi.runOnlyPendingTimersAsync();});}
it('loads real profiles and exposes named selected avatar controls',async()=>{snapshot.mockResolvedValue(data('Nova'));await render(<BuddyProvider><Probe/></BuddyProvider>);expect(container.querySelector('[data-testid=identity]')?.textContent).toBe('Nova');expect(container.querySelector('button[aria-label="Open Nova"]')?.getAttribute('aria-pressed')).toBe('true');});
it('ignores an older response after switching accounts',async()=>{let oldResolve!:(value:BuddySnapshot)=>void;snapshot.mockImplementationOnce(()=>new Promise(resolve=>{oldResolve=resolve;})).mockResolvedValueOnce(data('New account'));await render(<BuddyProvider><Probe/></BuddyProvider>);await act(async()=>{window.dispatchEvent(new Event(ACCOUNT_CHANGED));});expect(container.textContent).toContain('New account');await act(async()=>{oldResolve(data('Previous account'));});expect(container.textContent).not.toContain('Previous account');});
it('shows a retry when profiles are unavailable',async()=>{snapshot.mockRejectedValue(new Error('Offline'));await render(<BuddyProvider><Probe/></BuddyProvider>);expect(container.querySelector('button[aria-label="Retry loading Buddies"]')).not.toBeNull();expect(container.querySelector('button[aria-label="Create Buddy"]')?.hasAttribute('disabled')).toBe(true);});
