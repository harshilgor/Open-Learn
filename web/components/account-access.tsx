"use client";
import { useEffect, useState, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { LogIn, LogOut, UserRound } from 'lucide-react';
import { supabaseAccount } from '@/lib/supabase-account';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog';
import { DropdownMenuItem, DropdownMenuSeparator } from './ui/dropdown-menu';
import { BuddyProvider } from './buddies';
import { AuthForm, type AuthMode } from './auth-flow';
import styles from './auth-flow.module.css';
function useSignedIn(){const [signedIn,setSignedIn]=useState<boolean|null>(null);useEffect(()=>{const client=supabaseAccount();if(!client)return;let alive=true;void client.auth.getSession().then(({data})=>{if(alive)setSignedIn(!!data.session);});const {data}=client.auth.onAuthStateChange((_event,session)=>{if(alive)setSignedIn(!!session);});return()=>{alive=false;data.subscription.unsubscribe();};},[]);return signedIn;}
export function AccountAccess(){const signedIn=useSignedIn(),path=usePathname();const [mode,setMode]=useState<AuthMode|null>(null);if(signedIn!==false||path.startsWith('/auth/'))return null;return <><div className={styles.access} aria-label="Account access"><button onClick={()=>setMode('login')}>Log in</button><button onClick={()=>setMode('signup')}>Sign up for free</button></div><Dialog open={!!mode} onOpenChange={open=>{if(!open)setMode(null);}}><DialogContent className={styles.modal}><DialogTitle className={styles.srOnly}>{mode==='signup'?'Create an account':'Log in'}</DialogTitle><DialogDescription className={styles.srOnly}>Continue with Google or a secure email link.</DialogDescription><AuthForm key={mode} mode={mode||'login'} onModeChange={setMode}/></DialogContent></Dialog></>;}
export function AccountMenuActions(){const signedIn=useSignedIn();if(signedIn===null)return null;return <><DropdownMenuSeparator/>{signedIn?<DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-out')}><LogOut size={15}/>Sign out</DropdownMenuItem>:<><DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-in')}><LogIn size={15}/>Log in</DropdownMenuItem><DropdownMenuItem onSelect={()=>window.location.assign('/auth/sign-up')}><UserRound size={15}/>Create free account</DropdownMenuItem></>}</>;}

export function AccountWorkspace({children}:{children:ReactNode}){const path=usePathname();return path.startsWith('/auth/')?<>{children}</>:<BuddyProvider>{children}</BuddyProvider>;}
