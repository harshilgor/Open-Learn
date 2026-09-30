"use client";

import { useEffect, useState } from 'react';
import { BookmarkPlus, Clipboard, CircleHelp, RotateCcw, ThumbsDown, ThumbsUp, X } from 'lucide-react';
import { learningApi } from '@/lib/api';
import { toast } from 'sonner';
import { addMessageToReview } from '@/lib/message-review';
import styles from './message-action-bar.module.css';

export type MessageVerification = { status: 'verified' | 'partial' | 'unverified'; agents: number; sources: { title: string; url: string }[] };

export function VerificationBadge({ verification }: { verification?: MessageVerification | null }) {
  if (!verification) return null;
  const sources = verification.sources.filter(source => /^https?:\/\//i.test(source.url));
  const count = sources.length;
  return <details className={styles.verification}><summary>{verification.status === 'verified' ? 'Verified' : verification.status === 'partial' ? 'Partially verified' : 'Unverified'} · {count} {count === 1 ? 'source' : 'sources'}</summary><div><p>{verification.agents} {verification.agents === 1 ? 'agent' : 'agents'} checked this response.</p>{sources.map((source, index) => <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>)}</div></details>;
}

export function MessageActionBar({ messageId, markdown, title, isLatest, onLost }: { messageId: string; markdown: string; title: string; isLatest: boolean; onLost: () => void }) {
  const [notice, setNotice] = useState('');
  const [saved, setSaved] = useState<{ id: string; revision: number } | null>(null);
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);
  useEffect(() => { const timer = window.setTimeout(() => { try { const value = localStorage.getItem(`forma-message-feedback:${messageId}`); setFeedback(value === 'up' || value === 'down' ? value : null); } catch { setFeedback(null); } }, 0); return () => window.clearTimeout(timer); }, [messageId]);
  async function undoNote(note: { id: string; revision: number }) {
    try { await learningApi.deleteWorkspaceNote(note.id, note.revision); setSaved(null); setNotice('Save undone.'); } catch { setNotice('Could not undo the save. Open Notes to remove it.'); }
  }
  async function save() {
    try {
      const source = `${window.location.origin}${window.location.pathname}#message-${encodeURIComponent(messageId)}`;
      const note = await learningApi.createWorkspaceNote({ title: title.slice(0, 100) || 'Tutor response', body: `${markdown.trim()}\n\n[Source chat message](${source})\n`, frontmatter: { source_chat: window.location.pathname, source_message_id: messageId } });
      const savedNote = { id: note.id, revision: note.revision };
      setSaved(savedNote); setNotice('Saved to Notes.');
      toast.success('Saved to Notes', { action: { label: 'Undo', onClick: () => void undoNote(savedNote) } });
    } catch { setNotice('Could not save this message to Notes.'); }
  }
  async function undo() {
    if (!saved) return;
    await undoNote(saved);
  }
  function rate(value: 'up' | 'down') {
    const next = feedback === value ? null : value;
    setFeedback(next);
    try { if (next) localStorage.setItem(`forma-message-feedback:${messageId}`, next); else localStorage.removeItem(`forma-message-feedback:${messageId}`); } catch { /* Local feedback is optional. */ }
    setNotice(next ? 'Feedback saved on this device.' : 'Feedback removed.');
  }
  return <div className={`${styles.wrap} ${isLatest ? styles.latest : ''}`}>
    <div className={styles.bar} aria-label="Tutor message actions">
      <button type="button" title="Copy response" aria-label="Copy response" onClick={() => void navigator.clipboard.writeText(markdown).then(() => setNotice('Copied response.')).catch(() => setNotice('Copy is unavailable.'))}><Clipboard size={15}/></button>
      <button type="button" title="Save to Notes" aria-label="Save to Notes" disabled={Boolean(saved)} onClick={() => void save()}><BookmarkPlus size={15}/></button>
      <button type="button" title="Add to Review" aria-label="Add to Review" onClick={() => void addMessageToReview(messageId).then(() => setNotice('Review cards cannot be created directly from a message yet.'))}><RotateCcw size={15}/></button>
      <button type="button" title="I'm lost" aria-label="I'm lost" onClick={onLost}><CircleHelp size={15}/></button>
      <button type="button" title="Helpful" aria-label="Helpful" aria-pressed={feedback === 'up'} onClick={() => rate('up')}><ThumbsUp size={15}/></button>
      <button type="button" title="Not helpful" aria-label="Not helpful" aria-pressed={feedback === 'down'} onClick={() => rate('down')}><ThumbsDown size={15}/></button>
    </div>
    {notice ? <div className={styles.notice} role="status"><span>{notice}</span>{saved && notice === 'Saved to Notes.' ? <button type="button" onClick={() => void undo()}>Undo</button> : null}<button type="button" aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={13}/></button></div> : null}
  </div>;
}
