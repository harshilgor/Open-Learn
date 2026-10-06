import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
const mocks=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>({request:mocks.request}));
vi.mock('@/lib/account-session',()=>({ACCOUNT_CHANGED:'account-changed',sessionToken:async()=>null}));
import {refreshAllowance,useAllowance} from '@/lib/usage-allowance';

it('clears a transient error after a successful unchanged allowance check',async()=>{
 const snapshot={windowId:'w',windowState:'active',serverTime:1,resetsAt:null,grantedMicrocredits:100,usedMicrocredits:10,heldMicrocredits:0,availableMicrocredits:90,revision:1,availability:'available',reasonCode:null};
 let fail=false;
 mocks.request.mockImplementation(async(path:string)=>{
  if(path.includes('/events'))return{events:[],nextRevision:1,latestRevision:1,hasMore:false,resnapshotRequired:false};
  if(fail)throw new Error('temporary outage');
  return snapshot;
 });
 (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
 let current:ReturnType<typeof useAllowance>|undefined;
 function Probe(){current=useAllowance();return null;}
 const container=document.createElement('div');document.body.appendChild(container);
 const root=createRoot(container);
 await act(async()=>root.render(<Probe/>));
 expect(current?.snapshot?.revision).toBe(1);
 fail=true;
 await act(async()=>{await refreshAllowance();});
 expect(current?.error).toBeTruthy();
 fail=false;
 await act(async()=>{await refreshAllowance();});
 expect(current?.error).toBe('');
 expect(current?.snapshot).toEqual(snapshot);
 await act(async()=>root.unmount());container.remove();
});
