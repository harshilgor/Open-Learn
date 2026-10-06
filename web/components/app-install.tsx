"use client";

import { useEffect, useState } from 'react';
import { Download, Sparkles } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog';
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
  return <Dialog open={open} onOpenChange={value => { setOpen(value); if (!value) remember(); }}>
    <DialogContent>
      <Sparkles size={32} aria-hidden="true" />
      <DialogTitle>Make room for a little learning.</DialogTitle>
      <DialogDescription>Install Open Learn on your phone or desktop. Keep your courses, notes, and Buddy chat a tap away.</DialogDescription>
      {available ? <Button disabled={busy} onClick={() => void install()}><Download size={16} />{busy ? 'Opening installer…' : 'Install Open Learn'}</Button> : <div className="rounded-lg bg-muted p-4 text-sm leading-relaxed">
        {ios ? 'On iPhone or iPad, open this page in Safari, tap Share, then Add to Home Screen and Add.' : 'Open your browser menu and look for “Install Open Learn”, “Install app”, or “Add to Home screen”. On Mac Safari, use File → Add to Dock. If no install option appears, continue in your browser.'}
      </div>}
      {error ? <p role="alert" className="text-sm">{error}</p> : null}
      <Button variant="ghost" onClick={() => { remember(); setOpen(false); }}>Continue in browser</Button>
      <p className="text-xs text-muted-foreground">You can also install later from your browser menu.</p>
    </DialogContent>
  </Dialog>;
}
