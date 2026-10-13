"use client";

import { useEffect, useState } from 'react';
import { Download, Sparkles, X } from 'lucide-react';
import { Button } from './ui/button';
import styles from './app-install.module.css';

interface InstallEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const seenKey = 'openlearn-install-invitation-v1';

function remember() {
  try {
    localStorage.setItem(seenKey, 'seen');
  } catch {
    // Storage may be unavailable.
  }
}

export function AppInstall() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<InstallEvent | null>(null);
  const [ios, setIos] = useState(false);
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const installed = window.matchMedia('(display-mode: standalone)').matches ||
      (navigator as Navigator & { standalone?: boolean }).standalone;
    if (installed || 'formaDesktop' in window) return;

    const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    let seen = false;
    try {
      seen = !!localStorage.getItem(seenKey);
    } catch {
      // Show once for this visit when storage is unavailable.
    }

    const timer = window.setTimeout(() => {
      setIos(isIos);
      if (!seen) setOpen(true);
    }, 1500);
    const capture = (event: Event) => {
      event.preventDefault();
      setAvailable(event as InstallEvent);
    };
    const finish = () => {
      remember();
      setOpen(false);
      setAvailable(null);
    };
    const reopen = () => {
      setIos(isIos);
      setInstructionsOpen(false);
      setError('');
      setOpen(true);
    };

    window.addEventListener('beforeinstallprompt', capture);
    window.addEventListener('appinstalled', finish);
    window.addEventListener('openlearn:install', reopen);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('beforeinstallprompt', capture);
      window.removeEventListener('appinstalled', finish);
      window.removeEventListener('openlearn:install', reopen);
    };
  }, []);

  function dismiss() {
    remember();
    setOpen(false);
  }

  async function install() {
    if (!available || busy) return;
    setBusy(true);
    setError('');
    try {
      await available.prompt();
      const choice = await available.userChoice;
      setAvailable(null);
      if (choice.outcome === 'accepted') {
        remember();
        setOpen(false);
      }
    } catch {
      setAvailable(null);
      setError('The install prompt could not open. Try your browser menu instead.');
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <aside
      className={styles.toast}
      role="status"
      aria-label="Install Open Learn"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className={styles.header}>
        <span className={styles.icon} aria-hidden="true"><Sparkles size={17} /></span>
        <p className={styles.title}>Take Open Learn with you</p>
        <button className={styles.close} type="button" onClick={dismiss} aria-label="Dismiss install message">
          <X size={17} />
        </button>
      </div>

      <p className={styles.description}>
        {available
          ? 'Install for a quicker way back to your chats and notes.'
          : 'Add Open Learn to your home screen for a quicker way back.'}
      </p>

      {error ? <p className={styles.error} role="alert">{error}</p> : null}

      {instructionsOpen ? (
        <p className={styles.instructions}>
          {ios
            ? 'In Safari, tap Share, then Add to Home Screen.'
            : 'Open your browser menu and choose “Install Open Learn” or “Add to Home screen”.'}
        </p>
      ) : null}

      <div className={styles.actions}>
        {available ? (
          <Button className={styles.primary} disabled={busy} onClick={() => void install()}>
            <Download size={15} aria-hidden="true" />
            {busy ? 'Opening…' : 'Install app'}
          </Button>
        ) : (
          <Button
            className={styles.primary}
            aria-expanded={instructionsOpen}
            onClick={() => setInstructionsOpen(value => !value)}
          >
            {instructionsOpen ? 'Hide instructions' : 'How to install'}
          </Button>
        )}
        <Button variant="ghost" className={styles.dismiss} onClick={dismiss}>Not now</Button>
      </div>
    </aside>
  );
}
