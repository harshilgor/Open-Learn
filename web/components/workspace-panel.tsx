"use client";
import { reportVoiceFocus } from "@/lib/voice/client";

import { memo, useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { createPortal } from 'react-dom';
import { Bold, BookOpen, CheckSquare2, Download, FileText, FolderClosed, FolderPlus, Heading2, Italic, Link2, List, ListOrdered, Mic, MoreHorizontal, PanelLeft, PanelLeftClose, PanelRightClose, Plus, Quote, Search, Send, Sparkles, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { readingRemarkPlugins, readingRehypePlugins } from '@/lib/markdown-rendering';
import { normalizeMathMarkdown } from '@/lib/normalize-math-markdown';
import 'katex/dist/katex.min.css';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from '@/components/ui/empty';
import { LearningApiError, friendlyServiceError, learningApi, request, type CourseSummary, type WorkspaceNote, type WorkspaceNoteSummary } from '@/lib/api';
import { QuizWorkspace, LessonPractice } from './quiz-workspace';
import type { WorkspaceQuizOpen } from '@/lib/workspace-events';
import styles from './workspace-panel.module.css';
import {FlashcardWorkspace} from './flashcard-workspace';
import {MakeFlashcards} from './flashcard-create';
import type {FlashcardView} from '@/lib/flashcards-client';
import {InClassWorkspace} from './in-class-workspace';
import { mentionWorkspaceNoteExcerpt, WORKSPACE_SOURCE_OPEN_EVENT, type WorkspaceNoteSeed } from '@/lib/workspace-events';
import { StudyNoteBar } from './study-note-bar';
import { NoteProposalList } from './study-note-panel';
import { NoteVisualReferences } from './visualization-reference';
import { richNoteToMarkdown } from '@/lib/rich-note-markdown';
import { deleteClassRecording, getClassRecording, saveClassRecording } from '@/lib/class-recordings';
import { LectureNotesView } from './lecture-notes-view';
import type { NotesCommand } from './workspace-sidebar';
import { noteDisplayTitle } from '@/lib/note-list';
import { CompactTutorChat, type TutorChatContext } from './compact-tutor-chat';

export type WorkspaceTab = 'notes' | 'quiz' | 'sources' | 'class' | 'flashcards';
export type WorkspacePanelLayout = { width: number; collapsed: boolean; tabs: WorkspaceTab[]; activeTab: WorkspaceTab };
type NoteDraft = (Pick<WorkspaceNote, 'id' | 'title' | 'body' | 'revision' | 'frontmatter'>) | { id: null; title: string; body: string; revision: null; frontmatter: Record<string, unknown> };

const tabNames: Record<WorkspaceTab, string> = { notes: 'Notes', quiz: 'Quiz', sources: 'Sources',class:'In-Class',flashcards:'Flashcards' };
const noteTools = [
  { format: 'heading', label: 'Heading', icon: Heading2 },
  { format: 'bold', label: 'Bold (Ctrl+B)', icon: Bold },
  { format: 'italic', label: 'Italic (Ctrl+I)', icon: Italic },
  { format: 'bullet', label: 'Bulleted list', icon: List },
  { format: 'numbered', label: 'Numbered list', icon: ListOrdered },
  { format: 'checklist', label: 'Checklist', icon: CheckSquare2 },
  { format: 'quote', label: 'Quote', icon: Quote },
  { format: 'link', label: 'Link', icon: Link2 },
] as const;

function toDraft(note: WorkspaceNote): NoteDraft {
  return { id: note.id, title: note.title, body: note.body, revision: note.revision, frontmatter: note.frontmatter };
}

function blankDraft(): NoteDraft {
  return { id: null, title: 'Untitled note', body: '', revision: null, frontmatter: {} };
}

const RichNoteBody = memo(function RichNoteBody({ initialBody, editorRef, onChange }: {
  initialBody: string;
  editorRef: React.RefObject<HTMLElement | null>;
  onChange: (body: string) => void;
}) {
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  return <article ref={editorRef} className={styles.notePreview} contentEditable suppressContentEditableWarning role="textbox" aria-label="Note body" aria-multiline="true" data-placeholder="Write your note…" spellCheck onInput={event => onChangeRef.current(richNoteToMarkdown(event.currentTarget))} onPaste={event => {
    event.preventDefault();
    document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
  }}>
    {initialBody.trim() ? <ReactMarkdown remarkPlugins={readingRemarkPlugins as never} rehypePlugins={readingRehypePlugins as never} skipHtml components={{
      a: ({ href, children }) => <a href={href} onClick={event => event.preventDefault()}>{children}</a>,
      img: ({ alt }) => <span>{alt || 'Image reference'}</span>,
    }}>{normalizeMathMarkdown(initialBody)}</ReactMarkdown> : <p><br /></p>}
  </article>;
}, () => true);

function RecordingPlayer({ recordingId, noteId, duration, markersMs = [], onReady }: { recordingId: string; noteId: string; duration?: number; markersMs?: number[]; onReady: () => void }) {
  const [url, setUrl] = useState<string | null>(null), [status, setStatus] = useState('queued'), [processingError, setProcessingError] = useState(''), [retrying, setRetrying] = useState(false);
  const readyNotified = useRef(false);
  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;
    void getClassRecording(recordingId).then(blob => blob || learningApi.getClassRecordingAudio(recordingId)).then(blob => {
      if (revoked || !blob) return;
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    }).catch(() => setUrl(null));
    return () => { revoked = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [recordingId]);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await learningApi.getClassRecording(noteId);
        if (cancelled) return;
        setStatus(result.status); setProcessingError(result.error || '');
        if ((result.status === 'completed' || result.status === 'failed') && !readyNotified.current) { readyNotified.current = true; onReady(); }
      } catch (cause) { if (!cancelled) { setStatus(cause instanceof LearningApiError && cause.status === 404 ? 'awaiting_upload' : 'unavailable'); if (!(cause instanceof LearningApiError && cause.status === 404)) setProcessingError(cause instanceof Error ? cause.message : 'Processing status unavailable.'); } }
    };
    void poll();
    const timer = window.setInterval(() => { if (status !== 'completed' && status !== 'failed') void poll(); }, 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [noteId, onReady, status]);
  async function retry() { setRetrying(true); setProcessingError(''); readyNotified.current = false; try { if (status === 'awaiting_upload') { const audio = await getClassRecording(recordingId); if (!audio) throw new Error('The saved audio is unavailable on this device.'); const result = await learningApi.uploadClassRecording(noteId, audio, duration || 0, markersMs); await saveClassRecording(result.id, audio); if (result.id !== recordingId) await deleteClassRecording(recordingId); setStatus(result.status); } else { const result = await learningApi.retryClassRecording(noteId); setStatus(result.status); } } catch (cause) { setProcessingError(cause instanceof Error ? cause.message : 'Could not retry processing.'); } finally { setRetrying(false); } }
  const statusLabel = status === 'completed' ? 'Transcript and study guide ready' : status === 'processing' ? 'Transcribing and creating study guide…' : status === 'queued' ? 'Waiting to process…' : status === 'failed' ? 'Processing needs attention' : status === 'awaiting_upload' ? 'Recording saved locally; upload pending' : 'Processing status unavailable';
  return <section className={styles.recordingPlayer}><div><Mic size={17} /><strong>Class recording</strong><small>{duration ? `${Math.ceil(duration / 60000)} min` : ''}</small></div>{url ? <audio controls preload="metadata" src={url} aria-label="Class recording" /> : <p>Recording unavailable on this device.</p>}<p>{statusLabel}</p>{processingError ? <p role="alert">{processingError}</p> : null}{status === 'failed' || status === 'awaiting_upload' ? <Button size="sm" variant="outline" disabled={retrying} onClick={() => void retry()}>{retrying ? 'Retrying…' : status === 'awaiting_upload' ? 'Upload recording' : 'Retry processing'}</Button> : null}</section>;
}

