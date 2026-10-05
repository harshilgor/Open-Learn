import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let client: SupabaseClient | undefined;

export function supabaseAccount(): SupabaseClient | undefined {
  if (typeof window === 'undefined') return undefined;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) return undefined;
  if (!client) {
    client = createClient(url, key, { auth: {
      flowType: 'pkce', detectSessionInUrl: false,
      persistSession: true, autoRefreshToken: true,
    } });
    let accountId: string | undefined;
    client.auth.onAuthStateChange((event, session) => {
      const nextId = session?.user.id;
      const changed = nextId !== accountId;
      accountId = nextId;
      if (event !== 'INITIAL_SESSION' && changed) window.setTimeout(() => {
        window.dispatchEvent(new Event('openlearn-account-changed'));
      }, 0);
    });
  }
  return client;
}

export const supabaseManager = {
  async getUser() {
    const { data, error } = await supabaseAccount()!.auth.getSession();
    if (error) throw error;
    const session = data.session;
    return session ? { access_token: session.access_token,
      expired: (session.expires_at ?? 0) <= Date.now() / 1000 } : undefined;
  },
  async signinRedirect() { window.location.assign('/auth/sign-in'); },
  async signinRedirectCallback() {
    const code = new URL(window.location.href).searchParams.get('code');
    if (!code) throw new Error('The sign-in link is missing its code. Request a new link.');
    const { error } = await supabaseAccount()!.auth.exchangeCodeForSession(code);
    if (error) throw error;
  },
  async removeUser() {
    const { error } = await supabaseAccount()!.auth.signOut({ scope: 'local' });
    if (error) throw error;
  },
};
