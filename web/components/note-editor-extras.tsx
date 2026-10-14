"use client";

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { CheckSquare2, FileText, Heading2, Heading3, ImagePlus, List, ListChecks, ListOrdered, Mic, Minus, Quote, Shapes, Sparkles } from 'lucide-react';
import { learningApi, type WorkspaceNoteSummary } from '@/lib/api';
import { NOTE_TEMPLATES, relativeTime, type NoteTemplate, type SlashCommand, type SlashCommandId } from '@/lib/note-editing';
import { noteDisplayTitle } from '@/lib/note-list';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './ui/dialog';
import styles from './note-editor-extras.module.css';

const SLASH_ICONS: Record<SlashCommandId, typeof Heading2> = {
  heading: Heading2, subheading: Heading3, bullet: List, numbered: ListOrdered, checklist: CheckSquare2,
  quote: Quote, divider: Minus, image: ImagePlus, visual: Shapes, quiz: ListChecks,
};

/** The "/" command list, anchored to the caret inside the note body. */
export function SlashMenu({ commands, index, x, y, onPick, onHover }: { commands: SlashCommand[]; index: number; x: number; y: number; onPick: (id: SlashCommandId) => void; onHover: (index: number) => void }) {
  if (!commands.length) return <div className={styles.slashMenu} style={{ left: x, top: y }} role="status"><p className={styles.slashEmpty}>No matching blocks</p></div>;
  return <div className={styles.slashMenu} style={{ left: x, top: y }} role="listbox" aria-label="Insert block" onMouseDown={event => event.preventDefault()}>
    {commands.map((command, position) => {
      const Icon = SLASH_ICONS[command.id];
      return <button key={command.id} type="button" role="option" aria-selected={position === index} id={`slash-${command.id}`} onMouseEnter={() => onHover(position)} onClick={() => onPick(command.id)}>
        <span className={styles.slashIcon} aria-hidden="true"><Icon size={15}/></span>
        <span><strong>{command.label}</strong><small>{command.hint}</small></span>
      </button>;
    })}
  </div>;
}

/** Shown under an empty new note: one click turns it into a structured page. */
export function NoteTemplatePicker({ onPick, onRecord, onUpload }: { onPick: (template: NoteTemplate) => void; onRecord?: () => void; onUpload?: () => void }) {
  return <div className={styles.templates} aria-label="Start from a template">
    <span>Start with</span>
    {NOTE_TEMPLATES.map(template => <button key={template.id} type="button" title={template.description} onClick={() => onPick(template)}>{template.label}</button>)}
    {onRecord ? <button type="button" className={styles.recordStart} title="Record audio; notes are written into this note when you stop" onClick={onRecord}><Mic size={13} aria-hidden="true"/>Record a lecture</button> : null}
    {onUpload ? <button type="button" title="Turn an audio file (M4A, MP3, WAV, WebM) into notes" onClick={onUpload}>Upload a recording</button> : null}
    <small>or type <kbd>/</kbd> for blocks</small>
  </div>;
}

function noteIcon(note: WorkspaceNoteSummary): ReactNode {
  return note.noteType === 'lesson' ? <Sparkles size={15}/> : note.noteType === 'recording' ? <Mic size={15}/> : <FileText size={15}/>;
}

