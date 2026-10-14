import React,{act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {ClassDeviceStrip} from '@/components/class-device-strip';
const {status}=vi.hoisted(()=>({status:vi.fn()}));
vi.mock('@/lib/class-devices',()=>({classDevices:{status,command:vi.fn()}}));
let root:Root,container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.useFakeTimers();vi.setSystemTime(100000);container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.useRealTimers();vi.clearAllMocks();});
it('shows confirmed elapsed time and zero battery, and becomes stale even if polling fails',async()=>{
  status.mockResolvedValueOnce({run:{id:'run',state:'paused',audioEndMs:61000,lastSeenAt:100,stale:false,batteryPercent:0,backlog:2},commands:[]});
  status.mockRejectedValue(new Error('Offline'));
  await act(async()=>root.render(<ClassDeviceStrip classId="class"/>));
  expect(container.textContent).toContain('Captured 1:01');expect(container.textContent).toContain('Battery 0%');expect(container.textContent).toContain('2 audio slices waiting');
  await act(async()=>vi.advanceTimersByTimeAsync(16000));
  expect(container.textContent).toContain('Connection stale');expect(container.textContent).toContain('Last report 16s ago');expect(container.textContent).toContain('Captured 1:01');
});