type SourceBlock = { id: string; versionId: string; pageIndex: number; kind: string; text: string };
type SourceMaterial = { id: string; title: string; versionId: string; status: string; role: string };

function SourcesPanel({ sourceToOpen }: { sourceToOpen?: { spanId: string; versionId?: string } | null }) {
  const [materials, setMaterials] = useState<SourceMaterial[]>([]), [blocks, setBlocks] = useState<SourceBlock[]>([]), [active, setActive] = useState<SourceBlock | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try { setMaterials((await request<{ materials: SourceMaterial[] }>('/v1/materials')).materials); } catch (cause) { const friendly = friendlyServiceError(cause, 'Sources'); setError(`${friendly.message} ${friendly.detail}`); } finally { setLoading(false); } }, []);
  const openVersion = useCallback(async (versionId: string, spanId?: string) => { try {
    if (versionId.startsWith('quiz-context:')) {
      const source = await request<{ spanId: string; versionId: string; pageIndex: number; text: string }>(`/v1/quizzes/${encodeURIComponent(versionId.slice('quiz-context:'.length))}/study-context`);
      const block = { id: source.spanId, versionId: source.versionId, pageIndex: 0, kind: 'study_context', text: source.text };
      setBlocks([block]); setActive(block); setError(''); return;
    }
    const result = await request<{ blocks: SourceBlock[] }>(`/v1/material-versions/${encodeURIComponent(versionId)}/blocks`); setBlocks(result.blocks); setActive(spanId ? result.blocks.find(block => block.id === spanId) || result.blocks[0] || null : result.blocks[0] || null); setError(''); } catch (cause) { setError(cause instanceof Error ? cause.message : 'This material passage could not be opened.'); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { const receive = (event: Event) => { const detail = (event as CustomEvent<{ spanId: string; versionId?: string }>).detail; if (!detail?.spanId) return; if (detail.versionId || detail.spanId.startsWith('quiz-context:')) { void openVersion(detail.versionId || detail.spanId, detail.spanId); return; } void request<SourceBlock>(`/v1/source-spans/${encodeURIComponent(detail.spanId)}`).then(block => openVersion(block.versionId, block.id)).catch(cause => setError(cause instanceof Error ? cause.message : 'This cited passage is no longer available.')); }; window.addEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive); return () => window.removeEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive); }, [openVersion]);
  useEffect(() => { if (!sourceToOpen?.spanId) return; const timer = window.setTimeout(() => { if (sourceToOpen.versionId || sourceToOpen.spanId.startsWith('quiz-context:')) void openVersion(sourceToOpen.versionId || sourceToOpen.spanId, sourceToOpen.spanId); else void request<SourceBlock>(`/v1/source-spans/${encodeURIComponent(sourceToOpen.spanId)}`).then(block => openVersion(block.versionId, block.id)).catch(cause => setError(cause instanceof Error ? cause.message : 'This cited passage is no longer available.')); }, 0); return () => window.clearTimeout(timer); }, [openVersion, sourceToOpen]);
  return <section className={styles.sourcesPanel} aria-label="Sources workspace"><header><div><span>YOUR MATERIALS</span><h2>Sources</h2></div><Button size="sm" variant="ghost" onClick={() => void load()}>Refresh</Button></header><p className={styles.sourceNotice}>Attached passages and clearly labeled study context can support a quiz. Coverage can be limited.</p><div className={styles.sourceLayout}><div className={styles.sourceList}>{loading ? <p>Loading sources…</p> : materials.length ? materials.map(material => <button type="button" key={material.versionId} onClick={() => void openVersion(material.versionId)}><strong>{material.title}</strong><small>{material.status.replaceAll('_', ' ')} · {material.role.replaceAll('_', ' ')}</small></button>) : <p>No uploaded sources yet. Attach a text-based file in chat to inspect its passages here.</p>}</div><div className={styles.sourceDetail}>{active ? <><p className={styles.sourceMeta}>{active.kind === 'study_context' ? 'Study context · Not independently verified' : `Passage · Page ${active.pageIndex + 1}`}</p><pre>{active.text}</pre><p className={styles.sourceNotice}>This text is not independently verified.</p></> : blocks.length ? <div>{blocks.map(block => <button className={styles.passageButton} type="button" key={block.id} onClick={() => setActive(block)}>Page {block.pageIndex + 1} · {block.text.slice(0, 100)}…</button>)}</div> : <Empty className="h-full justify-center p-8"><EmptyHeader><EmptyMedia><BookOpen className="size-8 text-muted-foreground" /></EmptyMedia><EmptyTitle>Inspect support</EmptyTitle><EmptyDescription>Select a source or citation to see the exact passage behind it.</EmptyDescription></EmptyHeader></Empty>}</div></div>{error ? <p className={styles.error} role="alert">{error}</p> : null}</section>;
}

