"use client";
import { reportVoiceFocus } from "@/lib/voice/client";

import { memo, useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { createPortal } from 'react-dom';
import dynamic from 'next/dynamic';
import { Bold, BookOpen, CheckSquare2, Download, FileText, FolderClosed, FolderPlus, Heading2, ImagePlus, Italic, Link2, List, ListOrdered, Mic, MoreHorizontal, PanelLeft, PanelLeftClose, PanelRightClose, Plus, Quote, Search, Send, Sparkles, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { readingRemarkPlugins, readingRehypePlugins } from '@/lib/markdown-rendering';
import { normalizeMathMarkdown } from '@/lib/normalize-math-markdown';
import 'katex/dist/katex.min.css';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { ChevronDown, Maximize2, Minimize2, Pin } from 'lucide-react';
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
import { parseVisualArtifact as parseVisualization } from '@/lib/generated-visual';
import { WORKSPACE_NOTE_IMPROVE_EVENT, setWorkspacePanelCollapsed, openChatSession, requestWorkspaceQuiz } from '@/lib/workspace-events';
import { mentionWorkspaceNoteExcerpt, WORKSPACE_SOURCE_OPEN_EVENT, type WorkspaceNoteSeed } from '@/lib/workspace-events';
import { StudyNoteBar } from './study-note-bar';
import { NoteProposalList } from './study-note-panel';
import { NoteVisualReferences } from './visualization-reference';
import { richNoteToMarkdown } from '@/lib/rich-note-markdown';
import { prepareNoteImage } from '@/lib/note-images';
import { defaultUrlTransform } from 'react-markdown';
import { deleteClassRecording, getClassRecording, saveClassRecording } from '@/lib/class-recordings';
import type { NotesCommand } from './workspace-sidebar';
import { noteDisplayTitle } from '@/lib/note-list';
import type { TutorChatContext } from './compact-tutor-chat';
import { openSideChat } from '@/lib/workspace-side-chat-events';
import {PassageSelection} from './passage-selection';
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
const ReminderSidebar = dynamic(() => import('./reminder-sidebar').then(module => module.ReminderSidebar), { loading: WorkspaceFeatureLoading });
const Visualization = dynamic(() => import('./visualization').then(module => module.Visualization), { loading: WorkspaceFeatureLoading });
const LectureNotesView = dynamic(() => import('./lecture-notes-view').then(module => module.LectureNotesView), { loading: WorkspaceFeatureLoading });
const CompactTutorChat = dynamic(() => import('./compact-tutor-chat').then(module => module.CompactTutorChat), { loading: WorkspaceFeatureLoading });

export type WorkspaceTab = 'practice' | 'canvas' | 'notes' | 'quiz' | 'sources' | 'class' | 'flashcards' | 'reminders';
export type WorkspacePanelLayout = { width: number; collapsed: boolean; tabs: WorkspaceTab[]; activeTab: WorkspaceTab; focused?: boolean; pinned?: boolean; noteId?:string|null; noteTabs?: {key:string;noteId:string|null;title:string}[]; activeNoteKey?:string };
type NoteDraft = (Pick<WorkspaceNote, 'id' | 'title' | 'body' | 'revision' | 'frontmatter'>) | { id: null; title: string; body: string; revision: null; frontmatter: Record<string, unknown> };

const tabNames: Record<WorkspaceTab, string> = { practice: 'Practice', canvas: 'Canvas', notes: 'Notes', quiz: 'Quiz', sources: 'Sources',class:'In-Class',flashcards:'Flashcards',reminders:'Reminders' };
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

type SourceBlock = { id: string; versionId: string; pageIndex: number; kind: string; text: string };
type SourceMaterial = { id: string; title: string; versionId: string; status: string; role: string };

function SourcesPanel({ sourceToOpen }: { sourceToOpen?: { spanId: string; versionId?: string } | null }) {
  const [selectedSource, setSelectedSource] = useState('');
  const [materials, setMaterials] = useState<SourceMaterial[]>([]), [blocks, setBlocks] = useState<SourceBlock[]>([]), [active, setActive] = useState<SourceBlock | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try { setMaterials((await request<{ materials: SourceMaterial[] }>('/v1/materials')).materials); } catch (cause) { const friendly = friendlyServiceError(cause, 'Sources'); setError(`${friendly.message} ${friendly.detail}`); } finally { setLoading(false); } }, []);
  const openVersion = useCallback(async (versionId: string, spanId?: string) => { setSelectedSource(''); try {
    if (versionId.startsWith('quiz-context:')) {
      const source = await request<{ spanId: string; versionId: string; pageIndex: number; text: string }>(`/v1/quizzes/${encodeURIComponent(versionId.slice('quiz-context:'.length))}/study-context`);
      const block = { id: source.spanId, versionId: source.versionId, pageIndex: 0, kind: 'study_context', text: source.text };
      setBlocks([block]); setActive(block); setError(''); return;
    }
    const result = await request<{ blocks: SourceBlock[] }>(`/v1/material-versions/${encodeURIComponent(versionId)}/blocks`); setBlocks(result.blocks); setActive(spanId ? result.blocks.find(block => block.id === spanId) || result.blocks[0] || null : result.blocks[0] || null); setError(''); } catch (cause) { setError(cause instanceof Error ? cause.message : 'This material passage could not be opened.'); } }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { const receive = (event: Event) => { const detail = (event as CustomEvent<{ spanId: string; versionId?: string }>).detail; if (!detail?.spanId) return; if (detail.versionId || detail.spanId.startsWith('quiz-context:')) { void openVersion(detail.versionId || detail.spanId, detail.spanId); return; } void request<SourceBlock>(`/v1/source-spans/${encodeURIComponent(detail.spanId)}`).then(block => openVersion(block.versionId, block.id)).catch(cause => setError(cause instanceof Error ? cause.message : 'This cited passage is no longer available.')); }; window.addEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive); return () => window.removeEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive); }, [openVersion]);
  useEffect(() => { if (!sourceToOpen?.spanId) return; const timer = window.setTimeout(() => { if (sourceToOpen.versionId || sourceToOpen.spanId.startsWith('quiz-context:')) void openVersion(sourceToOpen.versionId || sourceToOpen.spanId, sourceToOpen.spanId); else void request<SourceBlock>(`/v1/source-spans/${encodeURIComponent(sourceToOpen.spanId)}`).then(block => openVersion(block.versionId, block.id)).catch(cause => setError(cause instanceof Error ? cause.message : 'This cited passage is no longer available.')); }, 0); return () => window.clearTimeout(timer); }, [openVersion, sourceToOpen]);
  return <section className={styles.sourcesPanel} aria-label="Sources workspace"><header><div><span>YOUR MATERIALS</span><h2>Sources</h2></div><Button size="sm" variant="ghost" onClick={() => void load()}>Refresh</Button></header><p className={styles.sourceNotice}>Attached passages and clearly labeled study context can support a quiz. Coverage can be limited.</p><div className={styles.sourceLayout}><div className={styles.sourceList}>{loading ? <p>Loading sources…</p> : materials.length ? materials.map(material => <button type="button" key={material.versionId} onClick={() => void openVersion(material.versionId)}><strong>{material.title}</strong><small>{material.status.replaceAll('_', ' ')} · {material.role.replaceAll('_', ' ')}</small></button>) : <p>No uploaded sources yet. Attach a text-based file in chat to inspect its passages here.</p>}</div><div className={styles.sourceDetail}>{active ? <><p className={styles.sourceMeta}>{active.kind === 'study_context' ? 'Study context · Not independently verified' : `Passage · Page ${active.pageIndex + 1}`}</p><pre tabIndex={0} onKeyUp={event => { const selection = window.getSelection(); setSelectedSource(selection && event.currentTarget.contains(selection.anchorNode) ? selection.toString().trim().slice(0, 6000) : ''); }} onMouseUp={event => { const selection = window.getSelection(); setSelectedSource(selection && event.currentTarget.contains(selection.anchorNode) ? selection.toString().trim().slice(0, 6000) : ''); }}>{active.text}</pre><div role="toolbar" aria-label="Source passage actions">{['Add to chat','Explain','Ask in side chat'].map(action=><Button key={action} size="sm" variant="ghost" onClick={()=>{const excerpt=selectedSource||active.text;const title=`Source · Page ${active.pageIndex+1}`;if(action==='Ask in side chat')openSideChat({id:active.id,title,excerpt});else window.dispatchEvent(new CustomEvent(WORKSPACE_PASSAGE_MENTION_EVENT,{detail:{title,excerpt,spanId:active.id,submit:action==='Explain'}}));}}>{action}</Button>)}</div><details><summary>Other passages</summary>{blocks.map(block => <button className={styles.passageButton} type="button" key={block.id} onClick={() => { setActive(block); setSelectedSource(''); }}>Page {block.pageIndex + 1} · {block.text.slice(0, 100)}</button>)}</details><p className={styles.sourceNotice}>This text is not independently verified.</p></> : blocks.length ? <div>{blocks.map(block => <button className={styles.passageButton} type="button" key={block.id} onClick={() => setActive(block)}>Page {block.pageIndex + 1} · {block.text.slice(0, 100)}…</button>)}</div> : <Empty className="h-full justify-center p-8"><EmptyHeader><EmptyMedia><BookOpen className="size-8 text-muted-foreground" /></EmptyMedia><EmptyTitle>Inspect support</EmptyTitle><EmptyDescription>Select a source or citation to see the exact passage behind it.</EmptyDescription></EmptyHeader></Empty>}</div></div>{error ? <p className={styles.error} role="alert">{error}</p> : null}</section>;
}

