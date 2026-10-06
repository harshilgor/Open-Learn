import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { SettingsPage } from '@/components/settings-page';
vi.mock('next-themes',()=>({useTheme:()=>({theme:'dark',setTheme:vi.fn()})}));
vi.mock('@/components/account-settings',()=>({AccountSettings:({section}:{section:string})=><p>{section} controls</p>}));
vi.mock('@/components/site-connections',()=>({SiteConnections:()=> <p>Connections</p>}));
vi.mock('@/components/usage-settings',()=>({UsageSettings:()=> <p>Usage activity</p>}));
vi.mock('@/components/provider-settings',()=>({ProviderSettings:()=> <p>Service status</p>}));
vi.mock('@/components/local-data-settings',()=>({UpdateSection:()=> <p>Desktop updater</p>,DataActionsSection:()=> <p>Local data</p>}));
vi.mock('@/components/academic-reminder-settings',()=>({AcademicReminderSettings:()=>null}));
vi.mock('@/components/review-notification-settings',()=>({ReviewNotificationSettings:()=>null}));
let root:ReturnType<typeof createRoot>,container:HTMLDivElement;
afterEach(()=>{act(()=>root.unmount());container.remove();delete (window as Window & {formaDesktop?:unknown}).formaDesktop;});
async function render(category:Parameters<typeof SettingsPage>[0]['category']){
 (globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
 container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
 await act(async()=>root.render(<SettingsPage category={category} onCategoryChange={vi.fn()} onBack={vi.fn()}/>));
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));});
}
it('keeps Usage separate and removes redundant destinations on web',async()=>{
 await render('usage');
 const labels=Array.from(container.querySelectorAll('nav button')).map(button=>button.textContent);
 expect(labels).toContain('Usage');expect(labels).toContain('Appearance');expect(labels).toContain('Help');
 for(const removed of ['AI service','Connected websites','Audio & recordings','Updates'])expect(labels).not.toContain(removed);
 expect(container.textContent).toContain('Plan allowances are not configured yet');
});
it('shows Updates only for an installed desktop app',async()=>{
 (window as Window & {formaDesktop?:unknown}).formaDesktop={preferences:{},version:'1.0.0',platform:'win32'};
 await render('updates');
 expect(Array.from(container.querySelectorAll('nav button')).map(button=>button.textContent)).toContain('Updates');
 expect(container.textContent).toContain('Desktop updater');
});
it('preserves old recording links within Learning',async()=>{
 await render('audio');
 expect(container.querySelector('h1')?.textContent).toBe('Learning');
 expect(container.textContent).toContain('Recording defaults');
});