/** Ctrl/⌘+P: jump to any note by title. Searches loaded notes instantly and the server as you type. */
export function NoteQuickSwitcher({ open, onOpenChange, notes, courseNames, onOpen }: { open: boolean; onOpenChange: (open: boolean) => void; notes: WorkspaceNoteSummary[]; courseNames: Record<string, string>; onOpen: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [remote, setRemote] = useState<WorkspaceNoteSummary[]>([]);
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (!open || query.trim().length < 2) return;
    let live = true;
    const timer = window.setTimeout(() => void learningApi.searchWorkspaceNotes(query).then(result => { if (live) setRemote(result.notes); }).catch(() => undefined), 160);
    return () => { live = false; window.clearTimeout(timer); };
  }, [open, query]);
  const results = useMemo(() => {
    const value = query.trim().toLowerCase();
    const local = value ? notes.filter(note => note.title.toLowerCase().includes(value)) : notes;
    const seen = new Set(local.map(note => note.id));
    return [...local, ...(value.length >= 2 ? remote.filter(note => !seen.has(note.id)) : [])].slice(0, 12);
  }, [notes, query, remote]);
  const choose = (note: WorkspaceNoteSummary | undefined) => { if (!note) return; onOpenChange(false); setQuery(''); onOpen(note.id); };
  return <Dialog open={open} onOpenChange={value => { onOpenChange(value); if (!value) { setQuery(''); setIndex(0); } }}>
    <DialogContent className={styles.switcher} showCloseButton={false}>
      <DialogHeader className="sr-only"><DialogTitle>Go to note</DialogTitle><DialogDescription>Type to find a note, then press Enter to open it.</DialogDescription></DialogHeader>
      <input autoFocus className={styles.switcherInput} placeholder="Go to note…" aria-label="Find a note" role="combobox" aria-expanded="true" aria-controls="note-switcher-results" aria-activedescendant={results[index] ? `note-switch-${results[index].id}` : undefined} value={query}
        onChange={event => { setQuery(event.target.value); setIndex(0); }}
        onKeyDown={event => {
          if (event.key === 'ArrowDown') { event.preventDefault(); setIndex(value => Math.min(results.length - 1, value + 1)); }
          else if (event.key === 'ArrowUp') { event.preventDefault(); setIndex(value => Math.max(0, value - 1)); }
          else if (event.key === 'Enter') { event.preventDefault(); choose(results[index]); }
        }}/>
      <div id="note-switcher-results" role="listbox" aria-label="Notes" className={styles.switcherList}>
        {results.length ? results.map((note, position) => <button key={note.id} id={`note-switch-${note.id}`} type="button" role="option" aria-selected={position === index} onMouseEnter={() => setIndex(position)} onClick={() => choose(note)}>
          <span className={styles.switcherIcon} aria-hidden="true">{noteIcon(note)}</span>
          <strong>{noteDisplayTitle(note, notes)}</strong>
          <small>{typeof note.frontmatter.course_id === 'string' && courseNames[note.frontmatter.course_id] ? `${courseNames[note.frontmatter.course_id]} · ` : ''}{relativeTime(note.updatedAt)}</small>
        </button>) : <p className={styles.slashEmpty}>No notes match “{query}”.</p>}
      </div>
      <p className={styles.switcherFoot}><kbd>↑</kbd><kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Esc</kbd> to close</p>
    </DialogContent>
  </Dialog>;
}

export type NoteConnection = { id: string; label: string; detail?: string; icon: ReactNode; onSelect: () => void };

/** Where this note came from and what it connects to, plus ways to study it. */
export function NoteConnections({ actions, links, related }: { actions: ReactNode; links: NoteConnection[]; related: NoteConnection[] }) {
  return <section className={styles.connections} aria-label="Study and connections">
    <div className={styles.connectionsBlock}>
      <h3>Study this note</h3>
      <div className={styles.studyActions}>{actions}</div>
    </div>
    {links.length ? <div className={styles.connectionsBlock}>
      <h3>Connected</h3>
      <ul>{links.map(link => <li key={link.id}><button type="button" onClick={link.onSelect}><span aria-hidden="true">{link.icon}</span><strong>{link.label}</strong>{link.detail ? <small>{link.detail}</small> : null}</button></li>)}</ul>
    </div> : null}
    {related.length ? <div className={styles.connectionsBlock}>
      <h3>Related notes</h3>
      <ul>{related.map(link => <li key={link.id}><button type="button" onClick={link.onSelect}><span aria-hidden="true">{link.icon}</span><strong>{link.label}</strong>{link.detail ? <small>{link.detail}</small> : null}</button></li>)}</ul>
    </div> : null}
  </section>;
}