function PracticePanel({ sessionId, conceptId }: { sessionId?: string | null; conceptId?: string }) {
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [note, setNote] = useState<WorkspaceNote | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const [topic, setTopic] = useState('');
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
  return <div className="study-practice">
    <header className="study-practice-heading"><span>STUDY TOOLS</span><h2>Practice</h2><p>Choose your material, then focus the questions.</p></header>
    <section className="study-practice-setup" aria-label="Choose practice material">
      <label>Study from<select aria-label="Study from" value={selected} onChange={event => { setSelected(event.target.value); setTopic(''); }}><option value="">This conversation</option>{studyNotes.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      <label>Focus (optional)<input aria-label="Quiz topic" value={topic} onChange={event => setTopic(event.target.value)} placeholder="e.g. cellular respiration" /></label>
      <p className="study-practice-source">{note?.frontmatter.study_note ? `Questions will use ${note.title}.` : 'Questions will use the material in this conversation.'}</p>
      <div className="study-practice-actions"><Button size="sm" onClick={beginQuiz} disabled={starting}>{starting ? 'Opening quiz…' : 'Start quiz'}</Button><MakeFlashcards key={selected} sessionId={linkedSession || sessionId} sourceRefs={note ? [{kind: note.frontmatter.study_note ? 'lesson' : 'note', id: note.id, revision: note.revision}] : undefined} label="Make flashcards"/></div>
    </section>
    {note && linkedSession && note.frontmatter.study_note ? <LessonPractice key={note.id} noteId={note.id} sessionId={linkedSession} noteTitle={note.title}/> : null}
    {note && !note.frontmatter.study_note ? <Button size="sm" variant="outline" onClick={() => { const excerpt = note.body.slice(0, 6000); mentionWorkspaceNoteExcerpt({noteId: note.id, title: note.title, revision: note.revision, startOffset: 0, endOffset: excerpt.length, excerpt, prompt: 'Check my understanding of this note. Ask one question at a time and help me work through mistakes.'}); setWorkspacePanelCollapsed(true); }}>Check my understanding</Button> : null}
    <details className="study-practice-history"><summary>Recent quizzes</summary><QuizWorkspace sessionId={sourceSession || sessionId} conceptId={conceptId} compact/></details>
    {error ? <p role="alert">{error}</p> : null}
  </div>;
}

type NoteEditorProps = {
  closeRequest: boolean; onClose: () => void; onCloseRequestHandled: () => void; onDirtyChange: (dirty: boolean) => void;
  seed: WorkspaceNoteSeed | null; onSeedConsumed: (id: string) => void; noteToOpen: string | null; onNoteOpenConsumed: (noteId: string) => void;
  quizToOpen?: WorkspaceQuizOpen | null; fullPage?: boolean; onRecordClass?: (folder: string | null) => void; onUseInChat?: () => void;
  listHost?: HTMLElement | null; courses?: CourseSummary[]; courseFilter?: string | null; onCourseFilter?: (id: string | null) => void;
  listWhenIdle?: boolean; command?: NotesCommand | null; onNoteSelected?: (id: string | null) => void; onDiscuss?: (context: TutorChatContext) => void; onTitleChange?:(title:string)=>void; startEmpty?:boolean; recoveryKey?:string; onOpenNote?:(id:string)=>void;
};

function NoteEditor({ listWhenIdle = false, closeRequest, onClose, onCloseRequestHandled, onDirtyChange, seed, onSeedConsumed, noteToOpen, onNoteOpenConsumed, quizToOpen, fullPage = false, onRecordClass, listHost, courses, courseFilter = null, onCourseFilter, command, onNoteSelected, onDiscuss,onTitleChange, startEmpty=false, recoveryKey='', onOpenNote }: NoteEditorProps) {
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [courseNames, setCourseNames] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<NoteDraft | null>(startEmpty ? blankDraft : null);
  const [reading, setReading] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState('');
  const [imageBusy, setImageBusy] = useState(false);
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
      heading: ['formatBlock', 'h2'], bold: ['bold'], italic: ['italic'], bullet: ['insertUnorderedList'], numbered: ['insertOrderedList'], quote: ['formatBlock', 'blockquote'],
    };
    if (format === 'link') {
      const address = window.prompt('Link URL');
      if (address && /^https?:\/\//i.test(address)) document.execCommand('createLink', false, address);
    } else if (format === 'checklist') document.execCommand('insertHTML', false, '<ul><li><input type="checkbox" contenteditable="false" aria-label="Mark checklist item complete">&nbsp;</li></ul>');
    else if (commands[format]) document.execCommand(commands[format][0], false, commands[format][1]);
    if (richBody.current) setDraft(current => current ? { ...current, body: richNoteToMarkdown(richBody.current!) } : current);
  }

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
    if (!selection || !richBody.current?.contains(selection.anchorNode) || !text || text.length > 6000 || !draft?.id || !draft.revision || dirty) { setSelectedExcerpt(null); return; }
    const start = draft.body.indexOf(text);
    if (start < 0 || draft.body.indexOf(text, start + 1) >= 0) { setSelectedExcerpt(null); return; }
    const range = selection.getRangeAt(0).getBoundingClientRect();
    const wrap = bodyWrap.current?.getBoundingClientRect();
    if (!wrap) return;
    setSelectedExcerpt({ text, start, x: Math.max(8, Math.min(range.left - wrap.left, wrap.width - 310)), y: Math.max(8, range.top - wrap.top - 42) });
    reportVoiceFocus({quiz_id:null,presentation_id:null,lesson_id:null,visualization_id:null,note_id:draft.id,expected_revision:draft.revision,selection_start:start,selection_end:start+text.length,selected_text:null,source_span_id:null});
  }

  function mentionExcerpt(action = '') {
    if (!draft?.id || !draft.revision || !selectedExcerpt) return;
    const { text, start } = selectedExcerpt;
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
  const noteList = (
    <div className={styles.noteList}>
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
        {notesCursor ? <Button type="button" size="sm" variant="outline" disabled={loadingMoreNotes} onClick={() => void loadMoreNotes()}>{loadingMoreNotes ? 'Loading notes…' : 'Load more notes'}</Button> : null}
      </div>
    </div>
  );

  return <section className={`${styles.notes} ${fullPage ? styles.notesHome + " " + styles.unifiedNotes : ""} ${!fullPage && listHidden ? styles.listCollapsed : ""} ${idleList ? styles.idleList : ""}`} aria-label="Notes workspace">
    {fullPage ? (listHost ? createPortal(noteList, listHost) : null) : noteList}
    <div className={`${styles.editor} ${draft?.frontmatter?.study_note === true ? styles.lessonEditor : ''}`}>
      {draft || listHidden ? <div className={styles.editorTop}>
        {listHidden ? <button type="button" className={styles.listToggle} title="Show note list" aria-label="Show note list" aria-expanded="false" onClick={() => setListCollapsedPersisted(false)}><PanelLeft size={15} /></button> : null}
        {draft && !fullPage ? <Button type="button" size="icon-sm" variant="ghost" aria-label="New note" onClick={()=>{if(onOpenNote)window.dispatchEvent(new CustomEvent('openlearn:new-note-tab'));else startBlank();}}><Plus size={16}/></Button> : null}
        {draft ? <input ref={titleInput} value={draft.title} onChange={event => setDraft(current => current ? { ...current, title: event.target.value } : current)} aria-label="Note title" placeholder="Note title" /> : null}
        {draft?<><Button type="button" size="icon-xs" variant="ghost" aria-label="Find in note" onClick={()=>{setReading(false);setFindOpen(value=>!value);}}><Search size={16}/></Button><Button type="button" size="icon-xs" variant="ghost" aria-label={reading?'Edit note':'Reading mode'} aria-pressed={reading} onClick={()=>setReading(value=>!value)}><BookOpen size={16}/></Button></>:null}{draft?.id && !fullPage ? <DropdownMenu><DropdownMenuTrigger asChild><Button size="icon-xs" variant="ghost" aria-label="Note history and actions"><MoreHorizontal size={16}/></Button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem onSelect={()=>void learningApi.getWorkspaceNoteVersions(draft.id!).then(result=>setVersions(result.versions)).catch(cause=>setError(String(cause)))}>Version history</DropdownMenuItem><DropdownMenuItem disabled={dirty||saving} onSelect={()=>void undoLastSave()}>Undo last save</DropdownMenuItem><DropdownMenuItem onSelect={discussNote}>Discuss in side chat</DropdownMenuItem><DropdownMenuItem onSelect={exportNote}>Export Markdown</DropdownMenuItem></DropdownMenuContent></DropdownMenu> : null}
        {draft && fullPage ? <div className={styles.editorActions}>
          <Button type="button" size="icon-sm" variant="ghost" aria-label="Discuss this note" title="Discuss this note" onClick={discussNote}><Send size={16} /></Button>
          <Button type="button" size="icon-sm" variant="ghost" aria-label="Record a class" title="Record a class" onClick={() => onRecordClass?.(activeFolder)}><Mic size={16} /></Button>
          <button type="button" className={styles.editorMenuTrigger} aria-label="More note actions" aria-expanded={openMenu === 'editor'} onClick={() => setOpenMenu(openMenu === 'editor' ? null : 'editor')}><MoreHorizontal size={18} /></button>
          {openMenu === 'editor' ? <div className={styles.editorMenu} role="menu">
            <button type="button" role="menuitem" onClick={() => { setOpenMenu(null); titleInput.current?.focus(); titleInput.current?.select(); }}>Rename</button>
            <button type="button" role="menuitem" onClick={()=>{setOpenMenu(null);if(draft.id)void learningApi.getWorkspaceNoteVersions(draft.id).then(result=>setVersions(result.versions)).catch(cause=>setError(String(cause)));}}>Version history</button><button type="button" role="menuitem" onClick={exportNote}><Download size={15} />Export Markdown</button>
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
      {findOpen?<form className={styles.noteFind} onSubmit={event=>{event.preventDefault();findInNote();}}><Search size={14}/><input autoFocus aria-label="Find text in note" placeholder="Find in this note…" value={findText} onChange={event=>setFindText(event.target.value)}/><button type="submit">Find</button><button type="button" aria-label="Close find" onClick={()=>setFindOpen(false)}><X size={14}/></button></form>:null}{unresolvedRecoveredDraft ? <div className={styles.recovery} role="status"><span>Local draft available</span><Button size="sm" variant="ghost" onClick={()=>confirmBefore(()=>{setDraft(unresolvedRecoveredDraft);setSavedDraft(null);setRecoveredDraft(null);setError('');setEditorEpoch(value=>value+1);})}>Restore draft</Button><Button size="sm" variant="ghost" onClick={()=>{setRecoveredDraft(null);if(recoveryOwner)localStorage.removeItem(`workspace-note-draft:${recoveryOwner}${recoveryKey?':'+recoveryKey:''}`);}}>Discard local copy</Button></div> : null}
      {versions ? <section aria-label="Note version history" className={styles.recovery}><strong>Version history</strong><Button size="sm" variant="ghost" onClick={()=>setVersions(null)}>Close history</Button>{versions.length ? versions.map(version=><button key={version.id} onClick={()=>confirmBefore(()=>{setDraft(current=>current?{...current,title:version.title,body:version.body}:current);setEditorEpoch(value=>value+1);setVersions(null);setError('Earlier version loaded as a draft. Save to restore it.');})}>Restore revision {version.noteRevision} · {new Date(version.savedAt).toLocaleString()}</button>):<p>No previous saved versions yet.</p>}</section> : null}
      {!draft ? (
        <div className={`ol-empty ${styles.quietEmpty}`}><FileText aria-hidden="true" />{notes.length ? <><h2>Pick up where you left off</h2><p>Choose a note from the list, or start a new one.</p></> : <><h2>Your notes</h2><p>Start writing, or save something from your conversation.</p></>}<div className="ol-page-actions"><Button size="sm" onClick={() => { setDraft(blankDraft()); setSavedDraft(null); setEditorEpoch(value=>value+1); }}><Plus size={15} />New note</Button></div></div>
      ) : <>
        <StudyNoteBar draft={draft} onChanged={(revision, frontmatter) => { const apply = (current: NoteDraft | null): NoteDraft | null => current && current.id ? { ...current, revision, frontmatter } : current; setDraft(apply); setSavedDraft(apply); }} />
        {(() => { const sessionIds = Array.isArray(draft.frontmatter?.session_ids) ? draft.frontmatter.session_ids as string[] : []; const sid = sessionIds[0]; const noteId = draft.id; return noteId && draft.frontmatter?.study_note === true && typeof sid === 'string' ? <NoteProposalList sessionId={sid} refreshKey={0} onChanged={() => void loadNote(noteId)} /> : null; })()}
        {typeof draft.frontmatter?.class_recording_id === 'string' && draft.id ? <RecordingPlayer recordingId={draft.frontmatter.class_recording_id} noteId={draft.id} duration={typeof draft.frontmatter.class_recording_duration_ms === 'number' ? draft.frontmatter.class_recording_duration_ms : undefined} markersMs={Array.isArray(draft.frontmatter.class_recording_markers_ms) ? draft.frontmatter.class_recording_markers_ms as number[] : []} onReady={() => { if (draft.id) void loadNote(draft.id); }} /> : null}
        {typeof draft.frontmatter?.lecture_recording_id === 'string' && draft.id ? <LectureNotesView recordingId={draft.frontmatter.lecture_recording_id} /> : null}
        {!reading ? <div className={styles.formatBar} data-note-toolbar role="toolbar" aria-label="Note formatting"><div className={styles.formatTools}>{noteTools.map(({ format, label, icon: Icon }) => <button key={format} type="button" title={label} aria-label={label} onMouseDown={event => event.preventDefault()} onClick={() => applyFormat(format)}><Icon size={16} /></button>)}<button type="button" aria-label="Attach image" title="Attach image" disabled={imageBusy} onMouseDown={event=>event.preventDefault()} onClick={()=>{const selection=window.getSelection();imageSelection.current=selection?.rangeCount?selection.getRangeAt(0).cloneRange():null;imageInput.current?.click();}}><ImagePlus size={16}/></button></div><span>{imageBusy?'Adding image…':''}</span></div> : null}
        <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden multiple onChange={event=>{void insertImages(Array.from(event.target.files||[]));event.target.value='';}}/><div ref={bodyWrap} className={styles.bodyWrap} onMouseUp={inspectSelection} onKeyUp={inspectSelection}><div className={styles.writingSurface} hidden={reading}><RichNoteBody key={editorEpoch} initialBody={draft.body} editorRef={richBody} onImages={files=>void insertImages(files)} onChange={body => { setSelectedExcerpt(null); setDraft(current => current ? { ...current, body } : current); }} /></div>{reading?<article className={styles.notePreview}><ReactMarkdown urlTransform={url=>/^data:image\/(?:webp|png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(url)?url:defaultUrlTransform(url)} remarkPlugins={readingRemarkPlugins as never} rehypePlugins={readingRehypePlugins as never} skipHtml>{draft.body}</ReactMarkdown></article>:null}{selectedExcerpt && !reading ? <div role="toolbar" aria-label="Selected passage" className={styles.excerptFloat} style={{ left: selectedExcerpt.x, top: selectedExcerpt.y }} onMouseDown={event => event.preventDefault()} onKeyDown={event=>{if(event.key==='Escape')setSelectedExcerpt(null);}}><button type="button" onClick={()=>mentionExcerpt()}>Add to chat</button><button type="button" onClick={()=>mentionExcerpt('Explain this')}>Explain</button><button type="button" onClick={()=>{if(!draft.id||!draft.revision)return;openSideChat({id:crypto.randomUUID(),title:draft.title,excerpt:selectedExcerpt.text,note:{noteId:draft.id,expectedRevision:draft.revision,startOffset:selectedExcerpt.start,endOffset:selectedExcerpt.start+selectedExcerpt.text.length}});setSelectedExcerpt(null);}}>Ask in side chat</button></div> : null}</div>

        {Array.isArray(draft.frontmatter.session_ids) && typeof draft.frontmatter.session_ids[0] === 'string' ? <Button variant="ghost" size="sm" onClick={() => openChatSession((draft.frontmatter.session_ids as string[])[0])}>Back to original conversation</Button> : null}
        <div className="study-actions" aria-label="Original explanations">{[...new Set(Array.from(draft.body.matchAll(/\[Original explanation\]\((\/s\/[A-Za-z0-9_%.-]+(?:#[A-Za-z0-9_%.-]+)?)\)/g), match => match[1]))].map((href, index) => <a key={href} href={href}>Original explanation {index + 1}</a>)}</div>
        <NoteVisualReferences body={draft.body}/>
        {draft.id && draft.frontmatter?.study_note === true && Array.isArray(draft.frontmatter?.session_ids) && typeof draft.frontmatter.session_ids[0] === 'string' ? <LessonPractice noteId={draft.id} sessionId={draft.frontmatter.session_ids[0]} noteTitle={draft.title} launch={quizToOpen?.lessonNoteId === draft.id ? quizToOpen : null} /> : null}
        {draft.id && draft.revision && !dirty ? <details className={styles.studyMenu}><summary>Study this note</summary><button type="button" onClick={discussNote}>Ask Buddy about this note</button><button type="button" disabled={draft.body.length>6000} onClick={()=>mentionWorkspaceNoteExcerpt({noteId:draft.id!,title:draft.title,revision:draft.revision!,startOffset:0,endOffset:draft.body.length,excerpt:draft.body,prompt:'Quiz me on this note',submit:true})}>Quiz me</button><MakeFlashcards sessionId={Array.isArray(draft.frontmatter.session_ids)?draft.frontmatter.session_ids[0] as string:undefined} courseId={typeof draft.frontmatter.course_id==='string'?draft.frontmatter.course_id:undefined} sourceRefs={[{kind:draft.frontmatter.study_note?'lesson':'note',id:draft.id,revision:draft.revision}]} origin="learn"/></details> : null}
        <div className={styles.status} role="status"><span>{draft.body.replace(/!\[[^\]]*\]\(data:[^)]+\)/g,'').trim().split(/\s+/).filter(Boolean).length} words</span><span>{saving ? 'Saving…' : error && dirty ? 'Changes not saved' : dirty ? 'Saving changes…' : draft.id ? 'Saved' : 'Start typing to create this note'}</span></div>
      </>}
      {error ? <p role="alert" className={styles.error}>{error}{dirty ? <Button size="sm" variant="ghost" onClick={()=>void save()}>Retry save</Button> : <Button size="sm" variant="ghost" onClick={()=>void loadNotes(query)}>Retry</Button>}</p> : null}
      {listRefreshError ? <p role="status" className={styles.recovery}>{listRefreshError}<Button size="sm" variant="ghost" onClick={()=>void loadNotes(query, true)}>Refresh</Button></p> : null}
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
export function NotesWorkspace({ compact = false, onRecordClass, noteToOpen = null, onNoteOpenConsumed = () => undefined, ...sidebar }: Pick<NoteEditorProps, 'onRecordClass' | 'noteToOpen' | 'onNoteOpenConsumed' | 'listHost' | 'courses' | 'courseFilter' | 'onCourseFilter' | 'command' | 'onNoteSelected'> & { compact?: boolean }) {
  const [, setDirty] = useState(false);
  const [discussion, setDiscussion] = useState<TutorChatContext | null>(null);
  return <div className={styles.notesDestination}>
    <NoteEditor {...sidebar} closeRequest={false} onClose={() => undefined} onCloseRequestHandled={() => undefined} onDirtyChange={setDirty} seed={null} onSeedConsumed={() => undefined} noteToOpen={noteToOpen} onNoteOpenConsumed={onNoteOpenConsumed} fullPage={!compact} listWhenIdle={compact} onRecordClass={onRecordClass} onDiscuss={setDiscussion} />
    {discussion ? <CompactTutorChat key={discussion.id} context={discussion} onClose={() => { setDiscussion(null); document.querySelector<HTMLButtonElement>('[aria-label="Discuss this note"]')?.focus(); }} /> : null}
  </div>;
}

function WorkspaceNoteDocument({item,active,closeRequest,onClosed,onCloseHandled,onChanged,onDirty,onOpen}: {item:{key:string;noteId:string|null;title:string};active:boolean;closeRequest:boolean;onClosed:()=>void;onCloseHandled:()=>void;onChanged:(key:string,id:string|null|undefined,title?:string)=>void;onDirty:(key:string,dirty:boolean)=>void;onOpen:(id:string)=>void}) {
  const [handled,setHandled]=useState(false);
  const selected=useCallback((id:string|null)=>onChanged(item.key,id),[item.key,onChanged]);
  const title=useCallback((value:string)=>onChanged(item.key,undefined,value),[item.key,onChanged]);
  const dirty=useCallback((value:boolean)=>onDirty(item.key,value),[item.key,onDirty]);
  const consumed=useCallback(()=>setHandled(true),[]);
  return <div hidden={!active} className={styles.preservedTab}><NoteEditor recoveryKey={item.key} startEmpty={!item.noteId} closeRequest={closeRequest} onClose={onClosed} onCloseRequestHandled={onCloseHandled} onDirtyChange={dirty} seed={null} onSeedConsumed={()=>{}} noteToOpen={handled?null:item.noteId} onNoteOpenConsumed={consumed} onNoteSelected={selected} onTitleChange={title} onOpenNote={onOpen}/></div>;
}

export function WorkspacePanel({ canvasValue, flashcardLaunch, classId, quizSessionId, quizConceptId, quizToOpen, layout, onLayoutChange, onCollapse, onExpand, noteSeed, noteToOpen, sourceToOpen, onNoteSeedConsumed, onNoteOpenConsumed }: {
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
  sourceToOpen?: { spanId: string; versionId?: string } | null;
  onNoteSeedConsumed: (id: string) => void;
  onNoteOpenConsumed: (noteId: string) => void;
}) {
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [notesDirty, setNotesDirty] = useState(false);
  const [noteTitle,setNoteTitle]=useState('Notes');
  const [pickerQuery,setPickerQuery]=useState('');
  const [pickerNotes,setPickerNotes]=useState<WorkspaceNoteSummary[]>([]);
  const rememberNote=useCallback((id:string|null)=>onLayoutChange(current=>({...current,noteId:id})),[onLayoutChange]);
  const [noteCloseRequest, setNoteCloseRequest] = useState(false);
  const [closingNote,setClosingNote]=useState<string|null>(null);
  const [dirtyDocuments,setDirtyDocuments]=useState<Record<string,boolean>>({});
  const updateDocument=useCallback((key:string,id:string|null|undefined,title?:string)=>onLayoutChange(current=>({...current,noteTabs:current.noteTabs?.map(item=>item.key===key?{...item,...(id!==undefined?{noteId:id}:{}),...(title?{title}:{})}:item)})),[onLayoutChange]);
  const documentDirty=useCallback((key:string,value:boolean)=>setDirtyDocuments(current=>current[key]===value?current:{...current,[key]:value}),[]);
  const openDocument=useCallback((id:string)=>{
    onLayoutChange(current=>{const existing=current.noteTabs?.find(item=>item.noteId===id);const key=existing?.key||id;return {...current,collapsed:false,activeTab:'notes',activeNoteKey:key,noteTabs:existing?current.noteTabs:[...(current.noteTabs||[]),{key,noteId:id,title:'Loading note…'}]};});
  },[onLayoutChange]);
  useEffect(()=>{if(!noteToOpen)return;openDocument(noteToOpen);onNoteOpenConsumed(noteToOpen);},[noteToOpen,openDocument,onNoteOpenConsumed]);
  const closeDocument=(key:string)=>{onLayoutChange(current=>({...current,noteTabs:current.noteTabs?.filter(item=>item.key!==key),activeNoteKey:current.activeNoteKey===key?undefined:current.activeNoteKey}));setClosingNote(null);setDirtyDocuments(current=>{const next={...current};delete next[key];return next;});};
  const requestCloseDocument=(key:string)=>{if(dirtyDocuments[key]){onLayoutChange(current=>({...current,activeTab:'notes',activeNoteKey:key}));setClosingNote(key);}else closeDocument(key);};
  useEffect(()=>{window.dispatchEvent(new CustomEvent('openlearn:workspace-dirty',{detail:notesDirty||Object.values(dirtyDocuments).some(Boolean)}));return()=>{window.dispatchEvent(new CustomEvent('openlearn:workspace-dirty',{detail:false}));};},[notesDirty,dirtyDocuments]);

  function openTab(tab: WorkspaceTab) {
    onLayoutChange(current => ({ ...current, collapsed: false, tabs: current.tabs.includes(tab) ? current.tabs : [...current.tabs, tab], activeTab: tab, activeNoteKey:undefined }));
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

  useEffect(()=>{const create=()=>{const key=crypto.randomUUID();onLayoutChange(current=>({...current,collapsed:false,activeTab:'notes',activeNoteKey:key,noteTabs:[...(current.noteTabs||[]),{key,noteId:null,title:'Untitled note'}]}));};window.addEventListener('openlearn:new-note-tab',create);return()=>window.removeEventListener('openlearn:new-note-tab',create);},[onLayoutChange]);
  const active = layout.activeTab;
  // Tabs are added to layout.tabs by openTab and kept there until closed.
  // This lets dynamic chunks load on first use and remain mounted afterward,
  // without mirroring activeTab into React state from an effect.
  const shouldRenderTab = (tab: WorkspaceTab) => layout.tabs.includes(tab);
  return <aside className={`${styles.panel} ${layout.collapsed ? styles.collapsed : ''}`} aria-label="Workspace panel">
    <div className={styles.returnBar}><Button type="button" variant="ghost" size="sm" onClick={onCollapse}><PanelLeft size={15}/>Return to conversation</Button><span>Study workspace</span></div>
    <header className={styles.header}>
      <div className={styles.tabsHeader}>
        <div className={styles.tabStrip} role="tablist" aria-label="Open study items" onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const tabs=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));const index=tabs.indexOf(document.activeElement as HTMLButtonElement);if(index<0)return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next]?.focus();tabs[next]?.click();}}>{layout.tabs.map(tab=><div key={tab} className={styles.tabItem} data-active={active===tab&&(tab!=='notes'||!layout.activeNoteKey)}><button type="button" role="tab" aria-selected={active===tab&&(tab!=='notes'||!layout.activeNoteKey)} onClick={()=>openTab(tab)}>{tab==='notes'?noteTitle:tabNames[tab]}</button><button type="button" aria-label={`Close ${tabNames[tab]} tab`} onClick={()=>{if(tab==='notes'&&notesDirty){setNoteCloseRequest(true);return;}onLayoutChange(current=>{const tabs=current.tabs.filter(value=>value!==tab);return {...current,tabs,activeTab:current.activeTab===tab?(tabs[0]||'notes'):current.activeTab,collapsed:tabs.length===0&&!current.noteTabs?.length};});}}><X size={12}/></button></div>)}{layout.noteTabs?.map(item=><div key={item.key} className={styles.tabItem} data-active={active==='notes'&&layout.activeNoteKey===item.key}><button type="button" role="tab" aria-selected={active==='notes'&&layout.activeNoteKey===item.key} onClick={()=>onLayoutChange(current=>({...current,activeTab:'notes',activeNoteKey:item.key}))}>{item.title}</button><button type="button" aria-label={`Close ${item.title} tab`} onClick={()=>requestCloseDocument(item.key)}><X size={12}/></button></div>)}</div>
        <DropdownMenu onOpenChange={open=>{if(open)void learningApi.listWorkspaceNotesPage().then(page=>setPickerNotes(page.notes)).catch(()=>{});}}><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-xs" aria-label="Switch workspace item"><ChevronDown size={14}/></Button></DropdownMenuTrigger><DropdownMenuContent align="start">
          <input aria-label="Search workspace items" placeholder="Find a note…" value={pickerQuery} onChange={event=>setPickerQuery(event.target.value)} onKeyDown={event=>event.stopPropagation()} className="m-1 rounded border bg-background px-2 py-2 text-sm"/>{pickerNotes.filter(note=>note.title.toLowerCase().includes(pickerQuery.toLowerCase())).slice(0,8).map(note=><DropdownMenuItem key={note.id} onSelect={()=>{openDocument(note.id);}}>{note.title}</DropdownMenuItem>)}{(['notes','sources','practice','reminders','canvas','flashcards','class'] as WorkspaceTab[]).map(tab => <DropdownMenuItem key={tab} onSelect={() => openTab(tab)}>{tabNames[tab]}{active === tab ? ' · Open' : ''}</DropdownMenuItem>)}
        </DropdownMenuContent></DropdownMenu>
        <div className={styles.launcher}>
          <Button type="button" size="icon-xs" variant="ghost" onClick={() => setLauncherOpen(open => !open)} aria-expanded={launcherOpen} aria-label="Open a workspace tab" title="Add workspace tab">
            <Plus size={15} />
          </Button>
          {launcherOpen ? (
            <div className={styles.launcherMenu}><button type="button" onClick={()=>{const key=crypto.randomUUID();onLayoutChange(current=>({...current,activeTab:'notes',activeNoteKey:key,noteTabs:[...(current.noteTabs||[]),{key,noteId:null,title:'Untitled note'}]}));setLauncherOpen(false);}}>New note</button>
              {(['notes', 'class', 'sources', 'practice', 'canvas', 'flashcards', 'reminders'] as WorkspaceTab[]).map(tab => (
                <button type="button" key={tab} onClick={() => openTab(tab)}>{tabNames[tab]}</button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className={styles.headerActions}>
        <Button type="button" size="icon-xs" variant="ghost" aria-label={layout.pinned ? 'Unpin workspace' : 'Pin workspace'} aria-pressed={!!layout.pinned} onClick={() => onLayoutChange(current => ({...current,pinned:!current.pinned}))}><Pin size={15}/></Button>
        <Button type="button" size="icon-xs" variant="ghost" aria-label={layout.focused ? 'Restore split view' : 'Focus on workspace'} onClick={() => onLayoutChange(current => ({...current,focused:!current.focused}))}>{layout.focused ? <Minimize2 size={15}/> : <Maximize2 size={15}/>}</Button>
        {layout.tabs.length > 1 && !['notes', 'sources', 'practice', 'reminders'].includes(active) ? (
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
      {layout.tabs.includes('notes') ? <div hidden={active !== 'notes'||!!layout.activeNoteKey} className={styles.preservedTab}><NoteEditor onOpenNote={openDocument} onNoteSelected={rememberNote} onTitleChange={setNoteTitle} closeRequest={noteCloseRequest} onDirtyChange={setNotesDirty} seed={noteSeed} onSeedConsumed={onNoteSeedConsumed} noteToOpen={layout.noteId||null} onNoteOpenConsumed={()=>{}} onUseInChat={() => setWorkspacePanelCollapsed(true)} quizToOpen={quizToOpen} onCloseRequestHandled={() => setNoteCloseRequest(false)} onClose={() => { setNoteCloseRequest(false);onLayoutChange(current=>{const tabs=current.tabs.filter(tab=>tab!=='notes');return {...current,tabs,activeTab:current.activeTab==='notes'?(tabs[0]||'notes'):current.activeTab};}); }} /></div> : null}
      {layout.noteTabs?.map(item=><WorkspaceNoteDocument key={item.key} item={item} active={active==='notes'&&layout.activeNoteKey===item.key} closeRequest={closingNote===item.key} onClosed={()=>closeDocument(item.key)} onCloseHandled={()=>setClosingNote(null)} onChanged={updateDocument} onDirty={documentDirty} onOpen={openDocument}/>)}
      {layout.tabs.includes('quiz') && shouldRenderTab('quiz') ? <div hidden={active !== 'quiz'} className={styles.preservedTab}><QuizWorkspace sessionId={quizToOpen?.sessionId || quizSessionId} conceptId={quizToOpen?.conceptId || quizConceptId} compact launch={quizToOpen?.origin === 'ask' ? quizToOpen : null} quizId={quizToOpen?.quizId} /></div> : null}
      {layout.tabs.includes('practice') ? <div hidden={active !== 'practice'} className={styles.preservedTab}><PracticePanel sessionId={quizSessionId} conceptId={quizConceptId}/></div> : null}
      {layout.tabs.includes('canvas') && shouldRenderTab('canvas') ? <div hidden={active!=='canvas'} className={styles.preservedTab}><h2>Canvas</h2>{parseVisualization(canvasValue) ? <PassageSelection title="Diagram" itemContext={JSON.stringify(canvasValue)}><Visualization value={canvasValue} lessonId={parseVisualization(canvasValue)?.sourceLessonId}/></PassageSelection> : <p>Open a diagram or interactive visual from an explanation to keep it beside your conversation.</p>}</div> : null}
      {layout.tabs.includes('sources') ? <div hidden={active !== 'sources'} className={styles.preservedTab}><SourcesPanel sourceToOpen={sourceToOpen} /></div> : null}
      {layout.tabs.includes('reminders') && shouldRenderTab('reminders') ? <div hidden={active !== 'reminders'} className={styles.preservedTab}><ReminderSidebar /></div> : null}
      {layout.tabs.includes('flashcards') && shouldRenderTab('flashcards') ? <div hidden={active!=='flashcards'} className={styles.preservedTab}><FlashcardWorkspace launch={flashcardLaunch}/></div> : null}
      {layout.tabs.includes('class') && shouldRenderTab('class') ? <div hidden={active!=='class'} className={styles.preservedTab}><InClassWorkspace classId={classId||null}/></div> : null}
    </div>
  </aside>;
}
