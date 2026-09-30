"use client";

import { useEffect, useState } from 'react';
import { KeyRound, PlugZap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { learningApi, friendlyServiceError, type ProviderSettingsStatus } from '@/lib/api';

type DesktopCredentials = {
  has: (key: string) => Promise<boolean>;
  get: (key: string) => Promise<string | null>;
  set: (key: string, value: string) => Promise<boolean>;
  delete: (key: string) => Promise<boolean>;
};

function desktopCredentials(): DesktopCredentials | null {
  if (typeof window === 'undefined') return null;
  return (window as Window & { formaDesktop?: { credentials?: DesktopCredentials } }).formaDesktop?.credentials || null;
}

export function ProviderSettings() {
  const [credentials] = useState<DesktopCredentials | null>(() => desktopCredentials());
  const [openRouterKey, setOpenRouterKey] = useState('');
  const [openAiKey, setOpenAiKey] = useState('');
  const [configured, setConfigured] = useState({ openRouter: false, openAi: false });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [restartRequired, setRestartRequired] = useState(false);

  useEffect(() => {
    if (!credentials) return;
    void Promise.all([credentials.has('OPENROUTER_API_KEY'), credentials.has('OPENAI_API_KEY')]).then(([openRouter, openAi]) => {
      setConfigured({ openRouter: Boolean(openRouter), openAi: Boolean(openAi) });
    });
  }, [credentials]);

  async function save() {
    if (!credentials) return;
    setBusy(true); setMessage('');
    try {
      if (openRouterKey.trim()) await credentials.set('OPENROUTER_API_KEY', openRouterKey.trim());
      if (openAiKey.trim()) await credentials.set('OPENAI_API_KEY', openAiKey.trim());
      setConfigured(current => ({ openRouter: current.openRouter || Boolean(openRouterKey.trim()), openAi: current.openAi || Boolean(openAiKey.trim()) }));
      setRestartRequired(true);
      setOpenRouterKey(''); setOpenAiKey('');
      setMessage('Provider keys saved securely. Restart Forma to use a newly saved key.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Provider keys could not be saved.'); }
    finally { setBusy(false); }
  }

  async function remove(key: 'OPENROUTER_API_KEY' | 'OPENAI_API_KEY', label: 'openRouter' | 'openAi') {
    if (!credentials) return;
    setBusy(true); setMessage('');
    try { await credentials.delete(key); setConfigured(current => ({ ...current, [label]: false })); setRestartRequired(true); setMessage('Provider key removed. Restart Forma to apply the change.'); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Provider key could not be removed.'); }
    finally { setBusy(false); }
  }

  async function testConnection() {
    setTesting(true); setMessage('');
    try { const result = await learningApi.testProviderConnection(); setMessage(`Connected to ${result.provider} · ${result.model}.`); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'The provider connection test failed.'); }
    finally { setTesting(false); }
  }

  if (!credentials) return <ServerProviderSettings />;

  return <div className="provider-settings">
    <div className="settings-section-title"><KeyRound size={16} /><strong>Model providers</strong></div>
    <p className="settings-help">Keys are encrypted with this device’s operating-system credential store and passed to the local tutor service. Leave a field empty to keep its current value.</p>
    <p className="settings-help">Class recordings can be transcribed with the selected OpenRouter or OpenAI provider. OpenRouter transcription needs access to a speech model and available credits.</p>
    <p className="settings-help">Test connection sends one short request to the configured provider; normal provider billing may apply.</p>
    <label>OpenRouter API key<input type="password" autoComplete="off" value={openRouterKey} onChange={event => setOpenRouterKey(event.target.value)} placeholder={configured.openRouter ? 'Key saved securely' : 'sk-or-v1-…'} /></label>
    <label>OpenAI API key<input type="password" autoComplete="off" value={openAiKey} onChange={event => setOpenAiKey(event.target.value)} placeholder={configured.openAi ? 'Key saved securely' : 'sk-…'} /></label>
    <div className="settings-provider-status" role="status">{configured.openRouter || configured.openAi ? `Saved credentials · ${[configured.openRouter ? 'OpenRouter' : '', configured.openAi ? 'OpenAI' : ''].filter(Boolean).join(' and ')}` : 'No provider credentials saved'}{restartRequired ? ' · restart required' : ''}</div>
    <div className="settings-actions"><Button disabled={busy || (!openRouterKey.trim() && !openAiKey.trim())} onClick={save}>Save provider keys</Button><Button variant="outline" disabled={testing || restartRequired || (!configured.openRouter && !configured.openAi)} onClick={() => void testConnection()}><PlugZap size={15} />{testing ? 'Testing…' : 'Test connection'}</Button>{configured.openRouter ? <Button variant="ghost" disabled={busy} onClick={() => remove('OPENROUTER_API_KEY', 'openRouter')}>Remove OpenRouter</Button> : null}{configured.openAi ? <Button variant="ghost" disabled={busy} onClick={() => remove('OPENAI_API_KEY', 'openAi')}>Remove OpenAI</Button> : null}</div>
    {message ? <p className="settings-message" role="status">{message}</p> : null}
  </div>;
}

/**
 * Browser development shell: keys are stored in the local API server's own
 * configuration file. The desktop application keeps using the OS credential
 * store above. New browser requests use the saved provider immediately.
 */
function ServerProviderSettings() {
  const [status, setStatus] = useState<ProviderSettingsStatus | null>(null);
  const [openRouterKey, setOpenRouterKey] = useState('');
  const [openAiKey, setOpenAiKey] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void learningApi.getProviderSettings().then(next => {
        setStatus(next);
        if (next.restartRequired) setMessage('Restart the local tutor service to apply the saved provider.');
      }).catch((cause: unknown) => {
        const friendly = friendlyServiceError(cause, 'Provider status');
        setMessage(`${friendly.message} ${friendly.detail}`);
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function save() {
    setBusy(true); setMessage('');
    try {
      let next: ProviderSettingsStatus | null = null;
      if (openRouterKey.trim()) next = await learningApi.saveProviderKey('openrouter', openRouterKey.trim());
      if (openAiKey.trim()) next = await learningApi.saveProviderKey('openai', openAiKey.trim());
      if (next) setStatus(next);
      setOpenRouterKey(''); setOpenAiKey('');
      setMessage(next?.restartRequired ? 'Provider key saved. Restart the local tutor service to use it.' : 'Provider key saved. New responses will use this provider.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Provider key could not be saved.'); }
    finally { setBusy(false); }
  }

  async function remove(provider: 'openrouter' | 'openai') {
    setBusy(true); setMessage('');
    try {
      const next = await learningApi.deleteProviderKey(provider);
      setStatus(next);
      setMessage(next.restartRequired ? 'Provider key removed. Restart the local tutor service to apply the change.' : 'Provider key removed. New responses will use the selected provider.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Provider key could not be removed.'); }
    finally { setBusy(false); }
  }

  async function testConnection() {
    setTesting(true); setMessage('');
    try { const result = await learningApi.testProviderConnection(); setMessage(`Connected to ${result.provider} · ${result.model}.`); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'The provider connection test failed.'); }
    finally { setTesting(false); }
  }

  return <div className="provider-settings">
    <div className="settings-section-title"><KeyRound size={16} /><strong>Model providers</strong></div>
    <p className="settings-help">Browser mode saves provider keys in the local tutor service configuration file and sends requests only to the selected model provider. Never paste a key into a shared or untrusted server.</p>
    <p className="settings-help">Class recordings can be transcribed with the selected OpenRouter or OpenAI provider. OpenRouter transcription needs access to a speech model and available credits.</p>
    <p className="settings-help">Test connection sends one short request to the configured provider; normal provider billing may apply.</p>
    <div className="settings-provider-status" role="status">Active provider: {status?.provider || 'Loading…'}{status?.restartRequired ? ' · restart required' : ''}</div>
    <label>OpenRouter API key<input type="password" autoComplete="off" value={openRouterKey} onChange={event => setOpenRouterKey(event.target.value)} placeholder={status?.openRouterConfigured ? 'Key saved' : 'sk-or-v1-…'} /></label>
    <label>OpenAI API key<input type="password" autoComplete="off" value={openAiKey} onChange={event => setOpenAiKey(event.target.value)} placeholder={status?.openAiConfigured ? 'Key saved' : 'sk-…'} /></label>
    <div className="settings-actions"><Button disabled={busy || (!openRouterKey.trim() && !openAiKey.trim())} onClick={save}>Save provider keys</Button><Button variant="outline" disabled={testing || !status || status.restartRequired || status.provider === 'deterministic_baseline'} onClick={() => void testConnection()}><PlugZap size={15} />{testing ? 'Testing…' : 'Test connection'}</Button>{status?.openRouterConfigured ? <Button variant="ghost" disabled={busy} onClick={() => remove('openrouter')}>Remove OpenRouter</Button> : null}{status?.openAiConfigured ? <Button variant="ghost" disabled={busy} onClick={() => remove('openai')}>Remove OpenAI</Button> : null}</div>
    {message ? <p className="settings-message" role="status">{message}</p> : null}
  </div>;
}
