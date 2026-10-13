"use client";
import { useEffect, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { usePathname } from 'next/navigation';
import { LogIn, LogOut, UserRound } from 'lucide-react';
import { supabaseAccount } from '@/lib/supabase-account';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog';
import { DropdownMenuItem, DropdownMenuSeparator } from './ui/dropdown-menu';
import { BuddyProvider } from './buddies';
import type { AuthMode } from './auth-flow';
import { LandingPage } from './landing-page';
import styles from './auth-flow.module.css';
const AuthForm = dynamic(() => import('./auth-flow').then(module => module.AuthForm), {
  loading: () => <p role="status">Opening sign in…</p>,
});
function useSignedIn(){const [signedIn,setSignedIn]=useState<boolean|null>(null);useEffect(()=>{const client=supabaseAccount();if(!client)return;let alive=true;void client.auth.getSession().then(({data})=>{if(alive)setSignedIn(!!data.session);});const {data}=client.auth.onAuthStateChange((_event,session)=>{if(alive)setSignedIn(!!session);});return()=>{alive=false;data.subscription.unsubscribe();};},[]);return signedIn;}
export function AccountAccess(){const signedIn=useSignedIn(),path=usePathname();const [mode,setMode]=useState<AuthMode|null>(null);useEffect(()=>{const open=(event:Event)=>setMode((event as CustomEvent<AuthMode>).detail);window.addEventListener('openlearn-auth-open',open);return()=>window.removeEventListener('openlearn-auth-open',open);},[]);if(signedIn!==false||path.startsWith('/auth/'))return null;return <Dialog open={!!mode} onOpenChange={open=>{if(!open)setMode(null);}}><DialogContent className={styles.modal}><DialogTitle className={styles.srOnly}>{mode==='signup'?'Create an account':'Log in'}</DialogTitle><DialogDescription className={styles.srOnly}>Continue with Google or a secure email link.</DialogDescription><AuthForm key={mode} mode={mode||'login'} onModeChange={setMode}/></DialogContent></Dialog>;}
export function AccountMenuActions(){const signedIn=useSignedIn();if(signedIn===null)return null;return <><DropdownMenuSeparator/>{signedIn?<DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-out')}><LogOut size={15}/>Sign out</DropdownMenuItem>:<><DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-in')}><LogIn size={15}/>Log in</DropdownMenuItem><DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-up')}><UserRound size={15}/>Create free account</DropdownMenuItem></>}</>;}

export function AccountWorkspace({children}:{children:ReactNode}){const path=usePathname(),signedIn=useSignedIn();if(path.startsWith('/auth/'))return <>{children}</>;if(process.env.NEXT_PUBLIC_SUPABASE_URL&&signedIn===null)return <main className={styles.guest}><p role="status">Opening your study space…</p></main>;if(signedIn===false)return <LandingPage/>;return <BuddyProvider>{children}</BuddyProvider>;}

export function AccountProfile(){const [name,setName]=useState('Learner');useEffect(()=>{const client=supabaseAccount();if(!client)return;let alive=true;const update=(user:{email?:string;user_metadata?:Record<string,unknown>}|undefined)=>{if(alive)setName(String(user?.user_metadata?.full_name||user?.email?.split('@')[0]||'Guest'));};void client.auth.getSession().then(({data})=>update(data.session?.user));const {data}=client.auth.onAuthStateChange((_event,session)=>update(session?.user));return()=>{alive=false;data.subscription.unsubscribe();};},[]);return <><span className="avatar">{name.charAt(0).toUpperCase()}</span><div>{name}</div></>;}
