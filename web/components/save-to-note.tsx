"use client";

import { useEffect, useRef, useState } from 'react';
import { learningApi, type WorkspaceNoteSummary } from '@/lib/api';
import { openWorkspaceNote } from '@/lib/workspace-events';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { Button } from './ui/button';
import { RichContent } from './rich-content';

/** Writes only after an explicit preview approval; existing notes use revision checks. */
export function SaveToNote({ body, title, sessionId, messageId, label = 'Save to note' }: {
  body: string; title: string; sessionId?: string | null; messageId?: string; label?: string;
}) {
  const [open, setOpen] = useState(false), [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [target, setTarget] = useState(''), [name, setName] = useState(title), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const epoch = useRef(0);
  const saving = useRef(false);
  useEffect(() => { if (!open) return; let live = true;
    void learningApi.listWorkspaceNotes().then(value => { if (live) setNotes(value); }).catch(cause => { if (live) setError(cause instanceof Error ? cause.message : 'Notes unavailable.'); });
    return () => { live = false; };
  }, [open]);
  useEffect(() => { const clear = () => { epoch.current++; setOpen(false); setNotes([]); setTarget(''); setError(''); }; window.addEventListener(ACCOUNT_CHANGED, clear); return () => { epoch.current++; window.removeEventListener(ACCOUNT_CHANGED, clear); }; }, []);
  const origin = sessionId ? `/s/${encodeURIComponent(sessionId)}${messageId ? `#${encodeURIComponent(messageId)}` : ''}` : '';
  const addition = `${body.trim()}${origin ? `\n\n[Original explanation](${origin})` : ''}`;
  async function save() {
    if (saving.current) return; saving.current = true; const generation = epoch.current; setBusy(true); setError('');
    try {
      const current = target ? await learningApi.getWorkspaceNote(target) : null;
      if (generation !== epoch.current) return;
      const saved = current ? await learningApi.updateWorkspaceNote(current.id, {
        title: current.title, body: `${current.body}\n\n---\n\n${addition}`, frontmatter: current.frontmatter, expectedRevision: current.revision,
      }) : await learningApi.createWorkspaceNote({ title: name.trim() || 'Study note', body: addition, frontmatter: { source: 'conversation_capture', ...(sessionId ? { session_ids: [sessionId] } : {}) } });
      if (generation === epoch.current) { setOpen(false); openWorkspaceNote(saved.id); }
    } catch (cause) { if (generation === epoch.current) setError(cause instanceof Error ? cause.message : 'Could not save. Your preview is still available.'); }
    finally { saving.current = false; setBusy(false); }
  }
  return <div className="study-capture"><Button size="sm" variant="outline" disabled={!body.trim()} onClick={() => { setOpen(value => !value); setError(''); }}>{label}</Button>
    {open ? <section aria-label="Preview note addition" className="study-capture-preview">
      <h3>Preview before saving</h3><label>Destination<select value={target} onChange={event => setTarget(event.target.value)} disabled={busy}><option value="">New note</option>{notes.map(note => <option key={note.id} value={note.id}>{note.title}</option>)}</select></label>
      {!target ? <label>Note title<input value={name} onChange={event => setName(event.target.value)} disabled={busy}/></label> : <p>This passage will be appended; your existing writing stays intact.</p>}
      <div className="study-capture-body"><RichContent body={addition}/></div>
      {error ? <p role="alert">{error}</p> : null}<Button size="sm" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Confirm addition'}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button>
    </section> : null}
  </div>;
}
