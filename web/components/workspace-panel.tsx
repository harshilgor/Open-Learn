"use client";
import { reportVoiceFocus } from "@/lib/voice/client";

import { memo, useCallback, useEffect, useRef, useState, type Dispatch, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type SetStateAction } from 'react';
import { createPortal } from 'react-dom';
import dynamic from 'next/dynamic';
import { Bold, BookOpen, CheckSquare2, Download, FileText, FolderClosed, FolderPlus, Heading2, ImagePlus, Italic, Link2, List, ListOrdered, Mic, MoreHorizontal, PanelLeft, PanelLeftClose, PanelRightClose, Plus, Quote, Search, Sparkles, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { readingRemarkPlugins, readingRehypePlugins } from '@/lib/markdown-rendering';
import { normalizeMathMarkdown } from '@/lib/normalize-math-markdown';
import 'katex/dist/katex.min.css';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { AudioLines, Check, ChevronLeft, Copy, FolderInput, History, Layers, ListChecks, Maximize2, MessagesSquare, Minimize2, Pin, PinOff, Shapes, Trash2, Undo2, Wand2 } from 'lucide-react';
import { DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@/components/ui/dropdown-menu';
import { NoteConnections, NoteQuickSwitcher, NoteTemplatePicker, SlashMenu, type NoteConnection } from './note-editor-extras';
import { NOTE_FILTERS, markdownShortcut, matchSlashCommands, matchesNoteFilter, noteWordCount, relativeTime, slashQuery, type NoteFilter, type SlashCommandId } from '@/lib/note-editing';
import { PracticeOverview } from './practice-overview';
import { CanvasTool } from './canvas-tool';
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
} from '@/components/ui/empty';
import { LearningApiError, friendlyServiceError, learningApi, request, type CourseSummary, type WorkspaceNote, type WorkspaceNoteSummary } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import type { WorkspaceQuizOpen } from '@/lib/workspace-events';
import styles from './workspace-panel.module.css';
import type {FlashcardView} from '@/lib/flashcards-client';
import { WORKSPACE_ASK_EVENT, WORKSPACE_NOTE_IMPROVE_EVENT, setWorkspacePanelCollapsed, openChatSession, requestWorkspaceQuiz } from '@/lib/workspace-events';
import { mentionWorkspaceNoteExcerpt, openWorkspaceFlashcards, type WorkspaceNoteSeed } from '@/lib/workspace-events';
import { StudyNoteBar } from './study-note-bar';
import { NoteProposalList } from './study-note-panel';
import { InlineNoteVisual, NOTE_VISUAL_LANGUAGES } from './visualization-reference';
import { richNoteToMarkdown } from '@/lib/rich-note-markdown';
import { prepareNoteImage } from '@/lib/note-images';
import { defaultUrlTransform } from 'react-markdown';
import { deleteClassRecording, getClassRecording, saveClassRecording } from '@/lib/class-recordings';
import type { NotesCommand } from './workspace-sidebar';
import { noteDisplayTitle } from '@/lib/note-list';
import type { TutorChatContext } from './compact-tutor-chat';
import { openSideChat } from '@/lib/workspace-side-chat-events';
import { WORKSPACE_PASSAGE_MENTION_EVENT } from '@/lib/workspace-events';

function WorkspaceFeatureLoading() {
  return <div className={styles.featureLoading} role="status" aria-live="polite">Loading workspace…</div>;
}

// Keep the note editor available immediately, but defer the larger tools until
// their tab or note feature is first opened. Once mounted, visited tabs remain
// mounted so their drafts and in-progress work keep the existing behavior.
const QuizWorkspace = dynamic(() => import('./quiz-workspace').then(module => module.QuizWorkspace), { loading: WorkspaceFeatureLoading });
const LessonPractice = dynamic(() => import('./quiz-workspace').then(module => module.LessonPractice), { loading: WorkspaceFeatureLoading });
const FlashcardWorkspace = dynamic(() => import('./flashcard-workspace').then(module => module.FlashcardWorkspace), { loading: WorkspaceFeatureLoading });
const MakeFlashcards = dynamic(() => import('./flashcard-create').then(module => module.MakeFlashcards), { loading: WorkspaceFeatureLoading });
const InClassWorkspace = dynamic(() => import('./in-class-workspace').then(module => module.InClassWorkspace), { loading: WorkspaceFeatureLoading });
const LectureNotesView = dynamic(() => import('./lecture-notes-view').then(module => module.LectureNotesView), { loading: WorkspaceFeatureLoading });
const CompactTutorChat = dynamic(() => import('./compact-tutor-chat').then(module => module.CompactTutorChat), { loading: WorkspaceFeatureLoading });

export type WorkspaceTool = 'notes' | 'canvas' | 'practice' | 'class';
/** Kept as an alias: layouts and events still call these "tabs". */
export type WorkspaceTab = WorkspaceTool;
export type PracticeView = 'home' | 'quiz' | 'flashcards';
export type WorkspacePanelLayout = { width: number; collapsed: boolean; tabs: WorkspaceTool[]; activeTab: WorkspaceTool; practiceView?: PracticeView; focused?: boolean; pinned?: boolean; noteId?:string|null; noteTabs?: {key:string;noteId:string|null;title:string}[]; activeNoteKey?:string };

/** Map a tab saved by an earlier version (quiz, flashcards, sources, reminders) to today's tools. */
export function workspaceToolFor(value: unknown): WorkspaceTool | null {
  if (value === 'notes' || value === 'canvas' || value === 'practice' || value === 'class') return value;
  if (value === 'quiz' || value === 'flashcards') return 'practice';
  return null;
}
type NoteDraft = (Pick<WorkspaceNote, 'id' | 'title' | 'body' | 'revision' | 'frontmatter'>) | { id: null; title: string; body: string; revision: null; frontmatter: Record<string, unknown> };

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

type HastNode = { tagName?: string; value?: string; properties?: { className?: unknown }; children?: HastNode[] };
/** A fenced visual reference (```visualization-ref / ```visual-artifact) inside a rendered note. */
function visualFence(node: unknown): { language: string; source: string } | null {
  const code = (node as HastNode | undefined)?.children?.find(child => child.tagName === 'code');
  const classes = Array.isArray(code?.properties?.className) ? code.properties.className.join(' ') : '';
  const language = classes.match(/language-([\w-]+)/)?.[1] || '';
  if (!code || !(NOTE_VISUAL_LANGUAGES as readonly string[]).includes(language)) return null;
  return { language, source: (code.children || []).map(child => child.value || '').join('').trim() };
}
/** Visuals render inline as atomic blocks; other code blocks stay plain. */
function NotePre({ node, children }: { node?: unknown; children?: ReactNode }) {
  const visual = visualFence(node);
  return visual ? <InlineNoteVisual {...visual}/> : <pre>{children}</pre>;
}

const RichNoteBody = memo(function RichNoteBody({ initialBody, editorRef, onChange, onImages }: {
  initialBody: string;
  editorRef: React.RefObject<HTMLElement | null>;
  onChange: (body: string) => void;
  onImages: (files: File[]) => void;
}) {
  const onChangeRef = useRef(onChange);
  const onImagesRef = useRef(onImages);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  useEffect(() => { onImagesRef.current = onImages; }, [onImages]);
  return <article ref={editorRef} className={styles.notePreview} contentEditable suppressContentEditableWarning role="textbox" aria-label="Note body" aria-multiline="true" data-placeholder="Write your note…" spellCheck onInput={event => onChangeRef.current(richNoteToMarkdown(event.currentTarget))} onPaste={event => {
    event.preventDefault();
    const images = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
    if (images.length) { onImagesRef.current(images); return; }
    document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
  }} onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault(); }} onDrop={event => { event.preventDefault(); const files=Array.from(event.dataTransfer.files); if(files.length)onImagesRef.current(files); }} onKeyDown={event=>{if((event.ctrlKey||event.metaKey)&&['b','i'].includes(event.key.toLowerCase())){event.preventDefault();document.execCommand(event.key.toLowerCase()==='b'?'bold':'italic');onChangeRef.current(richNoteToMarkdown(event.currentTarget));}}}>
    {initialBody.trim() ? <ReactMarkdown urlTransform={url => /^data:image\/(?:webp|png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(url) ? url : defaultUrlTransform(url)} remarkPlugins={readingRemarkPlugins as never} rehypePlugins={readingRehypePlugins as never} skipHtml components={{
      a: ({ href, children }) => <a href={href} onClick={event => event.preventDefault()}>{children}</a>,
      pre: NotePre,
      img: ({ alt, src }) => <img alt={alt || 'Note image'} src={src} loading="lazy" />,
      input: ({ checked, type }) => <input type={type} defaultChecked={checked} aria-label="Mark checklist item complete" contentEditable={false} onChange={event => {
        const editor = event.currentTarget.closest<HTMLElement>('[contenteditable="true"]');
        if (editor) onChangeRef.current(richNoteToMarkdown(editor));
      }}/>,
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

/** Shared heading for every study tool: icon, title, one line of context, optional action. */
function ToolHeader({ icon: Icon, title, description, action }: { icon: typeof FileText; title: string; description?: string; action?: ReactNode }) {
  return <header className={styles.toolHeader}>
    <span className={styles.toolIcon} aria-hidden="true"><Icon size={18}/></span>
    <div><h2>{title}</h2>{description ? <p>{description}</p> : null}</div>
    {action ? <div className={styles.toolHeaderAction}>{action}</div> : null}
  </header>;
}

/**
 * Practice brings quizzes and flashcards together. Its overview lists unfinished
 * and due work, then a single "new practice" form; an open quiz or flashcard deck
 * replaces the overview until the learner goes back.
 */
function PracticeTool({ sessionId, conceptId, view, onView, quizToOpen, flashcardLaunch }: { sessionId?: string | null; conceptId?: string; view: PracticeView; onView: (view: PracticeView) => void; quizToOpen?: WorkspaceQuizOpen | null; flashcardLaunch?: FlashcardView | null }) {
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [note, setNote] = useState<WorkspaceNote | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const [topic, setTopic] = useState('');
  const [kind, setKind] = useState<'quiz' | 'flashcards'>('quiz');
  const [starting, setStarting] = useState(false);
  useEffect(() => { let live = true; void learningApi.listWorkspaceNotesPage().then(value => { if (live) setNotes(value.notes); }).catch(cause => { if (live) setError(cause instanceof Error ? cause.message : 'Notes unavailable.'); }); return () => { live = false; }; }, []);
  useEffect(() => { let live = true; const timer=window.setTimeout(()=>setNote(null),0); if (selected) void learningApi.getWorkspaceNote(selected).then(value => { if (live) { setNote(value); setError(''); } }).catch(cause => { if (live) setError(cause instanceof Error ? cause.message : 'Note unavailable.'); }); return () => { live = false;window.clearTimeout(timer); }; }, [selected]);
  const linkedSession = note && Array.isArray(note.frontmatter.session_ids) && typeof note.frontmatter.session_ids[0] === 'string' ? note.frontmatter.session_ids[0] : null;
  const studyNotes = notes.filter(item => item.frontmatter.study_note && Array.isArray(item.frontmatter.session_ids) && item.frontmatter.session_ids.some(id => typeof id === 'string'));
  const sourceSession = note && note.frontmatter.study_note ? linkedSession : sessionId;
  const beginQuiz = () => {
    setStarting(true);
    requestWorkspaceQuiz({ requestedTopic: topic.trim(), sessionId: sourceSession || undefined, origin: note?.frontmatter.study_note ? 'learn' : undefined });
    window.setTimeout(() => setStarting(false), 1200);
  };
  const showQuiz = view === 'quiz' || !!quizToOpen;
  const showCards = view === 'flashcards' || !!flashcardLaunch;
  return <div className={styles.practice}>
    {view !== 'home' ? <div className={styles.practiceBack}><Button type="button" variant="ghost" size="sm" onClick={() => onView('home')}><ChevronLeft size={16}/>Practice</Button><span>{view === 'quiz' ? 'Quiz' : 'Flashcards'}</span></div> : null}
    <div hidden={view !== 'home'} className={styles.toolPage}>
      <ToolHeader icon={ListChecks} title="Practice" description="Quizzes and flashcards from your chats, notes and classes." />
      <PracticeOverview />
      <section className={styles.practiceSection} aria-labelledby="practice-new">
        <h3 id="practice-new">New practice</h3>
        <div className={`ol-card ${styles.practiceCreate}`}>
          <div className={styles.kindSwitch} role="radiogroup" aria-label="Practice type">
            <button type="button" role="radio" aria-checked={kind === 'quiz'} onClick={() => setKind('quiz')}><ListChecks size={15}/>Quiz</button>
            <button type="button" role="radio" aria-checked={kind === 'flashcards'} onClick={() => setKind('flashcards')}><Layers size={15}/>Flashcards</button>
          </div>
          <label>Study from<select aria-label="Study from" value={selected} onChange={event => { setSelected(event.target.value); setTopic(''); }}><option value="">This conversation</option>{studyNotes.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          {kind === 'quiz' ? <label><span>Focus <small>Optional</small></span><input aria-label="Quiz topic" value={topic} onChange={event => setTopic(event.target.value)} placeholder="e.g. cellular respiration" /></label> : null}
          <p className={styles.practiceHint}>{note?.frontmatter.study_note ? `Uses ${note.title}.` : 'Uses the material in this conversation.'}</p>
          <div className={styles.practiceActions}>{kind === 'quiz' ? <Button size="sm" onClick={beginQuiz} disabled={starting}>{starting ? 'Opening quiz…' : 'Start quiz'}</Button> : <MakeFlashcards key={selected} sessionId={linkedSession || sessionId} sourceRefs={note ? [{kind: note.frontmatter.study_note ? 'lesson' : 'note', id: note.id, revision: note.revision}] : undefined} label="Make flashcards"/>}
            <Button size="sm" variant="ghost" onClick={() => openWorkspaceFlashcards({ view: 'library' })}><Layers size={15}/>Flashcard library</Button></div>
        </div>
        {note && linkedSession && note.frontmatter.study_note ? <LessonPractice key={note.id} noteId={note.id} sessionId={linkedSession} noteTitle={note.title}/> : null}
        {note && !note.frontmatter.study_note ? <Button size="sm" variant="outline" onClick={() => { const excerpt = note.body.slice(0, 6000); mentionWorkspaceNoteExcerpt({noteId: note.id, title: note.title, revision: note.revision, startOffset: 0, endOffset: excerpt.length, excerpt, prompt: 'Check my understanding of this note. Ask one question at a time and help me work through mistakes.'}); setWorkspacePanelCollapsed(true); }}>Check my understanding</Button> : null}
      </section>
      {error ? <p role="alert" className={styles.practiceHint}>{error}</p> : null}
    </div>
    {showQuiz ? <div hidden={view !== 'quiz'} className={styles.practiceView}><QuizWorkspace sessionId={quizToOpen?.sessionId || sessionId} conceptId={quizToOpen?.conceptId || conceptId} compact launch={quizToOpen?.origin === 'ask' ? quizToOpen : null} quizId={quizToOpen?.quizId} /></div> : null}
    {showCards ? <div hidden={view !== 'flashcards'} className={styles.practiceView}><FlashcardWorkspace launch={flashcardLaunch}/></div> : null}
  </div>;
}

type NoteEditorProps = {
  closeRequest: boolean; onClose: () => void; onCloseRequestHandled: () => void; onDirtyChange: (dirty: boolean) => void;
  seed: WorkspaceNoteSeed | null; onSeedConsumed: (id: string) => void; noteToOpen: string | null; onNoteOpenConsumed: (noteId: string) => void;
  quizToOpen?: WorkspaceQuizOpen | null; fullPage?: boolean; onRecordClass?: (folder: string | null) => void; onUseInChat?: () => void;
  listHost?: HTMLElement | null; courses?: CourseSummary[]; courseFilter?: string | null; onCourseFilter?: (id: string | null) => void;
  listWhenIdle?: boolean; command?: NotesCommand | null; onNoteSelected?: (id: string | null) => void; onDiscuss?: (context: TutorChatContext) => void; onTitleChange?:(title:string)=>void; startEmpty?:boolean; recoveryKey?:string; onOpenNote?:(id:string)=>void;
  /** Markdown to append to the open note (or a new note), e.g. a visual added from Canvas. */
  insertRequest?: NoteInsert | null; onInsertConsumed?: (id: string) => void;
};
export type NoteInsert = { id: string; markdown: string; title: string };

function NoteEditor({ listWhenIdle = false, closeRequest, onClose, onCloseRequestHandled, onDirtyChange, seed, onSeedConsumed, noteToOpen, onNoteOpenConsumed, quizToOpen, fullPage = false, onRecordClass, listHost, courses, courseFilter = null, onCourseFilter, command, onNoteSelected, onDiscuss,onTitleChange, startEmpty=false, recoveryKey='', onOpenNote, insertRequest = null, onInsertConsumed }: NoteEditorProps) {
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [courseNames, setCourseNames] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<NoteDraft | null>(startEmpty ? blankDraft : null);
  const [reading, setReading] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState('');
  const [imageBusy, setImageBusy] = useState(false);
  const [noteFilter, setNoteFilter] = useState<NoteFilter>('all');
  const [slash, setSlash] = useState<{ query: string; x: number; y: number; index: number } | null>(null);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [pendingAsk, setPendingAsk] = useState<string | null>(null);
  const consumedInserts = useRef(new Set<string>());
  const imageInput = useRef<HTMLInputElement>(null);
  const imageSelection = useRef<Range|null>(null);
  useEffect(()=>{onTitleChange?.(draft?.title||'Notes');},[draft?.title,onTitleChange]);
  const [savedDraft, setSavedDraft] = useState<NoteDraft | null>(null);
  const [recoveryOwner,setRecoveryOwner] = useState<string|null>(null);
  const [recoveredDraft,setRecoveredDraft] = useState<NoteDraft|null>(null);
  const draftRef = useRef(draft);
  const savedDraftRef = useRef(savedDraft);
  const recoveryOwnerRef = useRef(recoveryOwner);
  const loadNotesRef = useRef<(search?: string, quiet?: boolean) => Promise<void>>(async () => undefined);
  draftRef.current = draft;
  savedDraftRef.current = savedDraft;
  recoveryOwnerRef.current = recoveryOwner;
  const [versions,setVersions]=useState<{id:string;noteRevision:number;title:string;body:string;savedAt:string}[]|null>(null);
  useEffect(()=>{
    let live=true;
    let identityEpoch=0;
    const restoreOwnerDraft=async(epoch:number)=>{
      try{
        const account=await request<{ownerId:string}>('/v1/account');
        if(!live||epoch!==identityEpoch)return;
        let saved:unknown=null;
        try{saved=JSON.parse(localStorage.getItem(`workspace-note-draft:${account.ownerId}${recoveryKey?':'+recoveryKey:''}`)||'null');}catch{/* No valid recovery. */}
        if(saved&&typeof saved==='object'&&typeof (saved as NoteDraft).body==='string'&&typeof (saved as NoteDraft).title==='string'&&(saved as NoteDraft).frontmatter&&typeof (saved as NoteDraft).frontmatter==='object')setRecoveredDraft(saved as NoteDraft);
        else setRecoveredDraft(null);
        setRecoveryOwner(account.ownerId);
        if(epoch>0){setNotes([]);void loadNotesRef.current('');}
      }catch{/* The editor remains usable; account recovery can retry on the next identity change. */}
    };
    const onAccountChanged=()=>{
      identityEpoch++;
      const owner=recoveryOwnerRef.current;
      const current=draftRef.current;
      const baseline=savedDraftRef.current;
      const hasUnsaved=Boolean(current&&(baseline?current.title!==baseline.title||current.body!==baseline.body:current.title.trim()!=='Untitled note'||current.body.trim()));
      if(owner&&current&&hasUnsaved){try{localStorage.setItem(`workspace-note-draft:${owner}${recoveryKey?':'+recoveryKey:''}`,JSON.stringify(current));}catch{/* Keep in-memory recovery if browser storage is unavailable. */}}
      setDraft(null);setSavedDraft(null);setRecoveryOwner(null);setRecoveredDraft(null);setError('');setListRefreshError('');
      void restoreOwnerDraft(identityEpoch);
    };
    void restoreOwnerDraft(identityEpoch);
    window.addEventListener(ACCOUNT_CHANGED,onAccountChanged);
    return()=>{live=false;window.removeEventListener(ACCOUNT_CHANGED,onAccountChanged);};
  },[recoveryKey]);
  useEffect(() => { if (draft?.id) reportVoiceFocus({ quiz_id:null,presentation_id:null,lesson_id:null,visualization_id:null,note_id: draft.id, expected_revision: draft.revision,selection_start:null,selection_end:null,selected_text:null,source_span_id:null }); }, [draft?.id, draft?.revision]);
  const [query, setQuery] = useState('');
  const [editorEpoch, setEditorEpoch] = useState(0);
  const [folders, setFolders] = useState<string[]>([]);
  const [newFolder, setNewFolder] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<WorkspaceNoteSummary | null>(null);
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  // start is the excerpt's offset in the saved Markdown, or -1 when it can't be located exactly.
  const [selectedExcerpt, setSelectedExcerpt] = useState<{ text: string; start: number; x: number; y: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [listCollapsed, setListCollapsed] = useState(false);
  // The initializer above runs during server rendering (always expanded);
  // sync the persisted preference on the client after mount.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { if (!fullPage) setListCollapsed(localStorage.getItem('forma-notes-list-v1') !== 'expanded'); } catch { /* Stay expanded. */ }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [fullPage]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [listRefreshError, setListRefreshError] = useState('');
  const [notesCursor, setNotesCursor] = useState<string | null>(null);
  const [loadingMoreNotes, setLoadingMoreNotes] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const requestId = useRef(0);
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
  const unresolvedRecoveredDraft = recoveredDraft && !(savedDraft && recoveredDraft.id === savedDraft.id
    && recoveredDraft.title === savedDraft.title && recoveredDraft.body === savedDraft.body) ? recoveredDraft : null;
  useEffect(()=>{if(!recoveryOwner||!draft||unresolvedRecoveredDraft)return;try{if(dirty)localStorage.setItem(`workspace-note-draft:${recoveryOwner}${recoveryKey?':'+recoveryKey:''}`,JSON.stringify(draft));else localStorage.removeItem(`workspace-note-draft:${recoveryOwner}${recoveryKey?':'+recoveryKey:''}`);}catch{/* In-memory edits remain available. */}},[recoveryOwner,draft,dirty,unresolvedRecoveredDraft,recoveryKey]);

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

  const loadNotes = useCallback(async (search = '', quiet = false) => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setListRefreshError('');
    try {
      const page = search.trim() ? null : await learningApi.listWorkspaceNotesPage();
      const result = search.trim() ? (await learningApi.searchWorkspaceNotes(search)).notes : page!.notes;
      if (currentRequest === requestId.current) {
        setNotes(result);
        setNotesCursor(page?.nextCursor || null);
      }
      if (currentRequest === requestId.current) setFolders(current => [...new Set([...current, ...result.map(note => note.frontmatter.note_folder).filter((folder): folder is string => typeof folder === 'string' && Boolean(folder))])].sort((a, b) => a.localeCompare(b)));
      if (currentRequest === requestId.current && quiet) setListRefreshError('');
    } catch (cause) {
      if (currentRequest === requestId.current) {
        const friendly = friendlyServiceError(cause, 'Notes');
        setListRefreshError(quiet
          ? 'Your note is saved, but the notes list could not refresh. Use Refresh to try again.'
          : `${friendly.message} ${friendly.detail}`);
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, []);
  loadNotesRef.current = loadNotes;

  const loadMoreNotes = useCallback(async () => {
    const cursor = notesCursor;
    const currentRequest = requestId.current;
    if (!cursor || loadingMoreNotes) return;
    setLoadingMoreNotes(true);
    try {
      const page = await learningApi.listWorkspaceNotesPage(cursor);
      if (currentRequest !== requestId.current) return;
      setNotes(current => {
        const existing = new Set(current.map(note => note.id));
        return [...current, ...page.notes.filter(note => !existing.has(note.id))];
      });
      setNotesCursor(page.nextCursor);
      setFolders(current => [...new Set([...current, ...page.notes.map(note => note.frontmatter.note_folder).filter((folder): folder is string => typeof folder === 'string' && Boolean(folder))])].sort((a, b) => a.localeCompare(b)));
    } catch (cause) {
      if (currentRequest === requestId.current) {
        const friendly = friendlyServiceError(cause, 'Notes');
        setListRefreshError(`${friendly.message} ${friendly.detail}`);
      }
    } finally {
      setLoadingMoreNotes(false);
    }
  }, [loadingMoreNotes, notesCursor]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadNotes(query), 180);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    noteItemsRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest' });
  }, [draft?.id, notes]);
  useEffect(() => {
    let live = true;
    const timer=window.setTimeout(()=>{if(courses)setCourseNames(Object.fromEntries(courses.map(course=>[course.id,course.name])));},0);
    if(courses)return()=>{live=false;window.clearTimeout(timer);};
    void learningApi.listCourses().then(items => {
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
    const timer=window.setTimeout(()=>{if(command.action==='new-folder')setNewFolder(true);else startBlank();},0);
    return()=>window.clearTimeout(timer);
  }, [command, confirmBefore]);

  const loadNote = useCallback(async (noteId: string) => {
    setLoading(true);
    setError('');
    setOpenMenu(null);
    setSelectedExcerpt(null);
    try {
      const note = await learningApi.getWorkspaceNote(noteId);
      onNoteSelected?.(note.id);
      if (!fullPage) setListCollapsed(true);
      setDraft(toDraft(note));
      setSavedDraft(toDraft(note));
      setRecoveredDraft(current=>current?.id===note.id&&current.title===note.title&&current.body===note.body?null:current);
      setEditorEpoch(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The note could not be opened.');
    } finally { setLoading(false); }
  }, [onNoteSelected]);

  useEffect(() => {
    const refreshedTitle = () => {
      if (draft?.id && draft.frontmatter.study_note === true && !dirty) void loadNote(draft.id);
      void loadNotes(query);
    };
    window.addEventListener('forma:chat-title-changed', refreshedTitle);
    return () => window.removeEventListener('forma:chat-title-changed', refreshedTitle);
  }, [draft?.id, draft?.frontmatter.study_note, dirty, loadNote, query]);

  function openNote(noteId: string) {
    if(onOpenNote){onOpenNote(noteId);return;}
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
      void loadNotes(query, true);
    }), 0);
    return () => window.clearTimeout(timer);
  }, [confirmBefore, draft?.id, loadNote, loadNotes, noteToOpen, onNoteOpenConsumed, query]);

  async function save(): Promise<boolean> {
    if (!draft || saving) return false;
    const title = draft.title.trim();
    if (!title) { setError('Give this note a title before saving.'); return false; }
    if (draft.body.length > 200000) { setError('This note is full. Move some content or images into another note before saving.'); return false; }
    setSaving(true);
    setError('');
    setListRefreshError('');
    try {
      const input = { title, body: draft.body, frontmatter: { ...draft.frontmatter, ...(savedDraft && title !== savedDraft.title ? { title_source: 'user' } : {}) } };
      let saved: WorkspaceNote;
      if (draft.id) {
        // PATCH is revision fenced and the API recognizes an exact replay after
        // a lost response, so one bounded retry is safe. Never auto-retry creates.
        let attempt = 0;
        for (;;) {
          try {
            saved = await learningApi.updateWorkspaceNote(draft.id, { ...input, expectedRevision: draft.revision! });
            break;
          } catch (cause) {
            const transient = cause instanceof LearningApiError &&
              (cause.status === 408 || cause.status === 429 || cause.status >= 500);
            if (attempt >= 1 || !transient) throw cause;
            attempt += 1;
            await new Promise(resolve => window.setTimeout(resolve, 250));
          }
        }
      } else {
        saved = await learningApi.createWorkspaceNote({ ...input, frontmatter: { ...input.frontmatter, title_source: input.frontmatter.title_source || 'user' } });
      }
      const next = toDraft(saved);
      setDraft(current => {
        if (!current || current.id !== draft.id) return current;
        if (current.title === draft.title && current.body === draft.body) return next;
        return { ...next, title: current.title, body: current.body, frontmatter: current.frontmatter };
      });
      setSavedDraft(next);
      onNoteSelected?.(saved.id);
      // The note write is authoritative. A separate list refresh failure must
      // not turn a successful save into a red save error or invite duplicate work.
      await loadNotes(query, true);
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

  async function undoLastSave(){
    if(!draft?.id||dirty||saving)return;
    setSaving(true);setError('');
    try{const history=await learningApi.getWorkspaceNoteVersions(draft.id);const previous=history.versions[0];if(!previous){setError('No previous saved version is available.');return;}const restored=await learningApi.updateWorkspaceNote(draft.id,{title:previous.title,body:previous.body,expectedRevision:draft.revision!});setDraft(toDraft(restored));setSavedDraft(toDraft(restored));setEditorEpoch(value=>value+1);await loadNotes(query);}catch(cause){setError(cause instanceof Error?cause.message:'Could not undo the last save.');}finally{setSaving(false);}
  }

  useEffect(() => {
    const hasContent = Boolean(draft && (draft.title.trim() !== 'Untitled note' || draft.body.trim()));
    if (!dirty || saving || error || !hasContent) return;
    const timer = window.setTimeout(() => { void save(); }, 650);
    return () => window.clearTimeout(timer);
  }, [draft?.body, draft?.title, dirty, saving, error]);

  function setListCollapsedPersisted(collapsed: boolean) {
    setListCollapsed(collapsed);
    try { localStorage.setItem('forma-notes-list-v1', collapsed ? 'collapsed' : 'expanded'); } catch { /* Layout preference is optional. */ }
  }

  function applyFormat(format: string) {
    richBody.current?.focus();
    const commands: Record<string, [string, string?]> = {
      heading: ['formatBlock', 'h2'], subheading: ['formatBlock', 'h3'], bold: ['bold'], italic: ['italic'], bullet: ['insertUnorderedList'], numbered: ['insertOrderedList'], quote: ['formatBlock', 'blockquote'],
    };
    if (format === 'link') {
      const address = window.prompt('Link URL');
      if (address && /^https?:\/\//i.test(address)) document.execCommand('createLink', false, address);
    } else if (format === 'checklist') document.execCommand('insertHTML', false, '<ul><li><input type="checkbox" contenteditable="false" aria-label="Mark checklist item complete">&nbsp;</li></ul>');
    else if (commands[format]) document.execCommand(commands[format][0], false, commands[format][1]);
    if (richBody.current) setDraft(current => current ? { ...current, body: richNoteToMarkdown(richBody.current!) } : current);
  }

  const syncBody = () => { if (richBody.current) setDraft(current => current ? { ...current, body: richNoteToMarkdown(richBody.current!) } : current); };

  /** The block holding a collapsed caret, and the text typed before the caret in that block. */
  function caretBlock(): { block: HTMLElement; before: string; rect: DOMRect } | null {
    const editor = richBody.current, selection = window.getSelection();
    if (!editor || !selection?.rangeCount || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.startContainer)) return null;
    let node: Node | null = range.startContainer;
    while (node && node !== editor && !(node instanceof HTMLElement && /^(P|DIV|LI|H[1-6]|BLOCKQUOTE)$/.test(node.tagName))) node = node.parentNode;
    const block = node instanceof HTMLElement ? node : editor;
    const prefix = document.createRange(); prefix.selectNodeContents(block); prefix.setEnd(range.startContainer, range.startOffset);
    const rect = range.getBoundingClientRect?.();
    return { block, before: prefix.toString(), rect: rect && (rect.width || rect.height || rect.left) ? rect : block.getBoundingClientRect() };
  }

  /** Remove the characters just typed before the caret (a "/query" or a Markdown marker). */
  function deleteBeforeCaret(count: number) {
    const selection = window.getSelection();
    if (!selection?.rangeCount || count <= 0) return;
    const range = selection.getRangeAt(0);
    if (range.startContainer.nodeType !== Node.TEXT_NODE || range.startOffset < count) return;
    const remove = document.createRange(); remove.setStart(range.startContainer, range.startOffset - count); remove.setEnd(range.startContainer, range.startOffset);
    selection.removeAllRanges(); selection.addRange(remove);
    if (!document.execCommand('delete')) remove.deleteContents();
  }

  function updateSlash() {
    const caret = caretBlock();
    const query = caret ? slashQuery(caret.before) : null;
    const wrap = bodyWrap.current?.getBoundingClientRect();
    if (query === null || !caret || !wrap) { setSlash(current => current ? null : current); return; }
    const x = Math.max(8, Math.min(caret.rect.left - wrap.left, wrap.width - 288)), y = caret.rect.bottom - wrap.top + 6;
    setSlash(current => ({ query, x, y, index: current && current.query === query ? current.index : 0 }));
  }

  function runSlash(id: SlashCommandId) {
    deleteBeforeCaret((slash?.query.length ?? 0) + 1);
    setSlash(null);
    if (id === 'divider') { document.execCommand('insertHTML', false, '<hr><p><br></p>'); syncBody(); return; }
    if (id === 'image') { const selection = window.getSelection(); imageSelection.current = selection?.rangeCount ? selection.getRangeAt(0).cloneRange() : null; syncBody(); imageInput.current?.click(); return; }
    if (id === 'visual' || id === 'quiz') {
      syncBody();
      if (!richBody.current || !richNoteToMarkdown(richBody.current).trim()) { setError(id === 'visual' ? 'Write a little first, then ask Buddy for a visual of it.' : 'Write a little first, then ask Buddy to quiz you on it.'); return; }
      setPendingAsk(id === 'visual' ? 'Make a visual that explains this note' : 'Quiz me on this note');
      return;
    }
    applyFormat(id);
  }

  function editorKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (reading || !richBody.current?.contains(event.target as Node)) return;
    if (slash) {
      const commands = matchSlashCommands(slash.query);
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && commands.length) { event.preventDefault(); setSlash({ ...slash, index: (slash.index + (event.key === 'ArrowDown' ? 1 : -1) + commands.length) % commands.length }); return; }
      if ((event.key === 'Enter' || event.key === 'Tab') && commands.length) { event.preventDefault(); runSlash(commands[Math.min(slash.index, commands.length - 1)].id); return; }
      if (event.key === 'Escape') { event.preventDefault(); setSlash(null); return; }
    }
    if (event.key === ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const caret = caretBlock();
      if (!caret || !(caret.block === richBody.current || /^(P|DIV)$/.test(caret.block.tagName))) return;
      const shortcut = markdownShortcut(caret.before);
      if (!shortcut) return;
      event.preventDefault();
      deleteBeforeCaret(caret.before.length);
      applyFormat(shortcut);
    }
  }

  // A visual or quiz request waits until the note is saved, so Buddy reads the current revision.
  useEffect(() => {
    if (!pendingAsk || !draft?.id || !draft.revision || dirty || saving) return;
    const timer = window.setTimeout(() => {
      setPendingAsk(null);
      if (draft.body.length > 6000) { setError('This note is long. Select the part you want, then choose Visualize or Explain.'); return; }
      mentionWorkspaceNoteExcerpt({ noteId: draft.id!, title: draft.title, revision: draft.revision!, startOffset: 0, endOffset: draft.body.length, excerpt: draft.body, prompt: pendingAsk, submit: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [pendingAsk, draft, dirty, saving]);

  async function setNoteFrontmatter(note: Pick<WorkspaceNoteSummary, 'id'>, patch: Record<string, unknown>, failure: string) {
    setOpenMenu(null);
    if (dirty && draft?.id === note.id) { setError('Save this note first.'); return; }
    try {
      const full = await learningApi.getWorkspaceNote(note.id);
      const updated = await learningApi.updateWorkspaceNote(note.id, { title: full.title, body: full.body, frontmatter: { ...full.frontmatter, ...patch }, expectedRevision: full.revision });
      if (draft?.id === note.id) { setDraft(toDraft(updated)); setSavedDraft(toDraft(updated)); }
      await loadNotes(query, true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : failure); }
  }
  const togglePinned = (note: Pick<WorkspaceNoteSummary, 'id' | 'frontmatter'>) => void setNoteFrontmatter(note, { pinned: note.frontmatter?.pinned !== true }, 'Could not pin the note.');

  // Canvas "Add to note": append to the open note, or start a new one around the visual.
  useEffect(() => {
    if (!insertRequest || consumedInserts.current.has(insertRequest.id)) return;
    consumedInserts.current.add(insertRequest.id);
    const timer = window.setTimeout(() => {
      onInsertConsumed?.(insertRequest.id);
      if (draftRef.current) setDraft(current => current ? { ...current, body: `${current.body.trim()}${current.body.trim() ? '\n\n' : ''}${insertRequest.markdown}\n` } : current);
      else { setDraft({ ...blankDraft(), title: insertRequest.title, body: `${insertRequest.markdown}\n` }); setSavedDraft(null); }
      setReading(false);
      setEditorEpoch(value => value + 1);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [insertRequest, onInsertConsumed]);

  async function insertImages(files: File[]) {
    const editor = richBody.current;
    if (!editor) return;
    const selection = window.getSelection();
    const range = imageSelection.current || (selection?.rangeCount && editor.contains(selection.anchorNode) ? selection.getRangeAt(0).cloneRange() : null);
    imageSelection.current = null;
    setImageBusy(true); setError('');
    try {
      const images = await Promise.all(files.map(prepareNoteImage));
      if (richBody.current !== editor) return;
      if (richNoteToMarkdown(editor).length + images.join('').length + files.length * 100 > 195000) throw new Error('These images would fill this note. Add fewer images or use another note.');
      editor.focus();
      const currentSelection = window.getSelection();
      if (range && editor.contains(range.startContainer)) { currentSelection?.removeAllRanges(); currentSelection?.addRange(range); }
      else { const end = document.createRange(); end.selectNodeContents(editor); end.collapse(false); currentSelection?.removeAllRanges(); currentSelection?.addRange(end); }
      for (const [index, src] of images.entries()) {
        const alt = files[index].name.replace(/[<>"&]/g, '').slice(0, 120) || 'Pasted image';
        document.execCommand('insertHTML', false, `<img src="${src}" alt="${alt}"><p><br></p>`);
      }
      setDraft(current => current ? {...current, body:richNoteToMarkdown(editor)} : current);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not add this image.'); }
    finally { setImageBusy(false); }
  }

  function findInNote() {
    if (!richBody.current || !findText.trim()) return;
    setReading(false);
    const walker = document.createTreeWalker(richBody.current, NodeFilter.SHOW_TEXT);
    let node: Node|null;
    while ((node=walker.nextNode())) {
      const start=(node.textContent||'').toLowerCase().indexOf(findText.toLowerCase());
      if(start<0)continue;
      const range=document.createRange();range.setStart(node,start);range.setEnd(node,start+findText.length);
      const selection=window.getSelection();selection?.removeAllRanges();selection?.addRange(range);
      node.parentElement?.scrollIntoView({block:'center'});return;
    }
  }

  function inspectSelection() {
    const selection = window.getSelection();
    const text = selection?.toString().trim() || '';
    if (!selection || selection.isCollapsed || !richBody.current?.contains(selection.anchorNode) || !text || text.length > 6000 || !draft) { setSelectedExcerpt(null); return; }
    // Note-anchored actions need the exact saved offsets; otherwise the passage is sent as plain text.
    const found = draft.id && draft.revision && !dirty ? draft.body.indexOf(text) : -1;
    const start = found >= 0 && draft.body.indexOf(text, found + 1) < 0 ? found : -1;
    const range = selection.getRangeAt(0).getBoundingClientRect();
    const wrap = bodyWrap.current?.getBoundingClientRect();
    if (!wrap) return;
    setSelectedExcerpt({ text, start, x: Math.max(8, Math.min(range.left - wrap.left, wrap.width - Math.min(440, wrap.width - 16) - 8)), y: Math.max(8, range.top - wrap.top - 46) });
    if (start < 0 || !draft.id) return;
    reportVoiceFocus({quiz_id:null,presentation_id:null,lesson_id:null,visualization_id:null,note_id:draft.id,expected_revision:draft.revision,selection_start:start,selection_end:start+text.length,selected_text:null,source_span_id:null});
  }

  function mentionExcerpt(action = '') {
    if (!draft || !selectedExcerpt) return;
    const { text, start } = selectedExcerpt;
    if (start < 0 || !draft.id || !draft.revision) {
      window.dispatchEvent(new CustomEvent(WORKSPACE_PASSAGE_MENTION_EVENT, { detail: { title: draft.title, excerpt: text, submit: action === 'Explain this' } }));
      if (action && action !== 'Explain this') window.dispatchEvent(new CustomEvent(WORKSPACE_ASK_EVENT, { detail: `${action}.` }));
      setSelectedExcerpt(null);
      document.querySelector<HTMLTextAreaElement>('[id="chat-message"]')?.focus();
      return;
    }
    if (action === 'Suggest improvements') { window.dispatchEvent(new CustomEvent(WORKSPACE_NOTE_IMPROVE_EVENT, {detail: {noteId: draft.id, title: draft.title, revision: draft.revision, startOffset: start, endOffset: start + text.length, excerpt: text}})); setWorkspacePanelCollapsed(true); setSelectedExcerpt(null); return; }
    mentionWorkspaceNoteExcerpt({ noteId: draft.id, title: draft.title, revision: draft.revision, startOffset: start, endOffset: start + text.length, excerpt: text, prompt: action ? `${action}:\n\n${text}` : undefined, submit:action==='Explain this' });
    setSelectedExcerpt(null);
    document.querySelector<HTMLTextAreaElement>('[id="chat-message"]')?.focus();
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
    openSideChat({id:draft.id,title:draft.title,excerpt:draft.body,note:{noteId:draft.id,expectedRevision:draft.revision,startOffset:0,endOffset:draft.body.length},courseId:typeof draft.frontmatter.course_id==='string'?draft.frontmatter.course_id:null});
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

  // On small screens the notes destination is list-first: the list fills the view until a note is open.
  const idleList = listWhenIdle && !fullPage && !draft;
  const listHidden = listCollapsed && !idleList;
  // In the study panel an open list slides over the note; working in the note puts it away.
  const listOverlay = !fullPage && !idleList && !listCollapsed;
  const courseLabel = (note: { frontmatter: Record<string, unknown> }) => typeof note.frontmatter.course_id === 'string' ? courseNames[note.frontmatter.course_id] || 'Course' : '';
  const noteList = (
    <div className={styles.noteList} onKeyDown={event => { if (listOverlay && event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); setListCollapsedPersisted(true); } }}>
      <div className={styles.noteListTop}>
        {!fullPage && !idleList ? <button type="button" className={styles.listToggle} title="Hide note list" aria-label="Hide note list" aria-expanded="true" onClick={() => setListCollapsedPersisted(true)}><PanelLeftClose size={15} /></button> : null}
        <div className={styles.search}><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search notes" aria-label="Search notes" /></div>
        {!fullPage ? <Button type="button" size="icon-sm" variant="outline" onClick={startBlank} aria-label="Create blank note"><Plus size={16} /></Button> : null}
      </div>
      {!fullPage ? <div className={styles.noteListActions}><button type="button" onClick={() => setNewFolder(true)}><FolderPlus size={15} />New folder</button></div> : null}
      {newFolder ? <form className={styles.folderForm} onSubmit={event => { event.preventDefault(); createFolder(); }}><input autoFocus value={folderName} onChange={event => setFolderName(event.target.value)} placeholder="Folder name" aria-label="Folder name" /><button type="submit">Create</button><button type="button" onClick={() => setNewFolder(false)} aria-label="Cancel"><X size={14} /></button></form> : null}
      {fullPage ? <div className={styles.folderNav}>
        <span className={styles.navSectionLabel}><FolderClosed size={14} />Folders</span>
        <button type="button" className={!activeFolder && !courseFilter ? styles.folderActive : ''} onClick={() => { setActiveFolder(null); onCourseFilter?.(null); }}><FolderClosed size={15} />All notes</button>
        {courses?.map(course => <button type="button" key={course.id} className={courseFilter === course.id && !activeFolder ? styles.folderActive : ''} onClick={() => { setActiveFolder(null); onCourseFilter?.(course.id); }}><FolderClosed size={15} /><span>{course.name}</span></button>)}
        {folders.map(folder => <button type="button" className={activeFolder === folder ? styles.folderActive : ''} key={`folder:${folder}`} onClick={() => setActiveFolder(folder)}><FolderClosed size={15} />{folder}{!notesCursor ? <small>{notes.filter(note => note.frontmatter?.note_folder === folder).length}</small> : null}</button>)}
      </div> : null}
      <div className={styles.noteFilters} role="radiogroup" aria-label="Show notes">
        {NOTE_FILTERS.map(filter => <button key={filter.id} type="button" role="radio" aria-checked={noteFilter === filter.id} onClick={() => setNoteFilter(filter.id)}>{filter.label}</button>)}
      </div>
      <div ref={noteItemsRef} className={styles.noteItems} aria-live="polite">
        {loading && notes.length === 0 ? <p className={styles.muted}>Loading notes…</p> : null}
        {!loading && notes.length === 0 ? <div className={styles.emptyList}><FileText size={18} /><span>{query ? 'No matching notes.' : 'No notes yet.'}</span></div> : null}
        {(() => {
          const visible = notes.filter(note => (!fullPage || !courseFilter || note.frontmatter.course_id === courseFilter) && (!activeFolder || note.frontmatter.note_folder === activeFolder) && matchesNoteFilter(note, noteFilter));
          const pinned = visible.filter(note => note.frontmatter.pinned === true);
          const rest = visible.filter(note => note.frontmatter.pinned !== true);
          const lessons = rest.filter(note => note.noteType === 'lesson');
          const mine = rest.filter(note => note.noteType !== 'lesson');
          const row = (note: typeof notes[number]) => (
            <div key={note.id} className={`${styles.noteRow} ${draft?.id === note.id ? styles.selected : ''}`}>
              <button type="button" className={styles.noteItem} onClick={() => void openNote(note.id)} aria-current={draft?.id === note.id ? 'page' : undefined} title={note.title}><span className={styles.noteTitle}><span aria-hidden="true">{note.noteType === 'lesson' ? <Sparkles size={15} /> : note.noteType === 'recording' ? <Mic size={15} /> : <FileText size={15} />}</span><strong>{noteDisplayTitle(note, notes)}</strong></span>{note.preview ? <span className={styles.noteExcerpt}>{note.preview}</span> : null}<small><span>{note.noteType === 'recording' ? 'Class · ' : ''}{relativeTime(note.updatedAt)}</span>{courseLabel(note) ? <span className={styles.noteCourse}>{courseLabel(note)}</span> : null}</small></button>
              <button type="button" className={styles.noteMenuButton} aria-label={`More options for ${note.title}`} aria-expanded={openMenu === note.id} onClick={() => setOpenMenu(openMenu === note.id ? null : note.id)}><MoreHorizontal size={17} /></button>
              {openMenu === note.id ? <div className={styles.noteMenu} role="menu"><button type="button" role="menuitem" onClick={() => togglePinned(note)}>{note.frontmatter.pinned === true ? 'Unpin' : 'Pin to top'}</button><span>Move to folder</span><button type="button" role="menuitem" onClick={() => void moveNote(note, null)}>No folder</button>{folders.map(folder => <button type="button" role="menuitem" key={folder} onClick={() => void moveNote(note, folder)}>{folder}</button>)}<button type="button" role="menuitem" className={styles.deleteAction} onClick={() => { setDeleting(note); setOpenMenu(null); }}>Delete note</button></div> : null}
            </div>
          );
          return <>
            {visible.length === 0 && notes.length > 0 ? <p className={styles.muted}>{noteFilter !== 'all' ? 'No notes of this kind yet.' : 'No notes in this folder yet.'}</p> : null}
            {pinned.length > 0 ? <h2 className={styles.groupLabel}><span className={styles.groupHeading}><Pin size={13} />Pinned</span><span className={styles.groupCount}>{pinned.length}</span></h2> : null}
            {pinned.map(row)}
            {mine.length > 0 ? <h2 className={styles.groupLabel}><span>Your notes</span><span className={styles.groupCount}>{mine.length}</span></h2> : null}
            {mine.map(row)}
            {lessons.length > 0 ? <h2 className={`${styles.groupLabel} ${styles.generatedGroup}`}><span className={styles.groupHeading}><Sparkles size={14} />Generated</span><span className={styles.groupCount}>{lessons.length}</span></h2> : null}
            {lessons.map(row)}
          </>;
        })()}
        {notesCursor ? <Button type="button" size="sm" variant="outline" disabled={loadingMoreNotes} onClick={() => void loadMoreNotes()}>{loadingMoreNotes ? 'Loading notes…' : 'Load more notes'}</Button> : null}
      </div>
    </div>
  );

  const words = draft ? noteWordCount(draft.body) : 0;
  const saveState = !draft ? '' : saving || (dirty && !error) ? 'Saving…' : error && dirty ? 'Not saved' : draft.id ? 'Saved' : 'Draft';
  const draftCourse = draft && typeof draft.frontmatter.course_id === 'string' ? draft.frontmatter.course_id : null;
  const draftSummary = draft?.id ? notes.find(note => note.id === draft.id) : undefined;
  const draftAsSummary = (): WorkspaceNoteSummary | null => draft?.id ? draftSummary || { id: draft.id, title: draft.title, preview: '', noteType: 'manual', frontmatter: draft.frontmatter, revision: draft.revision!, relativePath: '', updatedAt: new Date().toISOString() } : null;
  const pinnedNote = draft?.frontmatter.pinned === true;
  const canStudy = Boolean(draft?.id && draft.revision && !dirty);
  const sessionIds = draft && Array.isArray(draft.frontmatter.session_ids) ? (draft.frontmatter.session_ids as unknown[]).filter((id): id is string => typeof id === 'string') : [];
  const explanations = draft ? [...new Set(Array.from(draft.body.matchAll(/\[Original explanation\]\((\/s\/[A-Za-z0-9_%.-]+(?:#[A-Za-z0-9_%.-]+)?)\)/g), match => match[1]))] : [];
  const connections: NoteConnection[] = [
    ...(draftCourse && courseNames[draftCourse] ? [{ id: 'course', label: courseNames[draftCourse], detail: 'Course', icon: <FolderClosed size={15}/>, onSelect: () => { if (fullPage && onCourseFilter) onCourseFilter(draftCourse); else window.location.assign(`/courses/${encodeURIComponent(draftCourse)}`); } }] : []),
    ...sessionIds.slice(0, 3).map((id, index) => ({ id: `chat:${id}`, label: index ? `Conversation ${index + 1}` : 'Original conversation', detail: 'Chat', icon: <MessagesSquare size={15}/>, onSelect: () => openChatSession(id) })),
    ...explanations.slice(0, 4).map((href, index) => ({ id: `explanation:${href}`, label: `Original explanation ${index + 1}`, detail: 'Lesson', icon: <BookOpen size={15}/>, onSelect: () => window.location.assign(href) })),
  ];
  const related: NoteConnection[] = draftCourse ? notes.filter(note => note.id !== draft?.id && note.frontmatter.course_id === draftCourse).slice(0, 3).map(note => ({ id: note.id, label: noteDisplayTitle(note, notes), detail: relativeTime(note.updatedAt), icon: <FileText size={15}/>, onSelect: () => openNote(note.id) })) : [];
  const applyTemplate = (template: { title: string; body: string }) => {
    setDraft(current => current ? { ...current, title: current.title.trim() && current.title !== 'Untitled note' ? current.title : template.title, body: template.body } : current);
    setEditorEpoch(value => value + 1);
    window.setTimeout(() => richBody.current?.focus(), 0);
  };
  const pickImage = () => { const selection = window.getSelection(); imageSelection.current = selection?.rangeCount && richBody.current?.contains(selection.anchorNode) ? selection.getRangeAt(0).cloneRange() : null; imageInput.current?.click(); };
  const showVersions = () => { if (draft?.id) void learningApi.getWorkspaceNoteVersions(draft.id).then(result => setVersions(result.versions)).catch(cause => setError(String(cause))); };

  return <section className={`${styles.notes} ${fullPage ? styles.notesHome + " " + styles.unifiedNotes : ""} ${!fullPage && listHidden ? styles.listCollapsed : ""} ${idleList ? styles.idleList : ""}`} aria-label="Notes workspace" onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'p') { event.preventDefault(); setSwitcherOpen(true); } }}>
    {fullPage ? (listHost ? createPortal(noteList, listHost) : null) : noteList}
    <div className={`${styles.editor} ${draft?.frontmatter?.study_note === true ? styles.lessonEditor : ''}`} onPointerDown={() => { if (listOverlay) setListCollapsedPersisted(true); }}>
      {draft || listHidden ? <div className={styles.editorTop}>
        {listHidden ? <button type="button" className={styles.listToggle} title="Show note list" aria-label="Show note list" aria-expanded="false" onClick={() => setListCollapsedPersisted(false)}><PanelLeft size={15} /></button> : null}
        {draft && !fullPage ? <Button type="button" size="icon-sm" variant="ghost" aria-label="New note" title="New note" onClick={()=>{if(onOpenNote)window.dispatchEvent(new CustomEvent('openlearn:new-note-tab'));else startBlank();}}><Plus size={16}/></Button> : null}
        <span className={styles.editorSpacer} />
        {draft ? <span className={styles.saveState} data-state={saveState === 'Saved' ? 'saved' : saveState === 'Not saved' ? 'error' : 'pending'} role="status">{saveState === 'Saved' ? <Check size={14} aria-hidden="true"/> : null}{saveState}</span> : null}
        {draft&&unresolvedRecoveredDraft?<DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" className={styles.draftIndicator} aria-label="Unsaved local draft available" title="An unsaved draft of this note is on this device"><History size={16}/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-60"><p className="px-2 py-1.5 text-xs text-muted-foreground">An unsaved draft of this note is on this device.</p><DropdownMenuItem onSelect={()=>confirmBefore(()=>{setDraft(unresolvedRecoveredDraft);setSavedDraft(null);setRecoveredDraft(null);setError('');setEditorEpoch(value=>value+1);})}><History size={15}/>Restore local draft</DropdownMenuItem><DropdownMenuItem onSelect={()=>{setRecoveredDraft(null);if(recoveryOwner)localStorage.removeItem(`workspace-note-draft:${recoveryOwner}${recoveryKey?':'+recoveryKey:''}`);}}><X size={15}/>Discard local copy</DropdownMenuItem></DropdownMenuContent></DropdownMenu>:null}
        {draft ? <Button type="button" size="sm" variant="ghost" className={styles.askBuddy} onClick={discussNote} title="Discuss this note with Buddy"><Sparkles size={15} aria-hidden="true"/>Ask Buddy</Button> : null}
        {draft && fullPage ? <Button type="button" size="icon-sm" variant="ghost" aria-label="Record a class" title="Record a class" onClick={() => onRecordClass?.(activeFolder)}><Mic size={16} /></Button> : null}
        {draft ? <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" variant="ghost" aria-label="More note actions" title="More"><MoreHorizontal size={16}/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-56">
          <DropdownMenuItem onSelect={() => { setReading(false); setFindOpen(true); }}><Search size={15}/>Find in note</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setReading(value => !value)}><BookOpen size={15}/>{reading ? 'Edit note' : 'Reading mode'}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setSwitcherOpen(true)}><FileText size={15}/>Go to note…<DropdownMenuShortcut>Ctrl P</DropdownMenuShortcut></DropdownMenuItem>
          <DropdownMenuItem disabled={reading || imageBusy} onSelect={pickImage}><ImagePlus size={15}/>Insert image</DropdownMenuItem>
          {draft.id ? <>
            <DropdownMenuSeparator/>
            <DropdownMenuItem onSelect={() => togglePinned({ id: draft.id!, frontmatter: draft.frontmatter })}>{pinnedNote ? <PinOff size={15}/> : <Pin size={15}/>}{pinnedNote ? 'Unpin' : 'Pin to top'}</DropdownMenuItem>
            <DropdownMenuSub><DropdownMenuSubTrigger><FolderInput size={15}/>Move to</DropdownMenuSubTrigger><DropdownMenuSubContent className="max-h-72 w-52 overflow-auto">
              {Object.entries(courseNames).map(([id, name]) => <DropdownMenuItem key={id} onSelect={() => { const note = draftAsSummary(); if (note) void moveNote(note, null, id); }}>{draftCourse === id ? <Check size={15}/> : <FolderClosed size={15}/>}<span className="truncate">{name}</span></DropdownMenuItem>)}
              {Object.keys(courseNames).length ? <DropdownMenuSeparator/> : null}
              {folders.map(folder => <DropdownMenuItem key={folder} onSelect={() => { const note = draftAsSummary(); if (note) void moveNote(note, folder); }}><FolderClosed size={15}/><span className="truncate">{folder}</span></DropdownMenuItem>)}
              <DropdownMenuItem onSelect={() => { const note = draftAsSummary(); if (note) void moveNote(note, null); }}>No folder</DropdownMenuItem>
            </DropdownMenuSubContent></DropdownMenuSub>
            <DropdownMenuItem onSelect={showVersions}><History size={15}/>Version history</DropdownMenuItem>
            <DropdownMenuItem disabled={dirty || saving} onSelect={() => void undoLastSave()}><Undo2 size={15}/>Undo last save</DropdownMenuItem>
            <DropdownMenuItem onSelect={exportNote}><Download size={15}/>Export Markdown</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => { void navigator.clipboard?.writeText(draft.body).catch(() => undefined); }}><Copy size={15}/>Copy as Markdown</DropdownMenuItem>
            <DropdownMenuSeparator/>
            <DropdownMenuItem variant="destructive" onSelect={() => { const note = draftAsSummary(); if (note) setDeleting(note); }}><Trash2 size={15}/>Delete note</DropdownMenuItem>
          </> : null}
        </DropdownMenuContent></DropdownMenu> : null}
      </div> : null}
      {findOpen?<form className={styles.noteFind} onSubmit={event=>{event.preventDefault();findInNote();}}><Search size={14}/><input autoFocus aria-label="Find text in note" placeholder="Find in this note…" value={findText} onChange={event=>setFindText(event.target.value)} onKeyDown={event=>{if(event.key==='Escape')setFindOpen(false);}}/><button type="submit">Find</button><button type="button" aria-label="Close find" onClick={()=>setFindOpen(false)}><X size={14}/></button></form>:null}
      {versions ? <section aria-label="Note version history" className={styles.recovery}><strong>Version history</strong><Button size="sm" variant="ghost" onClick={()=>setVersions(null)}>Close history</Button>{versions.length ? versions.map(version=><button key={version.id} onClick={()=>confirmBefore(()=>{setDraft(current=>current?{...current,title:version.title,body:version.body}:current);setEditorEpoch(value=>value+1);setVersions(null);setError('Earlier version loaded as a draft. Save to restore it.');})}>Restore revision {version.noteRevision} · {new Date(version.savedAt).toLocaleString()}</button>):<p>No previous saved versions yet.</p>}</section> : null}
      {!draft ? (
        <div className={`ol-empty ${styles.quietEmpty}`}><FileText aria-hidden="true" />{notes.length ? <><h2>Pick up where you left off</h2><p>Choose a note from the list, or start a new one.</p></> : <><h2>Your notes</h2><p>Start writing, or save something from your conversation.</p></>}<div className="ol-page-actions"><Button size="sm" onClick={() => { setDraft(blankDraft()); setSavedDraft(null); setEditorEpoch(value=>value+1); }}><Plus size={15} />New note</Button></div></div>
      ) : <>
        {!reading ? <div className={styles.formatBar} data-note-toolbar role="toolbar" aria-label="Note formatting"><div className={styles.formatTools}>{noteTools.map(({ format, label, icon: Icon }) => <button key={format} type="button" title={label} aria-label={label} onMouseDown={event => event.preventDefault()} onClick={() => applyFormat(format)}><Icon size={16} /></button>)}<button type="button" aria-label="Attach image" title="Attach image" disabled={imageBusy} onMouseDown={event=>event.preventDefault()} onClick={pickImage}><ImagePlus size={16}/></button></div><span>{imageBusy?'Adding image…':<>Type <kbd>/</kbd> for blocks</>}</span></div> : null}
        <div className={styles.docScroll}>
          <header className={styles.docHead}>
            <input ref={titleInput} className={styles.docTitle} value={draft.title} onChange={event => setDraft(current => current ? { ...current, title: event.target.value } : current)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); richBody.current?.focus(); } }} aria-label="Note title" placeholder="Untitled" />
            <p className={styles.docMeta}>
              {draftCourse && courseNames[draftCourse] ? <span className={styles.docCourse}>{courseNames[draftCourse]}</span> : null}
              {draft.frontmatter.study_note === true ? <span>Lesson</span> : null}
              {pinnedNote ? <span className={styles.docPinned}><Pin size={12} aria-hidden="true"/>Pinned</span> : null}
              <span>{draftSummary ? `Edited ${relativeTime(draftSummary.updatedAt)}` : draft.id ? 'Saved' : 'New note'}</span>
              <span>{words} {words === 1 ? 'word' : 'words'}</span>
            </p>
          </header>
          <StudyNoteBar draft={draft} onChanged={(revision, frontmatter) => { const apply = (current: NoteDraft | null): NoteDraft | null => current && current.id ? { ...current, revision, frontmatter } : current; setDraft(apply); setSavedDraft(apply); }} />
          {(() => { const sid = sessionIds[0]; const noteId = draft.id; return noteId && draft.frontmatter?.study_note === true && typeof sid === 'string' ? <NoteProposalList sessionId={sid} refreshKey={0} onChanged={() => void loadNote(noteId)} /> : null; })()}
          {typeof draft.frontmatter?.class_recording_id === 'string' && draft.id ? <RecordingPlayer recordingId={draft.frontmatter.class_recording_id} noteId={draft.id} duration={typeof draft.frontmatter.class_recording_duration_ms === 'number' ? draft.frontmatter.class_recording_duration_ms : undefined} markersMs={Array.isArray(draft.frontmatter.class_recording_markers_ms) ? draft.frontmatter.class_recording_markers_ms as number[] : []} onReady={() => { if (draft.id) void loadNote(draft.id); }} /> : null}
          {typeof draft.frontmatter?.lecture_recording_id === 'string' && draft.id ? <LectureNotesView recordingId={draft.frontmatter.lecture_recording_id} /> : null}
          <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden multiple onChange={event=>{void insertImages(Array.from(event.target.files||[]));event.target.value='';}}/>
          <div ref={bodyWrap} className={styles.bodyWrap} onMouseUp={inspectSelection} onKeyUp={() => { inspectSelection(); updateSlash(); }} onKeyDown={editorKeyDown} onInput={updateSlash} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setSlash(null); }}>
            <div className={styles.writingSurface} hidden={reading}><RichNoteBody key={editorEpoch} initialBody={draft.body} editorRef={richBody} onImages={files=>void insertImages(files)} onChange={body => { setSelectedExcerpt(null); setDraft(current => current ? { ...current, body } : current); }} /></div>
            {reading?<article className={styles.notePreview}><ReactMarkdown urlTransform={url=>/^data:image\/(?:webp|png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(url)?url:defaultUrlTransform(url)} remarkPlugins={readingRemarkPlugins as never} rehypePlugins={readingRehypePlugins as never} skipHtml components={{ pre: NotePre }}>{draft.body}</ReactMarkdown></article>:null}
            {slash && !reading ? <SlashMenu commands={matchSlashCommands(slash.query)} index={slash.index} x={slash.x} y={slash.y} onHover={index => setSlash(current => current ? { ...current, index } : current)} onPick={runSlash}/> : null}
            {selectedExcerpt && !reading ? <div role="toolbar" aria-label="Selected passage" className={styles.selectionBar} style={{ left: selectedExcerpt.x, top: selectedExcerpt.y }} onMouseDown={event => event.preventDefault()} onKeyDown={event=>{if(event.key==='Escape')setSelectedExcerpt(null);}}>
              <button type="button" aria-label="Bold" title="Bold (Ctrl+B)" onClick={() => applyFormat('bold')}><Bold size={15}/></button>
              <button type="button" aria-label="Italic" title="Italic (Ctrl+I)" onClick={() => applyFormat('italic')}><Italic size={15}/></button>
              <button type="button" aria-label="Heading" title="Heading" onClick={() => applyFormat('heading')}><Heading2 size={15}/></button>
              <button type="button" aria-label="Link" title="Link" onClick={() => applyFormat('link')}><Link2 size={15}/></button>
              <span className={styles.selectionDivider} aria-hidden="true"/>
              <button type="button" onClick={()=>mentionExcerpt('Explain this')}><Sparkles size={14} aria-hidden="true"/>Explain</button>
              <button type="button" onClick={()=>mentionExcerpt('Make a visual that explains this')}><Wand2 size={14} aria-hidden="true"/>Visualize</button>
              <button type="button" onClick={()=>mentionExcerpt()}>Add to chat</button>
              <button type="button" aria-label="Ask in side chat" title="Ask in side chat" onClick={()=>{const start=selectedExcerpt.start;openSideChat({id:crypto.randomUUID(),title:draft.title,excerpt:selectedExcerpt.text,...(start>=0&&draft.id&&draft.revision?{note:{noteId:draft.id,expectedRevision:draft.revision,startOffset:start,endOffset:start+selectedExcerpt.text.length}}:{})});setSelectedExcerpt(null);}}><MessagesSquare size={15}/></button>
            </div> : null}
          </div>
          {!draft.id && !draft.body.trim() && !reading ? <NoteTemplatePicker onPick={applyTemplate}/> : null}
          {draft.id && draft.frontmatter?.study_note === true && typeof sessionIds[0] === 'string' ? <LessonPractice noteId={draft.id} sessionId={sessionIds[0]} noteTitle={draft.title} launch={quizToOpen?.lessonNoteId === draft.id ? quizToOpen : null} /> : null}
          {draft.id && draft.body.trim() ? <NoteConnections links={connections} related={related} actions={canStudy ? <>
            <Button type="button" size="sm" variant="outline" onClick={() => setPendingAsk('Quiz me on this note')}><ListChecks size={15}/>Quiz me</Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setPendingAsk('Make a visual that explains this note')}><Shapes size={15}/>Visualize</Button>
            <MakeFlashcards sessionId={sessionIds[0]} courseId={draftCourse || undefined} sourceRefs={[{kind:draft.frontmatter.study_note?'lesson':'note',id:draft.id,revision:draft.revision!}]} origin="learn"/>
          </> : <p className={styles.muted}>Saving… study tools appear once this note is saved.</p>}/> : null}
        </div>
      </>}
      {error ? <p role="alert" className={styles.error}>{error}{dirty ? <Button size="sm" variant="ghost" onClick={()=>void save()}>Retry save</Button> : <Button size="sm" variant="ghost" onClick={()=>{setError('');void loadNotes(query);}}>Dismiss</Button>}</p> : null}
      {listRefreshError ? <p role="status" className={styles.recovery}>{listRefreshError}<Button size="sm" variant="ghost" onClick={()=>void loadNotes(query, true)}>Refresh</Button></p> : null}
    </div>
    <NoteQuickSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} notes={notes} courseNames={courseNames} onOpen={id => void openNote(id)}/>
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
export function NotesWorkspace({ compact = false, onRecordClass, noteToOpen = null, onNoteOpenConsumed = () => undefined, ...sidebar }: Pick<NoteEditorProps, 'onRecordClass' | 'noteToOpen' | 'onNoteOpenConsumed' | 'listHost' | 'courses' | 'courseFilter' | 'onCourseFilter' | 'command' | 'onNoteSelected'> & { compact?: boolean }) {
  const [, setDirty] = useState(false);
  const [discussion, setDiscussion] = useState<TutorChatContext | null>(null);
  return <div className={styles.notesDestination}>
    <NoteEditor {...sidebar} closeRequest={false} onClose={() => undefined} onCloseRequestHandled={() => undefined} onDirtyChange={setDirty} seed={null} onSeedConsumed={() => undefined} noteToOpen={noteToOpen} onNoteOpenConsumed={onNoteOpenConsumed} fullPage={!compact} listWhenIdle={compact} onRecordClass={onRecordClass} onDiscuss={setDiscussion} />
    {discussion ? <CompactTutorChat key={discussion.id} context={discussion} onClose={() => { setDiscussion(null); document.querySelector<HTMLButtonElement>('[aria-label="Discuss this note"]')?.focus(); }} /> : null}
  </div>;
}

function WorkspaceNoteDocument({item,active,closeRequest,onClosed,onCloseHandled,onChanged,onDirty,onOpen,insertRequest,onInsertConsumed}: {item:{key:string;noteId:string|null;title:string};active:boolean;closeRequest:boolean;onClosed:()=>void;onCloseHandled:()=>void;onChanged:(key:string,id:string|null|undefined,title?:string)=>void;onDirty:(key:string,dirty:boolean)=>void;onOpen:(id:string)=>void;insertRequest:NoteInsert|null;onInsertConsumed:(id:string)=>void}) {
  const [handled,setHandled]=useState(false);
  const selected=useCallback((id:string|null)=>onChanged(item.key,id),[item.key,onChanged]);
  const title=useCallback((value:string)=>onChanged(item.key,undefined,value),[item.key,onChanged]);
  const dirty=useCallback((value:boolean)=>onDirty(item.key,value),[item.key,onDirty]);
  const consumed=useCallback(()=>setHandled(true),[]);
  return <div hidden={!active} className={styles.preservedTab}><NoteEditor recoveryKey={item.key} startEmpty={!item.noteId} closeRequest={closeRequest} onClose={onClosed} onCloseRequestHandled={onCloseHandled} onDirtyChange={dirty} seed={null} onSeedConsumed={()=>{}} noteToOpen={handled?null:item.noteId} onNoteOpenConsumed={consumed} onNoteSelected={selected} onTitleChange={title} onOpenNote={onOpen} insertRequest={insertRequest} onInsertConsumed={onInsertConsumed}/></div>;
}

/** The four study tools. Earlier layouts also had quiz, flashcards, sources and reminders tabs. */
const TOOLS: { id: WorkspaceTool; label: string; icon: typeof FileText }[] = [
  { id: 'notes', label: 'Notes', icon: FileText },
  { id: 'canvas', label: 'Canvas', icon: Shapes },
  { id: 'practice', label: 'Practice', icon: ListChecks },
  { id: 'class', label: 'Class', icon: AudioLines },
];

export function WorkspacePanel({ canvasValue, flashcardLaunch, classId, quizSessionId, quizConceptId, quizToOpen, layout, onLayoutChange, onCollapse, onExpand, noteSeed, noteToOpen, onNoteSeedConsumed, onNoteOpenConsumed }: {
  flashcardLaunch?:FlashcardView|null;
  classId?:string|null;
  canvasValue?: unknown;
  quizSessionId?: string | null;
  quizConceptId?: string;
  quizToOpen?: WorkspaceQuizOpen | null;
  layout: WorkspacePanelLayout;
  onLayoutChange: Dispatch<SetStateAction<WorkspacePanelLayout>>;
  onCollapse: () => void;
  onExpand: () => void;
  noteSeed: WorkspaceNoteSeed | null;
  noteToOpen: string | null;
  onNoteSeedConsumed: (id: string) => void;
  onNoteOpenConsumed: (noteId: string) => void;
}) {
  const [noteTitle,setNoteTitle]=useState('Notes');
  const [noteInsert,setNoteInsert]=useState<NoteInsert|null>(null);
  const insertConsumed=useCallback((id:string)=>setNoteInsert(current=>current?.id===id?null:current),[]);
  const [pickerQuery,setPickerQuery]=useState('');
  const [pickerNotes,setPickerNotes]=useState<WorkspaceNoteSummary[]>([]);
  const [notesDirty, setNotesDirty] = useState(false);
  const rememberNote=useCallback((id:string|null)=>onLayoutChange(current=>({...current,noteId:id})),[onLayoutChange]);
  const [closingNote,setClosingNote]=useState<string|null>(null);
  const [dirtyDocuments,setDirtyDocuments]=useState<Record<string,boolean>>({});
  const updateDocument=useCallback((key:string,id:string|null|undefined,title?:string)=>onLayoutChange(current=>({...current,noteTabs:current.noteTabs?.map(item=>item.key===key?{...item,...(id!==undefined?{noteId:id}:{}),...(title?{title}:{})}:item)})),[onLayoutChange]);
  const documentDirty=useCallback((key:string,value:boolean)=>setDirtyDocuments(current=>current[key]===value?current:{...current,[key]:value}),[]);
  const openDocument=useCallback((id:string)=>{
    onLayoutChange(current=>{const existing=current.noteTabs?.find(item=>item.noteId===id);const key=existing?.key||id;return {...current,collapsed:false,tabs:current.tabs.includes('notes')?current.tabs:[...current.tabs,'notes'],activeTab:'notes',activeNoteKey:key,noteTabs:existing?current.noteTabs:[...(current.noteTabs||[]),{key,noteId:id,title:'Loading note…'}]};});
  },[onLayoutChange]);
  const newNoteTab=useCallback(()=>{const key=crypto.randomUUID();onLayoutChange(current=>({...current,collapsed:false,tabs:current.tabs.includes('notes')?current.tabs:[...current.tabs,'notes'],activeTab:'notes',activeNoteKey:key,noteTabs:[...(current.noteTabs||[]),{key,noteId:null,title:'Untitled note'}]}));},[onLayoutChange]);
  useEffect(()=>{if(!noteToOpen)return;openDocument(noteToOpen);onNoteOpenConsumed(noteToOpen);},[noteToOpen,openDocument,onNoteOpenConsumed]);
  const closeDocument=(key:string)=>{onLayoutChange(current=>({...current,noteTabs:current.noteTabs?.filter(item=>item.key!==key),activeNoteKey:current.activeNoteKey===key?undefined:current.activeNoteKey}));setClosingNote(null);setDirtyDocuments(current=>{const next={...current};delete next[key];return next;});};
  const requestCloseDocument=(key:string)=>{if(dirtyDocuments[key]){onLayoutChange(current=>({...current,activeTab:'notes',activeNoteKey:key}));setClosingNote(key);}else closeDocument(key);};
  useEffect(()=>{window.dispatchEvent(new CustomEvent('openlearn:workspace-dirty',{detail:notesDirty||Object.values(dirtyDocuments).some(Boolean)}));return()=>{window.dispatchEvent(new CustomEvent('openlearn:workspace-dirty',{detail:false}));};},[notesDirty,dirtyDocuments]);
  useEffect(()=>{window.addEventListener('openlearn:new-note-tab',newNoteTab);return()=>window.removeEventListener('openlearn:new-note-tab',newNoteTab);},[newNoteTab]);

  // Tools stay mounted once opened so drafts and in-progress work survive switching.
  function openTab(tool: WorkspaceTool) {
    onLayoutChange(current => ({ ...current, collapsed: false, tabs: current.tabs.includes(tool) ? current.tabs : [...current.tabs, tool], activeTab: tool }));
    onExpand();
  }
  const setPracticeView = useCallback((view: PracticeView) => onLayoutChange(current => ({ ...current, practiceView: view })), [onLayoutChange]);
  const active = layout.activeTab;
  const moveTab = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next]?.focus(); tabs[next]?.click();
  };
  return <aside className={`${styles.panel} ${layout.collapsed ? styles.collapsed : ''} ${layout.focused ? styles.focused : ''}`} aria-label="Study panel">
    <header className={styles.header}>
      <div className={styles.toolSwitch} role="tablist" aria-label="Study tools" onKeyDown={moveTab}>
        {TOOLS.map(({ id, label, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={active === id} tabIndex={active === id ? 0 : -1} title={label} onClick={() => openTab(id)}><Icon size={15} aria-hidden="true"/><span>{label}</span></button>)}
      </div>
      <div className={styles.headerActions}>
        <Button type="button" size="icon-sm" variant="ghost" aria-label={layout.pinned ? 'Unpin panel' : 'Pin panel'} title={layout.pinned ? 'Pinned: new items from Buddy wait instead of replacing what is open' : 'Pin to keep what is open while Buddy works'} aria-pressed={!!layout.pinned} onClick={() => onLayoutChange(current => ({...current,pinned:!current.pinned}))}><Pin size={16}/></Button>
        <Button type="button" size="icon-sm" variant="ghost" aria-label={layout.focused ? 'Restore split view' : 'Expand panel'} title={layout.focused ? 'Back to split view' : 'Expand to full width'} onClick={() => onLayoutChange(current => ({...current,focused:!current.focused}))}>{layout.focused ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</Button>
        <Button type="button" size="icon-sm" variant="ghost" onClick={() => { onLayoutChange(current => ({ ...current, collapsed: true })); onCollapse(); }} aria-label="Close study panel" title="Close panel · your work stays open"><PanelRightClose size={16} /></Button>
      </div>
    </header>
    {active === 'notes' && layout.noteTabs?.length ? <div className={styles.docTabs}>
      <div className={styles.docTabStrip} role="tablist" aria-label="Open notes" onKeyDown={moveTab}>
        <div className={styles.tabItem} data-active={!layout.activeNoteKey}><button type="button" role="tab" aria-selected={!layout.activeNoteKey} onClick={() => onLayoutChange(current => ({ ...current, activeNoteKey: undefined }))}>{noteTitle}</button></div>
        {layout.noteTabs?.map(item => <div key={item.key} className={styles.tabItem} data-active={layout.activeNoteKey === item.key}><button type="button" role="tab" aria-selected={layout.activeNoteKey === item.key} onClick={() => onLayoutChange(current => ({ ...current, activeNoteKey: item.key }))}>{item.title}</button><button type="button" aria-label={`Close ${item.title}`} title="Close tab" onClick={() => requestCloseDocument(item.key)}><X size={12}/></button></div>)}
      </div>
      <DropdownMenu onOpenChange={open=>{if(open)void learningApi.listWorkspaceNotesPage().then(page=>setPickerNotes(page.notes)).catch(()=>{});}}><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Open a note in a new tab" title="Open a note in a new tab"><Plus size={16}/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-64">
        <DropdownMenuItem onSelect={newNoteTab}><Plus size={15}/>New note</DropdownMenuItem>
        <input aria-label="Find a note to open" placeholder="Find a note…" value={pickerQuery} onChange={event=>setPickerQuery(event.target.value)} onKeyDown={event=>event.stopPropagation()} className="mx-1 my-1.5 w-[calc(100%-0.5rem)] rounded-[8px] border border-input bg-card px-2 py-1.5 text-sm"/>
        {pickerNotes.filter(note=>note.title.toLowerCase().includes(pickerQuery.toLowerCase())).slice(0,8).map(note=><DropdownMenuItem key={note.id} onSelect={()=>openDocument(note.id)}><FileText size={15}/><span className="truncate">{note.title}</span></DropdownMenuItem>)}
      </DropdownMenuContent></DropdownMenu>
    </div> : null}
    <div className={styles.content}>
      {layout.tabs.includes('notes') ? <div hidden={active !== 'notes'||!!layout.activeNoteKey} className={styles.preservedTab}><NoteEditor insertRequest={layout.activeNoteKey ? null : noteInsert} onInsertConsumed={insertConsumed} listWhenIdle onOpenNote={openDocument} onNoteSelected={rememberNote} onTitleChange={setNoteTitle} closeRequest={false} onDirtyChange={setNotesDirty} seed={noteSeed} onSeedConsumed={onNoteSeedConsumed} noteToOpen={layout.noteId||null} onNoteOpenConsumed={()=>{}} onUseInChat={() => setWorkspacePanelCollapsed(true)} quizToOpen={quizToOpen} onCloseRequestHandled={() => undefined} onClose={() => undefined} /></div> : null}
      {layout.noteTabs?.map(item=><WorkspaceNoteDocument key={item.key} item={item} active={active==='notes'&&layout.activeNoteKey===item.key} closeRequest={closingNote===item.key} onClosed={()=>closeDocument(item.key)} onCloseHandled={()=>setClosingNote(null)} onChanged={updateDocument} onDirty={documentDirty} onOpen={openDocument} insertRequest={layout.activeNoteKey===item.key ? noteInsert : null} onInsertConsumed={insertConsumed}/>)}
      {layout.tabs.includes('practice') ? <div hidden={active !== 'practice'} className={styles.preservedTab}><PracticeTool sessionId={quizSessionId} conceptId={quizConceptId} view={layout.practiceView || 'home'} onView={setPracticeView} quizToOpen={quizToOpen} flashcardLaunch={flashcardLaunch}/></div> : null}
      {layout.tabs.includes('canvas') ? <div hidden={active!=='canvas'} className={styles.preservedTab}><div className={styles.toolPage}>
        <CanvasTool value={canvasValue} header={actions => <ToolHeader icon={Shapes} title="Canvas" description="Diagrams and interactive visuals from your conversation." action={actions}/>} onAddToNote={(markdown, title) => {
          // Notes stays mounted, so the open note (or a new one) receives the visual even before the switch.
          setNoteInsert({ id: crypto.randomUUID(), markdown, title });
          onLayoutChange(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('notes') ? current.tabs : [...current.tabs, 'notes'], activeTab: 'notes' }));
        }}/>
      </div></div> : null}
      {layout.tabs.includes('class') ? <div hidden={active!=='class'} className={`${styles.preservedTab} ${styles.classTool}`}><InClassWorkspace classId={classId||null}/></div> : null}
    </div>
  </aside>;
}
