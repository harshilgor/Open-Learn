'use client';
import { useEffect, useState } from 'react';
import { MEMORY_NOTICE_KEY, MEMORY_SETTINGS_OPEN_EVENT, type MemoryFact, turnMemories, undoMemory } from '@/lib/learner-memory';

/** Extraction runs after the reply finishes, so check back a few times. */
export const MEMORY_POLL_DELAYS_MS = [2500, 7000, 15000];

/**
 * "Saved to memory · View · Undo" under a turn that just completed in this tab.
 * Shows nothing when the turn saved nothing, so ordinary turns stay quiet.
 */
export function MemorySavedChip({ generationId, delays = MEMORY_POLL_DELAYS_MS }: { generationId: string; delays?: number[] }) {
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [state, setState] = useState<'idle' | 'undoing' | 'undone' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    const timers = delays.map(delay => window.setTimeout(() => {
      void turnMemories(generationId).then(items => { if (!cancelled && items.length) setFacts(items); }).catch(() => undefined);
    }, delay));
    return () => { cancelled = true; timers.forEach(timer => window.clearTimeout(timer)); };
  }, [generationId, delays]);

  if (!facts.length && state !== 'undone') return null;
  if (state === 'undone') return <p role="status" style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 0' }}>Removed from memory.</p>;
  const label = facts.length === 1 ? facts[0].statement : `${facts.length} things about you`;
  async function undo() {
    setState('undoing');
    try {
      for (const fact of facts) await undoMemory(fact.id);
      setFacts([]); setState('undone');
    } catch {
      setState('error');
    }
  }
  return <div role="status" aria-label="Saved to memory" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 12, opacity: 0.85, margin: '4px 0 0' }}>
    <span>Saved to memory: {label}</span>
    <button type="button" onClick={() => window.dispatchEvent(new CustomEvent(MEMORY_SETTINGS_OPEN_EVENT))}>View</button>
    <button type="button" disabled={state === 'undoing'} onClick={() => void undo()}>Undo</button>
    {state === 'error' ? <span role="alert">Could not undo. Try again in Settings.</span> : null}
  </div>;
}

/** One-time notice that Open Learn now learns from chats, with a way to review or pause. */
export function MemoryFirstRunNotice({ load }: { load: () => Promise<{ learningEnabled: boolean; extraction: 'on' | 'off' }> }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let cancelled = false;
    try { if (localStorage.getItem(MEMORY_NOTICE_KEY)) return; } catch { return; }
    void load().then(settings => { if (!cancelled && settings.extraction === 'on' && settings.learningEnabled) setVisible(true); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [load]);
  if (!visible) return null;
  function dismiss() {
    try { localStorage.setItem(MEMORY_NOTICE_KEY, String(Date.now())); } catch { /* Shown again next visit. */ }
    setVisible(false);
  }
  return <aside aria-label="Memory notice" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border, #ddd)', margin: '0 0 8px' }}>
    <span>Open Learn now remembers useful things you tell it, like deadlines, goals and preferences, so you don&rsquo;t have to repeat them. Only your own words are used.</span>
    <button type="button" onClick={() => { dismiss(); window.dispatchEvent(new CustomEvent(MEMORY_SETTINGS_OPEN_EVENT)); }}>Review or pause</button>
    <button type="button" onClick={dismiss}>Got it</button>
  </aside>;
}
