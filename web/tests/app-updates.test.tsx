import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {UpdateSection} from '@/components/local-data-settings';
it('keeps failed update checks visible and retryable',async()=>{
 (globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
 const check=vi.fn().mockRejectedValue(new Error('Offline'));
 (window as Window & {formaDesktop?:unknown}).formaDesktop={updates:{status:async()=>({state:'idle',currentVersion:'1.0.0'}),check,onStatus:()=>()=>{}}};
 const container=document.createElement('div');document.body.appendChild(container);const root=createRoot(container);
 try{
  await act(async()=>root.render(<UpdateSection/>));
  expect(container.textContent).toContain('Open Learn 1.0.0');
  await act(async()=>{(container.querySelector('button') as HTMLButtonElement).click();});
  expect(check).toHaveBeenCalledOnce();expect(container.textContent).toContain('Could not check for updates');
  expect((container.querySelector('button') as HTMLButtonElement).disabled).toBe(false);
 }finally{act(()=>root.unmount());container.remove();delete (window as Window & {formaDesktop?:unknown}).formaDesktop;}
});
