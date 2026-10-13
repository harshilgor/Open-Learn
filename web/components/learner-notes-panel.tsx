"use client";

import { useEffect, useMemo, useState } from 'react';
import { FileText, RefreshCw, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { learningApi, type LearnerNote } from '@/lib/api';

const LEARNER_ID = 'local';

function titleFor(note: LearnerNote): string {
  return note.body.match(/^#\s+(.+)$/m)?.[1]?.trim() || 'Untitled note';
}

function summaryFor(note: LearnerNote): string {
  return note.body.replace(/^#.*$/m, '').replace(/\n+/g, ' ').trim().slice(0, 110) || 'No content yet';
}

function dateFor(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Recently edited' : `Edited ${date.toLocaleDateString()}`;
}

export function LearnerNotesPanel({ refreshKey }: { refreshKey: number }) {
  const [notes, setNotes] = useState<LearnerNote[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  async function load() {
    setState('loading');
    try {
      setNotes(await learningApi.listLearnerNotes(LEARNER_ID));
      setState('ready');
    } catch {
      setState('error');
    }
  }

  useEffect(() => { void load(); }, [refreshKey]);
  useEffect(() => {
    if (!notes.some((note) => note.id === selectedId)) setSelectedId(notes[0]?.id ?? null);
  }, [notes, selectedId]);

  const filteredNotes = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return notes;
    return notes.filter((note) => `${titleFor(note)} ${note.body}`.toLocaleLowerCase().includes(normalized));
  }, [notes, query]);
  const selected = notes.find((note) => note.id === selectedId) ?? null;

  return <section className="notes-workspace" aria-label="Notes workspace">
    <aside className="notes-index">
      <header className="notes-index-header"><div><span className="eyebrow">YOUR SPACE</span><h1>Notes</h1></div><Button variant="ghost" size="icon" onClick={() => void load()} aria-label="Refresh notes"><RefreshCw size={16} /></Button></header>
      <label className="notes-search"><Search size={15} /><span className="sr-only">Search notes</span><input placeholder="Search notes" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="notes-index-status">{state === 'loading' ? 'Loading notes…' : `${filteredNotes.length} note${filteredNotes.length === 1 ? '' : 's'}`}</div>
      <div className="notes-list" role="list">{filteredNotes.map((note) => <button className={note.id === selectedId ? 'selected' : ''} key={note.id} onClick={() => setSelectedId(note.id)} role="listitem"><strong>{titleFor(note)}</strong><span>{summaryFor(note)}</span><small>{dateFor(note.updatedAt)}</small></button>)}</div>
    </aside>
    <main className="notes-canvas">
      {state === 'error' ? <div className="notes-empty"><FileText size={28} /><h2>Notes are unavailable</h2><p>Start the local learning API, then refresh this page.</p><Button variant="outline" onClick={() => void load()}>Retry</Button></div> : null}
      {state === 'ready' && !notes.length ? <div className="notes-empty"><FileText size={28} /><h2>Capture what matters</h2><p>Attach a text source in Learn, then ask the tutor to create source-backed notes here.</p></div> : null}
      {selected ? <article className="note-document"><header><div><span className="eyebrow">{selected.documentId ? 'SOURCE-BACKED NOTE' : 'LEARNER NOTE'}</span><h2>{titleFor(selected)}</h2></div><span>Revision {selected.revision}</span></header><div className="note-document-body">{selected.body}</div></article> : null}
    </main>
  </section>;
}
