import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, it, expect, vi} from 'vitest';
import {ReminderPreferences} from '@/components/reminder-preferences';
const {request}=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/api',()=>({request}));
vi.mock('@/components/ui/button',()=>({Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>)=><button {...props}/> }));
let root:Root,container:HTMLDivElement;
const prefs={timezone:'America/Los_Angeles',quietStart:22,quietEnd:8,channels:['inbox'],emailOptIn:false};
beforeEach(()=>{
 (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
 request.mockReset();container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();});
it('disables unconfigured email and saves in-app preferences without stale email settings',async()=>{
 request.mockResolvedValue({...prefs,emailAvailable:false,emailOptIn:true,channels:['inbox','email']});
 await act(async()=>root.render(<ReminderPreferences/>));
 const checkbox=Array.from(container.querySelectorAll('label')).find(e=>e.textContent?.includes('Email notifications'))!.querySelector('input')!;
 expect(checkbox.disabled).toBe(true);expect(checkbox.checked).toBe(false);
 expect(container.textContent).toContain('Open Learn inbox and linked conversations');
 await act(async()=>container.querySelector('button')!.click());
 const saved=JSON.parse(request.mock.calls[1][1].body);
 expect(saved.channels).toEqual(['inbox']);expect(saved.emailOptIn).toBe(false);
 expect(container.textContent).toContain('Preferences saved');
});
it('allows email only when the server advertises configured delivery',async()=>{
 request.mockResolvedValue({...prefs,emailAvailable:true});
 await act(async()=>root.render(<ReminderPreferences/>));
 const checkbox=Array.from(container.querySelectorAll('label')).find(e=>e.textContent?.includes('Email notifications'))!.querySelector('input')!;
 expect(checkbox.disabled).toBe(false);
 await act(async()=>checkbox.click());
 await act(async()=>container.querySelector('button')!.click());
 expect(JSON.parse(request.mock.calls[1][1].body).channels).toEqual(['inbox','email']);
});
it('fails closed with an older API that does not expose email readiness',async()=>{
 request.mockResolvedValue(prefs);
 await act(async()=>root.render(<ReminderPreferences/>));
 const checkbox=Array.from(container.querySelectorAll('label')).find(e=>e.textContent?.includes('Email notifications'))!.querySelector('input')!;
 expect(checkbox.disabled).toBe(true);
});