type NoteEditorProps = {
  closeRequest: boolean; onClose: () => void; onCloseRequestHandled: () => void; onDirtyChange: (dirty: boolean) => void;
  seed: WorkspaceNoteSeed | null; onSeedConsumed: (id: string) => void; noteToOpen: string | null; onNoteOpenConsumed: (noteId: string) => void;
  quizToOpen?: WorkspaceQuizOpen | null; fullPage?: boolean; onRecordClass?: (folder: string | null) => void; onUseInChat?: () => void;
  listHost?: HTMLElement | null; courses?: CourseSummary[]; courseFilter?: string | null; onCourseFilter?: (id: string | null) => void;
  command?: NotesCommand | null; onNoteSelected?: (id: string | null) => void; onDiscuss?: (context: TutorChatContext) => void;
};

function NoteEditor({ closeRequest, onClose, onCloseRequestHandled, onDirtyChange, seed, onSeedConsumed, noteToOpen, onNoteOpenConsumed, quizToOpen, fullPage = false, onRecordClass, onUseInChat, listHost, courses, courseFilter = null, onCourseFilter, command, onNoteSelected, onDiscuss }: NoteEditorProps) {
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [courseNames, setCourseNames] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<NoteDraft | null>(null);
  const [savedDraft, setSavedDraft] = useState<NoteDraft | null>(null);
  useEffect(() => { if (draft?.id) reportVoiceFocus({ note_id: draft.id, expected_revision: draft.revision }); }, [draft?.id, draft?.revision]);
  const [query, setQuery] = useState('');
  const [editorEpoch, setEditorEpoch] = useState(0);
  const [folders, setFolders] = useState<string[]>([]);
  const [newFolder, setNewFolder] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<WorkspaceNoteSummary | null>(null);
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [selectedExcerpt, setSelectedExcerpt] = useState<{ text: string; start: number; x: number; y: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [listCollapsed, setListCollapsed] = useState(false);
  // The initializer above runs during server rendering (always expanded);
  // sync the persisted preference on the client after mount.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { if (!fullPage) setListCollapsed(localStorage.getItem('forma-notes-list-v1') === 'collapsed'); } catch { /* Stay expanded. */ }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [fullPage]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const requestId = useRef(0);
  const titleRefresh = useRef<Promise<unknown> | null>(null);
  const richBody = useRef<HTMLElement | null>(null);
  const bodyWrap = useRef<HTMLDivElement | null>(null);
  const noteItemsRef = useRef<HTMLDivElement | null>(null);
  const consumedSeeds = useRef(new Set<string>());
  const consumedCommands = useRef(new Set<number>());
  const titleInput = useRef<HTMLInputElement | null>(null);
  const consumedOpenNote = useRef<string | null>(null);

  const dirty = Boolean(draft && (savedDraft
    ? draft.title !== savedDraft.title || draft.body !== savedDraft.body
    : draft.title.trim() !== 'Untitled note' || draft.body.trim()));

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { const stored = JSON.parse(localStorage.getItem('open-learn-note-folders-v1') || '[]'); if (Array.isArray(stored)) setFolders(stored.filter((item): item is string => typeof item === 'string')); } catch { /* Optional folder preference. */ }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  const ensureTitles = useCallback(() => {
    if (!fullPage) return Promise.resolve();
    if (!titleRefresh.current) titleRefresh.current = learningApi.refreshNoteTitles().catch(cause => { titleRefresh.current = null; throw cause; });
    return titleRefresh.current;
  }, [fullPage]);

  async function loadNotes(search = '') {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError('');
    try {
      await ensureTitles();
      const result = search.trim()
        ? (await learningApi.searchWorkspaceNotes(search)).notes
        : await learningApi.listWorkspaceNotes();
      if (currentRequest === requestId.current) setNotes(result);
      if (currentRequest === requestId.current) setFolders(current => [...new Set([...current, ...result.map(note => note.frontmatter.note_folder).filter((folder): folder is string => typeof folder === 'string' && Boolean(folder))])].sort((a, b) => a.localeCompare(b)));
    } catch (cause) {
      if (currentRequest === requestId.current) {
        const friendly = friendlyServiceError(cause, 'Notes');
        setError(`${friendly.message} ${friendly.detail}`);
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void loadNotes(query), 180);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    noteItemsRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest' });
  }, [draft?.id, notes]);
  useEffect(() => {
    let live = true;
    if (courses) setCourseNames(Object.fromEntries(courses.map(course => [course.id, course.name])));
    else void learningApi.listCourses().then(items => {
      if (live) setCourseNames(Object.fromEntries(items.map(course => [course.id, course.name])));
    }).catch(() => undefined);
    return () => { live = false; };
  }, [courses]);

  const confirmBefore = useCallback((action: () => void) => {
    if (!dirty) { action(); return; }
    setPendingAction(() => action);
  }, [dirty]);

  useEffect(() => {
    if (!closeRequest) return;
    const timer = window.setTimeout(() => confirmBefore(onClose), 0);
    return () => window.clearTimeout(timer);
  }, [closeRequest, confirmBefore, onClose]);
  useEffect(() => {
    if (!seed || consumedSeeds.current.has(seed.id)) return;
    const timer = window.setTimeout(() => confirmBefore(() => {
      setDraft({ id: null, title: seed.title, body: seed.body, revision: null, frontmatter: seed.frontmatter });
      setSavedDraft(null);
      setSelectedExcerpt(null);
      setEditorEpoch(value => value + 1);
      setError('');
      consumedSeeds.current.add(seed.id);
      onSeedConsumed(seed.id);
    }), 0);
    return () => window.clearTimeout(timer);
  }, [confirmBefore, onSeedConsumed, seed]);

  function startBlank() {
    confirmBefore(() => {
      onNoteSelected?.(null);
      setDraft({ ...blankDraft(), frontmatter: { ...(activeFolder ? { note_folder: activeFolder } : {}), ...(courseFilter ? { course_id: courseFilter } : {}) } });
      setSavedDraft(null);
      setSelectedExcerpt(null);
      setEditorEpoch(value => value + 1);
      setError('');
    });
  }

  useEffect(() => {
    if (!command || consumedCommands.current.has(command.id)) return;
    consumedCommands.current.add(command.id);
    if (command.action === 'new-folder') setNewFolder(true);
    else startBlank();
  }, [command, confirmBefore]);

  const loadNote = useCallback(async (noteId: string) => {
    setLoading(true);
    setError('');
    setOpenMenu(null);
    setSelectedExcerpt(null);
    try {
      await ensureTitles();
      const note = await learningApi.getWorkspaceNote(noteId);
      onNoteSelected?.(note.id);
      setDraft(toDraft(note));
      setSavedDraft(toDraft(note));
      setEditorEpoch(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The note could not be opened.');
    } finally { setLoading(false); }
  }, [onNoteSelected, ensureTitles]);

  useEffect(() => {
    const refreshedTitle = () => {
      if (draft?.id && draft.frontmatter.study_note === true && !dirty) void loadNote(draft.id);
      void loadNotes(query);
    };
    window.addEventListener('forma:chat-title-changed', refreshedTitle);
    return () => window.removeEventListener('forma:chat-title-changed', refreshedTitle);
  }, [draft?.id, draft?.frontmatter.study_note, dirty, loadNote, query]);

  function openNote(noteId: string) {
    confirmBefore(() => { void loadNote(noteId); });
  }

  useEffect(() => {
    if (!noteToOpen) { consumedOpenNote.current = null; return; }
    if (consumedOpenNote.current === noteToOpen) return;
    if (draft?.id === noteToOpen) {
      consumedOpenNote.current = noteToOpen;
      onNoteOpenConsumed(noteToOpen);
      return;
    }
    const timer = window.setTimeout(() => confirmBefore(() => {
      consumedOpenNote.current = noteToOpen;
      onNoteOpenConsumed(noteToOpen);
      void loadNote(noteToOpen);
      void learningApi.listWorkspaceNotes().then(setNotes).catch(() => undefined);
    }), 0);
    return () => window.clearTimeout(timer);
  }, [confirmBefore, draft?.id, loadNote, noteToOpen, onNoteOpenConsumed]);

  async function save(): Promise<boolean> {
    if (!draft || saving) return false;
    const title = draft.title.trim();
    if (!title) { setError('Give this note a title before saving.'); return false; }
    setSaving(true);
    setError('');
    try {
      const saved = draft.id
        ? await learningApi.updateWorkspaceNote(draft.id, { title, body: draft.body, frontmatter: { ...draft.frontmatter, ...(savedDraft && title !== savedDraft.title ? { title_source: 'user' } : {}) }, expectedRevision: draft.revision! })
        : await learningApi.createWorkspaceNote({ title, body: draft.body, frontmatter: { ...draft.frontmatter, title_source: draft.frontmatter.title_source || 'user' } });
      const next = toDraft(saved);
      setDraft(current => {
        if (!current || current.id !== draft.id) return current;
        if (current.title === draft.title && current.body === draft.body) return next;
        return { ...next, title: current.title, body: current.body, frontmatter: current.frontmatter };
      });
      setSavedDraft(next);
      onNoteSelected?.(saved.id);
      await loadNotes(query);
      return true;
    } catch (cause) {
      if (cause instanceof LearningApiError && (cause.code === 'revision_conflict' || cause.code === 'external_change_conflict')) {
        setError(`${cause.message} Your unsaved draft is still in the editor.`);
      } else {
        setError(cause instanceof Error ? cause.message : 'The note could not be saved.');
      }
    } finally { setSaving(false); }
    return false;
  }

  useEffect(() => {
    const hasContent = Boolean(draft && (draft.title.trim() !== 'Untitled note' || draft.body.trim()));
    if (!dirty || saving || !hasContent) return;
    const timer = window.setTimeout(() => { void save(); }, 650);
    return () => window.clearTimeout(timer);
  }, [draft?.body, draft?.title, dirty, saving]);

  function setListCollapsedPersisted(collapsed: boolean) {
    setListCollapsed(collapsed);
    try { localStorage.setItem('forma-notes-list-v1', collapsed ? 'collapsed' : 'expanded'); } catch { /* Layout preference is optional. */ }
  }

  function applyFormat(format: string) {
    richBody.current?.focus();
    const commands: Record<string, [string, string?]> = {
      heading: ['formatBlock', 'h2'], bold: ['bold'], italic: ['italic'], bullet: ['insertUnorderedList'], numbered: ['insertOrderedList'], quote: ['formatBlock', 'blockquote'],
    };
    if (format === 'link') {
      const address = window.prompt('Link URL');
      if (address && /^https?:\/\//i.test(address)) document.execCommand('createLink', false, address);
    } else if (format === 'checklist') document.execCommand('insertText', false, '☐ ');
    else if (commands[format]) document.execCommand(commands[format][0], false, commands[format][1]);
    if (richBody.current) setDraft(current => current ? { ...current, body: richNoteToMarkdown(richBody.current!) } : current);
  }

  function inspectSelection() {
    const selection = window.getSelection();
    const text = selection?.toString().trim() || '';
    if (!selection || !richBody.current?.contains(selection.anchorNode) || !text || text.length > 6000 || !draft?.id || !draft.revision || dirty) { setSelectedExcerpt(null); return; }
    const start = draft.body.indexOf(text);
    if (start < 0 || draft.body.indexOf(text, start + 1) >= 0) { setSelectedExcerpt(null); return; }
    const range = selection.getRangeAt(0).getBoundingClientRect();
    const wrap = bodyWrap.current?.getBoundingClientRect();
    if (!wrap) return;
    setSelectedExcerpt({ text, start, x: Math.max(8, Math.min(range.left - wrap.left, wrap.width - 145)), y: Math.max(8, range.top - wrap.top - 42) });
  }

  function mentionExcerpt() {
    if (!draft?.id || !draft.revision || !selectedExcerpt) return;
    const { text, start } = selectedExcerpt;
    if (onDiscuss) {
      onDiscuss({ id: draft.id, title: draft.title, excerpt: text, courseId: typeof draft.frontmatter.course_id === 'string' ? draft.frontmatter.course_id : null, note: { noteId: draft.id, expectedRevision: draft.revision, startOffset: start, endOffset: start + text.length } });
      setSelectedExcerpt(null);
      return;
    }
    mentionWorkspaceNoteExcerpt({ noteId: draft.id, title: draft.title, revision: draft.revision, startOffset: start, endOffset: start + text.length, excerpt: text });
    setSelectedExcerpt(null);
    onUseInChat?.();
  }

  function discussNote() {
    if (!draft?.id || !draft.revision || dirty) {
      setError('Save this note before discussing it in chat.');
      return;
    }
    if (!draft.body.trim()) {
      setError('Select a passage in this note to discuss it in chat.');
      return;
    }
    if (onDiscuss) {
      const excerpt = draft.body.slice(0, 6000);
      onDiscuss({ id: draft.id, title: draft.title, excerpt, truncated: draft.body.length > 6000, courseId: typeof draft.frontmatter.course_id === 'string' ? draft.frontmatter.course_id : null, note: { noteId: draft.id, expectedRevision: draft.revision, startOffset: 0, endOffset: excerpt.length } });
      return;
    }
    if (draft.body.length > 6000) { setError('Select a shorter passage to discuss in chat.'); return; }
    mentionWorkspaceNoteExcerpt({ noteId: draft.id, title: draft.title, revision: draft.revision, startOffset: 0, endOffset: draft.body.length, excerpt: draft.body });
    onUseInChat?.();
  }

  function exportNote() {
    if (!draft) return;
    const content = `---\ntitle: ${JSON.stringify(draft.title)}\n---\n\n${draft.body}`;
    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${draft.title.trim().replace(/[\\/:*?"<>|]/g, '-').slice(0, 80) || 'note'}.md`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setOpenMenu(null);
  }

  function createFolder() {
    const name = folderName.trim();
    if (!name || folders.some(item => item.toLowerCase() === name.toLowerCase())) return;
    const next = [...folders, name].sort((a, b) => a.localeCompare(b));
    setFolders(next);
    localStorage.setItem('open-learn-note-folders-v1', JSON.stringify(next));
    setNewFolder(false); setFolderName(''); setActiveFolder(name);
  }

  async function moveNote(note: WorkspaceNoteSummary, folder: string | null, courseId?: string | null) {
    setOpenMenu(null);
    if (dirty && draft?.id === note.id) { setError('Save this note before moving it to a folder.'); return; }
    try {
      const full = await learningApi.getWorkspaceNote(note.id);
      const updated = await learningApi.updateWorkspaceNote(note.id, { title: full.title, body: full.body, frontmatter: { ...full.frontmatter, note_folder: folder, ...(courseId !== undefined ? { course_id: courseId } : {}) }, expectedRevision: full.revision });
      if (draft?.id === note.id) { setDraft(toDraft(updated)); setSavedDraft(toDraft(updated)); }
      await loadNotes(query);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not move the note.'); }
  }

  async function deleteNote() {
    if (!deleting) return;
    if (dirty && draft?.id === deleting.id) { setError('Save or discard your changes before deleting this note.'); setDeleting(null); return; }
    try {
      await learningApi.deleteWorkspaceNote(deleting.id, draft?.id === deleting.id ? draft.revision! : deleting.revision);
      const recordingId = deleting.frontmatter?.class_recording_id;
      if (typeof recordingId === 'string') await deleteClassRecording(recordingId);
      if (draft?.id === deleting.id) { setDraft(null); setSavedDraft(null); onNoteSelected?.(null); }
      setDeleting(null); setOpenMenu(null);
      await loadNotes(query);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not delete the note.'); }
  }

  const noteList = (
    <div className={styles.noteList}>
      <div className={styles.noteListTop}>
        {!fullPage ? <button type="button" className={styles.listToggle} title="Hide note list" aria-label="Hide note list" aria-expanded="true" onClick={() => setListCollapsedPersisted(true)}><PanelLeftClose size={15} /></button> : null}
        <div className={styles.search}><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search notes" aria-label="Search notes" /></div>
        {!fullPage ? <Button type="button" size="icon-sm" variant="outline" onClick={startBlank} aria-label="Create blank note"><Plus size={16} /></Button> : null}
      </div>
      {!fullPage ? <div className={styles.noteListActions}><button type="button" onClick={() => setNewFolder(true)}><FolderPlus size={15} />New folder</button></div> : null}
      {newFolder ? <form className={styles.folderForm} onSubmit={event => { event.preventDefault(); createFolder(); }}><input autoFocus value={folderName} onChange={event => setFolderName(event.target.value)} placeholder="Folder name" aria-label="Folder name" /><button type="submit">Create</button><button type="button" onClick={() => setNewFolder(false)} aria-label="Cancel"><X size={14} /></button></form> : null}
      {fullPage ? <div className={styles.folderNav}>
        <span className={styles.navSectionLabel}><FolderClosed size={14} />Folders</span>
        <button type="button" className={!activeFolder && !courseFilter ? styles.folderActive : ''} onClick={() => { setActiveFolder(null); onCourseFilter?.(null); }}><FolderClosed size={15} />All notes</button>
        {courses?.map(course => <button type="button" key={course.id} className={courseFilter === course.id && !activeFolder ? styles.folderActive : ''} onClick={() => { setActiveFolder(null); onCourseFilter?.(course.id); }}><FolderClosed size={15} /><span>{course.name}</span></button>)}
        {folders.map(folder => <button type="button" className={activeFolder === folder ? styles.folderActive : ''} key={`folder:${folder}`} onClick={() => setActiveFolder(folder)}><FolderClosed size={15} />{folder}<small>{notes.filter(note => note.frontmatter?.note_folder === folder).length}</small></button>)}
      </div> : null}
      <div ref={noteItemsRef} className={styles.noteItems} aria-live="polite">
        {loading && notes.length === 0 ? <p className={styles.muted}>Loading notes…</p> : null}
        {!loading && notes.length === 0 ? <div className={styles.emptyList}><FileText size={18} /><span>{query ? 'No matching notes.' : 'No notes yet.'}</span></div> : null}
        {(() => {
          const visible = notes.filter(note => (!fullPage || !courseFilter || note.frontmatter.course_id === courseFilter) && (!activeFolder || note.frontmatter.note_folder === activeFolder));
          const lessons = visible.filter(note => note.noteType === 'lesson');
          const mine = visible.filter(note => note.noteType !== 'lesson');
          const row = (note: typeof notes[number]) => (
            <div key={note.id} className={`${styles.noteRow} ${draft?.id === note.id ? styles.selected : ''}`}>
              <button type="button" className={styles.noteItem} onClick={() => void openNote(note.id)} aria-current={draft?.id === note.id ? 'page' : undefined} title={note.title}><span className={styles.noteTitle}><span aria-hidden="true">{note.noteType === 'lesson' ? <Sparkles size={15} /> : note.noteType === 'recording' ? <Mic size={15} /> : <FileText size={15} />}</span><strong>{noteDisplayTitle(note, notes)}</strong></span>{note.preview ? <span className={styles.noteExcerpt}>{note.preview}</span> : null}<small>{note.noteType === 'recording' ? 'Class recording · ' : ''}Edited {new Date(note.updatedAt).toLocaleDateString()}{typeof note.frontmatter.course_id === 'string' ? <span className={styles.noteCourse}>{courseNames[note.frontmatter.course_id] || 'Course'}</span> : null}</small></button>
              <button type="button" className={styles.noteMenuButton} aria-label={`More options for ${note.title}`} aria-expanded={openMenu === note.id} onClick={() => setOpenMenu(openMenu === note.id ? null : note.id)}><MoreHorizontal size={17} /></button>
              {openMenu === note.id ? <div className={styles.noteMenu} role="menu"><span>Move to folder</span><button type="button" role="menuitem" onClick={() => void moveNote(note, null)}>No folder</button>{folders.map(folder => <button type="button" role="menuitem" key={folder} onClick={() => void moveNote(note, folder)}>{folder}</button>)}<button type="button" role="menuitem" className={styles.deleteAction} onClick={() => { setDeleting(note); setOpenMenu(null); }}>Delete note</button></div> : null}
            </div>
          );
          return <>
            {visible.length === 0 && notes.length > 0 ? <p className={styles.muted}>No notes in this folder yet.</p> : null}
            {mine.length > 0 ? <h2 className={styles.groupLabel}><span>Your notes</span><span className={styles.groupCount}>{mine.length}</span></h2> : null}
            {mine.map(row)}
            {lessons.length > 0 ? <h2 className={`${styles.groupLabel} ${styles.generatedGroup}`}><span className={styles.groupHeading}><Sparkles size={14} />Generated</span><span className={styles.groupCount}>{lessons.length}</span></h2> : null}
            {lessons.map(row)}
          </>;
        })()}
      </div>
    </div>
  );

  return <section className={`${styles.notes} ${fullPage ? styles.notesHome + " " + styles.unifiedNotes : ""} ${!fullPage && listCollapsed ? styles.listCollapsed : ""}`} aria-label="Notes workspace">
    {fullPage ? (listHost ? createPortal(noteList, listHost) : null) : noteList}
    <div className={`${styles.editor} ${draft?.frontmatter?.study_note === true ? styles.lessonEditor : ''}`}>
      {draft || listCollapsed ? <div className={styles.editorTop}>
        {listCollapsed ? <button type="button" className={styles.listToggle} title="Show note list" aria-label="Show note list" aria-expanded="false" onClick={() => setListCollapsedPersisted(false)}><PanelLeft size={15} /></button> : null}
        {draft ? <input ref={titleInput} value={draft.title} onChange={event => setDraft(current => current ? { ...current, title: event.target.value } : current)} aria-label="Note title" placeholder="Note title" /> : null}
        {draft && fullPage ? <div className={styles.editorActions}>
          <Button type="button" size="icon-sm" variant="ghost" aria-label="Discuss this note" title="Discuss this note" onClick={discussNote}><Send size={16} /></Button>
          <Button type="button" size="icon-sm" variant="ghost" aria-label="Record a class" title="Record a class" onClick={() => onRecordClass?.(activeFolder)}><Mic size={16} /></Button>
          <button type="button" className={styles.editorMenuTrigger} aria-label="More note actions" aria-expanded={openMenu === 'editor'} onClick={() => setOpenMenu(openMenu === 'editor' ? null : 'editor')}><MoreHorizontal size={18} /></button>
          {openMenu === 'editor' ? <div className={styles.editorMenu} role="menu">
            <button type="button" role="menuitem" onClick={() => { setOpenMenu(null); titleInput.current?.focus(); titleInput.current?.select(); }}>Rename</button>
            <button type="button" role="menuitem" onClick={exportNote}><Download size={15} />Export Markdown</button>
            {draft.id ? <>
              <span>Move to folder</span>
              {courses?.map(course => <button type="button" role="menuitem" key={course.id} onClick={() => { const note = notes.find(item => item.id === draft.id); if (note) void moveNote(note, null, course.id); }}>{course.name}</button>)}
              <button type="button" role="menuitem" onClick={() => { const note = notes.find(item => item.id === draft.id); if (note) void moveNote(note, null); }}>No folder</button>
              {folders.map(folder => <button type="button" role="menuitem" key={folder} onClick={() => { const note = notes.find(item => item.id === draft.id); if (note) void moveNote(note, folder); }}>{folder}</button>)}
              <button type="button" role="menuitem" className={styles.deleteAction} onClick={() => { const note = notes.find(item => item.id === draft.id); if (note) setDeleting(note); setOpenMenu(null); }}>Delete note</button>
            </> : null}
          </div> : null}
        </div> : null}
      </div> : null}
      {!draft ? (
        <Empty className="h-full justify-center p-8">
          <EmptyHeader>
            <EmptyMedia>
              <BookOpen className="size-8 text-muted-foreground" />
            </EmptyMedia>
            <EmptyTitle>Capture what matters</EmptyTitle>
            <EmptyDescription>
              Keep your explanations, examples, and questions in one place.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button type="button" onClick={startBlank}>
              <Plus size={16} />New note
            </Button>
            {fullPage ? <Button type="button" variant="outline" onClick={() => onRecordClass?.(activeFolder)}><Mic size={16} />Record a class</Button> : null}
          </EmptyContent>
        </Empty>
      ) : <>
        <StudyNoteBar draft={draft} onChanged={(revision, frontmatter) => { const apply = (current: NoteDraft | null): NoteDraft | null => current && current.id ? { ...current, revision, frontmatter } : current; setDraft(apply); setSavedDraft(apply); }} />
        {(() => { const sessionIds = Array.isArray(draft.frontmatter?.session_ids) ? draft.frontmatter.session_ids as string[] : []; const sid = sessionIds[0]; const noteId = draft.id; return noteId && draft.frontmatter?.study_note === true && typeof sid === 'string' ? <NoteProposalList sessionId={sid} refreshKey={0} onChanged={() => void loadNote(noteId)} /> : null; })()}
        {typeof draft.frontmatter?.class_recording_id === 'string' && draft.id ? <RecordingPlayer recordingId={draft.frontmatter.class_recording_id} noteId={draft.id} duration={typeof draft.frontmatter.class_recording_duration_ms === 'number' ? draft.frontmatter.class_recording_duration_ms : undefined} markersMs={Array.isArray(draft.frontmatter.class_recording_markers_ms) ? draft.frontmatter.class_recording_markers_ms as number[] : []} onReady={() => { if (draft.id) void loadNote(draft.id); }} /> : null}
        {typeof draft.frontmatter?.lecture_recording_id === 'string' && draft.id ? <LectureNotesView recordingId={draft.frontmatter.lecture_recording_id} /> : null}
        {draft.body.trim() ? <div className={styles.formatBar} data-note-toolbar role="toolbar" aria-label="Note formatting"><div className={styles.formatTools}>{noteTools.map(({ format, label, icon: Icon }) => <button key={format} type="button" title={label} aria-label={label} onMouseDown={event => event.preventDefault()} onClick={() => applyFormat(format)}><Icon size={16} /></button>)}</div></div> : null}
        <div ref={bodyWrap} className={styles.bodyWrap} onMouseUp={inspectSelection} onKeyUp={inspectSelection}><RichNoteBody key={editorEpoch} initialBody={draft.body} editorRef={richBody} onChange={body => { setSelectedExcerpt(null); setDraft(current => current ? { ...current, body } : current); }} />{selectedExcerpt ? <button type="button" className={styles.excerptFloat} style={{ left: selectedExcerpt.x, top: selectedExcerpt.y }} onMouseDown={event => event.preventDefault()} onClick={mentionExcerpt}><Send size={13} />Ask in chat</button> : null}</div>
        <NoteVisualReferences body={draft.body}/>
        {draft.id && draft.frontmatter?.study_note === true && Array.isArray(draft.frontmatter?.session_ids) && typeof draft.frontmatter.session_ids[0] === 'string' ? <LessonPractice noteId={draft.id} sessionId={draft.frontmatter.session_ids[0]} noteTitle={draft.title} launch={quizToOpen?.lessonNoteId === draft.id ? quizToOpen : null} /> : null}
        {draft.id && draft.revision && !dirty ? <MakeFlashcards sessionId={Array.isArray(draft.frontmatter.session_ids)?draft.frontmatter.session_ids[0] as string:undefined} courseId={typeof draft.frontmatter.course_id==='string'?draft.frontmatter.course_id:undefined} sourceRefs={[{kind:draft.frontmatter.study_note?'lesson':'note',id:draft.id,revision:draft.revision}]} origin="learn"/> : null}
        <div className={styles.status} role="status">{saving ? 'Saving…' : dirty ? 'Saving changes…' : draft.id ? 'Saved locally' : 'Start typing to create this note'}</div>
      </>}
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
    </div>
    <AlertDialog open={Boolean(pendingAction)} onOpenChange={open => { if (!open) { setPendingAction(null); onCloseRequestHandled(); } }}>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogTitle>Keep your changes?</AlertDialogTitle>
          <AlertDialogDescription>
            Save this note before switching, or discard the unsaved edits.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => { setPendingAction(null); onCloseRequestHandled(); }}>
            Keep editing
          </AlertDialogCancel>
          <Button type="button" variant="ghost" onClick={() => {
            const action = pendingAction;
            setPendingAction(null);
            onCloseRequestHandled();
            action?.();
          }}>
            Discard
          </Button>
          <AlertDialogAction onClick={(e) => {
            e.preventDefault();
            void save().then(saved => {
              if (saved) {
                const action = pendingAction;
                setPendingAction(null);
                onCloseRequestHandled();
                action?.();
              }
            });
          }}>
            Save changes
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <AlertDialog open={Boolean(deleting)} onOpenChange={open => { if (!open) setDeleting(null); }}>
      <AlertDialogContent size="sm"><AlertDialogHeader><AlertDialogTitle>Delete this note?</AlertDialogTitle><AlertDialogDescription>{deleting?.title} will be removed from Notes. If it contains a class recording, the local audio will be removed too.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={event => { event.preventDefault(); void deleteNote(); }}>Delete note</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
  </section>;
}

/** Full notes destination. The chat side panel uses the same editor in a compact frame. */
export function NotesWorkspace({ onRecordClass, noteToOpen = null, onNoteOpenConsumed = () => undefined, ...sidebar }: Pick<NoteEditorProps, 'onRecordClass' | 'noteToOpen' | 'onNoteOpenConsumed' | 'listHost' | 'courses' | 'courseFilter' | 'onCourseFilter' | 'command' | 'onNoteSelected'>) {
  const [, setDirty] = useState(false);
  const [discussion, setDiscussion] = useState<TutorChatContext | null>(null);
  return <div className={styles.notesDestination}>
    <NoteEditor {...sidebar} closeRequest={false} onClose={() => undefined} onCloseRequestHandled={() => undefined} onDirtyChange={setDirty} seed={null} onSeedConsumed={() => undefined} noteToOpen={noteToOpen} onNoteOpenConsumed={onNoteOpenConsumed} fullPage onRecordClass={onRecordClass} onDiscuss={setDiscussion} />
    {discussion ? <CompactTutorChat key={discussion.id} context={discussion} onClose={() => { setDiscussion(null); document.querySelector<HTMLButtonElement>('[aria-label="Discuss this note"]')?.focus(); }} /> : null}
  </div>;
}

export function WorkspacePanel({ flashcardLaunch, classId, quizSessionId, quizConceptId, quizToOpen, layout, onLayoutChange, onCollapse, onExpand, noteSeed, noteToOpen, sourceToOpen, onNoteSeedConsumed, onNoteOpenConsumed }: {
  flashcardLaunch?:FlashcardView|null;
  classId?:string|null;
  quizSessionId?: string | null;
  quizConceptId?: string;
  quizToOpen?: WorkspaceQuizOpen | null;
  layout: WorkspacePanelLayout;
  onLayoutChange: Dispatch<SetStateAction<WorkspacePanelLayout>>;
  onCollapse: () => void;
  onExpand: () => void;
  noteSeed: WorkspaceNoteSeed | null;
  noteToOpen: string | null;
  sourceToOpen?: { spanId: string; versionId?: string } | null;
  onNoteSeedConsumed: (id: string) => void;
  onNoteOpenConsumed: (noteId: string) => void;
}) {
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [notesDirty, setNotesDirty] = useState(false);
  const [noteCloseRequest, setNoteCloseRequest] = useState(false);

  function openTab(tab: WorkspaceTab) {
    onLayoutChange(current => ({ ...current, collapsed: false, tabs: current.tabs.includes(tab) ? current.tabs : [...current.tabs, tab], activeTab: tab }));
    onExpand();
    setLauncherOpen(false);
  }

  function removeActiveTab() {
    onLayoutChange(current => {
      const tabs = current.tabs.filter(tab => tab !== current.activeTab);
      return { ...current, tabs, activeTab: tabs[0] || 'notes', collapsed: tabs.length === 0 };
    });
    if (layout.tabs.length === 1) onCollapse();
  }

  function closeActiveTab() {
    if (layout.activeTab === 'notes' && notesDirty) { setNoteCloseRequest(true); return; }
    removeActiveTab();
  }

  const active = layout.activeTab;
  return <aside className={`${styles.panel} ${layout.collapsed ? styles.collapsed : ''}`} aria-label="Workspace panel">
    <div className={styles.returnBar}><Button type="button" variant="ghost" size="sm" onClick={onCollapse}><PanelLeft size={15}/>Return to conversation</Button><span>Study workspace</span></div>
    <header className={styles.header}>
      <div className={styles.tabsHeader}>
        <Tabs value={active} onValueChange={(tab) => onLayoutChange(current => ({ ...current, activeTab: tab as WorkspaceTab }))}>
          <TabsList variant="line" className="h-8">
            {layout.tabs.map(tab => (
              <TabsTrigger key={tab} value={tab} className="text-xs px-2.5 py-1">
                {tabNames[tab]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className={styles.launcher}>
          <Button type="button" size="icon-xs" variant="ghost" onClick={() => setLauncherOpen(open => !open)} aria-expanded={launcherOpen} aria-label="Open a workspace tab" title="Add workspace tab">
            <Plus size={15} />
          </Button>
          {launcherOpen ? (
            <div className={styles.launcherMenu}>
              {(['notes', 'sources', 'flashcards'] as WorkspaceTab[]).map(tab => (
                <button type="button" key={tab} onClick={() => openTab(tab)}>{tabNames[tab]}</button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className={styles.headerActions}>
        {layout.tabs.length > 1 ? (
          <Button type="button" size="icon-xs" variant="ghost" onClick={closeActiveTab} aria-label={`Close ${tabNames[active]} tab`} title={`Close ${tabNames[active]} tab`}>
            <X size={15} />
          </Button>
        ) : null}
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          onClick={() => { onLayoutChange(current => ({ ...current, collapsed: true })); onCollapse(); }}
          aria-label="Close study canvas"
          title="Close study canvas · your work stays open"
        >
          <PanelRightClose size={15} />
        </Button>
      </div>
    </header>
    <div className={styles.content}>
      {layout.tabs.includes('notes') ? <div hidden={active !== 'notes'} className={styles.preservedTab}><NoteEditor closeRequest={noteCloseRequest} onDirtyChange={setNotesDirty} seed={noteSeed} onSeedConsumed={onNoteSeedConsumed} noteToOpen={noteToOpen} onNoteOpenConsumed={onNoteOpenConsumed} quizToOpen={quizToOpen} onCloseRequestHandled={() => setNoteCloseRequest(false)} onClose={() => { setNoteCloseRequest(false); removeActiveTab(); }} /></div> : null}
      {layout.tabs.includes('quiz') ? <div hidden={active !== 'quiz'} className={styles.preservedTab}><QuizWorkspace sessionId={quizToOpen?.sessionId || quizSessionId} conceptId={quizToOpen?.conceptId || quizConceptId} compact launch={quizToOpen?.origin === 'ask' ? quizToOpen : null} quizId={quizToOpen?.quizId} /></div> : null}
      {active === 'sources' ? <SourcesPanel sourceToOpen={sourceToOpen} /> : null}
      {layout.tabs.includes('flashcards') ? <div hidden={active!=='flashcards'} className={styles.preservedTab}><FlashcardWorkspace launch={flashcardLaunch}/></div> : null}
      {layout.tabs.includes('class') ? <div hidden={active!=='class'} className={styles.preservedTab}><InClassWorkspace classId={classId||null}/></div> : null}
    </div>
  </aside>;
}
