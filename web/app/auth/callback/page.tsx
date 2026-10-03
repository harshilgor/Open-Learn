'use client';
import { useEffect, useState } from 'react';
import { accountManager } from '@/lib/account-session';

export default function AccountCallback() {
  const [message, setMessage] = useState('Completing sign-in…');
  useEffect(() => {
    const manager = accountManager();
    if (!manager) { setMessage('The account provider is not configured.'); return; }
    void manager.signinRedirectCallback().then(() => window.location.replace('/')).catch(() => setMessage('Sign-in could not be completed. Return to Settings and try again.'));
  }, []);
  return <main style={{ maxWidth: 720, margin: '80px auto', padding: 24 }}><h1>Open Learn account</h1><p role="status">{message}</p><a href="/">Return to Open Learn</a></main>;
}
