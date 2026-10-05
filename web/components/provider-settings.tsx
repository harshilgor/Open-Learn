"use client";
import { useEffect, useState } from 'react';
import { Sparkles, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { learningApi, friendlyServiceError, type ProviderSettingsStatus } from '@/lib/api';

export function ProviderSettings() {
  const [status, setStatus] = useState<ProviderSettingsStatus | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(true);
  async function refresh() {
    setBusy(true); setMessage('');
    try { setStatus(await learningApi.getProviderSettings()); }
    catch (cause) { const friendly = friendlyServiceError(cause, 'AI service'); setMessage(`${friendly.message} ${friendly.detail}`); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    void learningApi.getProviderSettings().then(value => { if (active) setStatus(value); }).catch(cause => {
      if (active) { const friendly = friendlyServiceError(cause, 'AI service'); setMessage(`${friendly.message} ${friendly.detail}`); }
    }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  return <section className="provider-settings" aria-label="Included AI service">
    <div className="settings-section-title"><Sparkles size={16} /><strong>AI service</strong></div>
    <p className="settings-help">Open Learn provides AI access for your conversations, study notes and practice. You do not need an API key or a separate provider account.</p>
    <p className="settings-help">The same service supports the web, mobile and desktop apps. Usage follows your Open Learn account.</p>
    <p className="settings-provider-status" role="status">{busy ? 'Checking service…' : status?.available ? 'AI service ready' : status ? 'AI service is temporarily unavailable. Please retry shortly.' : 'Service status unavailable'}</p>
    <Button variant="outline" disabled={busy} onClick={() => void refresh()}><RefreshCw size={15} />Check service status</Button>
    {message ? <p className="settings-message" role="status">{message}</p> : null}
  </section>;
}
