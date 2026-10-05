'use client';
import { useState, type FormEvent } from 'react';
import { supabaseAccount } from '@/lib/supabase-account';

export default function SignInPage() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      const client = supabaseAccount();
      if (!client) throw new Error('Account sign-in is not configured yet.');
      const { error } = await client.auth.signInWithOtp({ email: email.trim(),
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` } });
      if (error) throw error;
      setMessage('Check your email for a sign-in link. Open it in this browser to continue.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not send the sign-in link.');
    } finally { setBusy(false); }
  }
  return <main style={{ maxWidth: 480, margin: '80px auto', padding: 24 }}>
    <h1>Sign in to Open Learn</h1>
    <p>Use your email to access your learning across devices.</p>
    <form onSubmit={event => void submit(event)} style={{ display: 'grid', gap: 16 }}>
      <label>Email address<input type="email" autoComplete="email" required value={email}
        onChange={event => setEmail(event.target.value)} disabled={busy}
        style={{ display: 'block', width: '100%', padding: 12, marginTop: 8, border: '1px solid currentColor', borderRadius: 8 }} /></label>
      <button type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send sign-in link'}</button>
    </form>
    <p role="status">{message}</p>
    <a href="/">Return to Open Learn</a>
  </main>;
}
