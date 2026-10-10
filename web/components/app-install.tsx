"use client";

import { useEffect, useState } from 'react';
import { Download, X } from 'lucide-react';
import { Button } from './ui/button';

interface InstallEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}
const seenKey = 'openlearn-install-invitation-v1';
function remember() { try { localStorage.setItem(seenKey, 'seen'); } catch { /* Storage may be unavailable. */ } }

export function AppInstall() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<InstallEvent | null>(null);
  const [ios, setIos] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const installed = window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone;
    if (installed || 'formaDesktop' in window) return;
    const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    let seen = false;
    try { seen = !!localStorage.getItem(seenKey); } catch { /* Show once for this visit. */ }
    const timer = window.setTimeout(() => { setIos(isIos); if (!seen) setOpen(true); }, 1500);
    const capture = (event: Event) => { event.preventDefault(); setAvailable(event as InstallEvent); };
    const finish = () => { remember(); setOpen(false); setAvailable(null); };
    const reopen = () => { setIos(isIos); setOpen(true); };
    window.addEventListener('beforeinstallprompt', capture);
    window.addEventListener('appinstalled', finish);
    window.addEventListener('openlearn:install', reopen);
    return () => { clearTimeout(timer); window.removeEventListener('beforeinstallprompt', capture); window.removeEventListener('appinstalled', finish); window.removeEventListener('openlearn:install', reopen); };
  }, []);
  async function install() {
    if (!available || busy) return;
    setBusy(true); setError('');
    try {
      await available.prompt();
      const choice = await available.userChoice;
      setAvailable(null);
      if (choice.outcome === 'accepted') { remember(); setOpen(false); }
    } catch { setAvailable(null); setError('The installation prompt could not open. Use your browser menu to install.'); }
    finally { setBusy(false); }
  }
  if (!open) return null;
  const dismiss = () => { remember(); setOpen(false); };
  return <aside aria-label="Install Open Learn" className="fixed bottom-4 left-4 z-50 w-[calc(100vw-2rem)] max-w-sm rounded-xl border border-border bg-background p-5 text-foreground shadow-lg">
    <button type="button" aria-label="Dismiss install invitation" onClick={dismiss} className="absolute right-2 top-2 rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"><X size={16} aria-hidden="true" /></button>
    <h2 className="pr-6 text-sm font-semibold">Install Open Learn</h2>
    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Open it straight from your home screen or desktop.</p>
    {!available ? <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{ios ? 'In Safari, tap Share → Add to Home Screen.' : 'Use your browser’s install button or menu. On Mac Safari: File → Add to Dock.'}</p> : null}
    {error ? <p role="alert" className="mt-3 text-sm">{error}</p> : null}
    <div className="mt-4 flex items-center gap-2">
      {available ? <Button size="sm" disabled={busy} onClick={() => void install()}><Download size={14} aria-hidden="true" />{busy ? 'Opening…' : 'Install'}</Button> : null}
      <Button size="sm" variant="ghost" onClick={dismiss}>Not now</Button>
    </div>
  </aside>;
}
