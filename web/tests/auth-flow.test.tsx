import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { AuthForm, SignOutScreen } from '@/components/auth-flow';
const auth = vi.hoisted(()=>({signInWithOtp:vi.fn(),signInWithOAuth:vi.fn()}));
vi.mock('@/lib/supabase-account',()=>({supabaseAccount:()=>({auth})}));
vi.mock('@/lib/account-session',()=>({signOut:vi.fn()}));
let root:ReturnType<typeof createRoot>,container:HTMLDivElement;
afterEach(()=>{act(()=>root.unmount());container.remove();vi.clearAllMocks();});
async function render(element:React.ReactNode){
 (globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
 container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
 await act(async()=>root.render(element));
}
async function submit(){await act(async()=>container.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));}
it('creates accounts only in the signup flow and offers a resend countdown',async()=>{
 auth.signInWithOtp.mockResolvedValue({error:null});await render(<AuthForm mode="signup"/>);await submit();
 expect(auth.signInWithOtp.mock.calls[0][0].options.shouldCreateUser).toBe(true);
 expect(container.textContent).toContain('Check your inbox');
 const resend=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Resend link in'))!;
 expect(resend.disabled).toBe(true);
 await act(async()=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent==='Use a different email')!.click());
 expect(container.querySelector('input[type=email]')).toBeTruthy();
});
it('does not create users during email login and recovers from a provider error',async()=>{
 auth.signInWithOtp.mockResolvedValue({error:new Error('Please create an account first.')});await render(<AuthForm mode="login"/>);await submit();
 expect(auth.signInWithOtp.mock.calls[0][0].options.shouldCreateUser).toBe(false);
 expect(container.querySelector('[role=alert]')?.textContent).toContain('create an account');
 expect(container.querySelector('a[href="/auth/sign-up"]')).toBeTruthy();
 expect(container.querySelector<HTMLButtonElement>('button[type=submit],form button')!.disabled).toBe(false);
});
it('starts Google OAuth using the existing PKCE callback',async()=>{
 auth.signInWithOAuth.mockResolvedValue({error:new Error('Try again')});await render(<AuthForm mode="login"/>);
 await act(async()=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent==='Continue with Google')!.click());
 expect(auth.signInWithOAuth).toHaveBeenCalledWith({provider:'google',options:{redirectTo:expect.stringContaining('/auth/callback')}});
});
it('offers a clear sign-out confirmation and a return path',async()=>{
 await render(<SignOutScreen/>);expect(container.textContent).toContain('Sign out of Open Learn?');expect(container.textContent).toContain('Stay signed in');
 await act(async()=>root.render(<SignOutScreen key="complete" signedOut/>));expect(container.textContent).toContain('You’re signed out');expect(container.querySelector('a[href="/auth/sign-in"]')).toBeTruthy();
});
