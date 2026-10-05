"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowUp, Check, ChevronDown, CircleHelp, FileText, GraduationCap, MessageCircle, MessageCircleQuestion, Plus, Square, X, Upload, type LucideIcon } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import styles from './learn-chat.module.css';
import { learningApi, type Gear, type WorkspaceNoteSummary } from '@/lib/api';
import type { ChatMode } from '@/lib/learning-workflows';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';

export type ChatModeOption = {
  value: ChatMode; label: string; description: string; icon: LucideIcon;
  /** Restrained accent drawn from the existing sage/earth palette. */
  accent: string; tileBg: string;
};

/** Add future modes (e.g. Agent) here — the selector renders them with no other changes. */
export const CHAT_MODES: ChatModeOption[] = [
  { value: 'ask', label: 'Ask', description: 'Get developed answers with explanations and sources', icon: MessageCircleQuestion, accent: '#5f705c', tileBg: '#e6ece1' },
  { value: 'learn', label: 'Learn', description: 'Learn a topic interactively, step by step', icon: GraduationCap, accent: '#77663f', tileBg: '#efe9d8' },
  { value: 'quiz', label: 'Quiz', description: 'Practice active recall and test your understanding', icon: CircleHelp, accent: '#536d7a', tileBg: '#e6edf2' },
];

export function ChatModeSelector({ mode, onModeChange, disabled, conversation, onConversation, onInClass }: {
  mode: ChatMode; onModeChange?: (mode: ChatMode) => void; disabled?: boolean;
  conversation?:boolean; onConversation?:()=>void; onInClass?:()=>void;
}) {
  const current = CHAT_MODES.find(option => option.value === mode) ?? CHAT_MODES[0];
  const isConversation = mode === 'ask' && conversation;
  const CurrentIcon = isConversation ? MessageCircle : current.icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label="Conversation mode"
          title={isConversation ? 'Conversation · Your everyday study partner' : `${current.label} · ${current.description}`}
          className={styles.modeTrigger}
        >
          <span className={styles.modeTile} style={{ background: current.tileBg, color: current.accent }}>
            <CurrentIcon size={14} />
          </span>
          {mode==='ask'&&conversation?'Conversation':current.label}
          <ChevronDown size={14} className={styles.modeChevron} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" sideOffset={6} className="w-[280px] p-1.5">
        {onConversation?<DropdownMenuItem onSelect={onConversation} className="items-start gap-2.5 rounded-lg px-2.5 py-2 cursor-pointer"><span className={styles.modeTile}><MessageCircle size={15}/></span><span className="grid flex-1 gap-0.5"><span className="flex items-center gap-1.5 text-[13px] font-semibold">Conversation{isConversation?<Check size={13}/>:null}</span><span className="text-xs leading-snug text-muted-foreground">Talk, plan your day, and prepare together</span></span></DropdownMenuItem>:null}
        {CHAT_MODES.map(option => {
          const OptionIcon = option.icon;
          const selected = option.value === mode && !(mode==='ask'&&conversation);
          return (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => onModeChange?.(option.value)}
              className="items-start gap-2.5 rounded-lg px-2.5 py-2 cursor-pointer"
            >
              <span className={styles.modeTile} style={{ background: option.tileBg, color: option.accent }}>
                <OptionIcon size={15} />
              </span>
              <span className="grid flex-1 gap-0.5">
                <span className="flex items-center gap-1.5 text-[13px] font-semibold leading-none text-foreground">
                  {option.label}
                  {selected ? <Check size={13} style={{ color: option.accent }} /> : null}
                </span>
                <span className="text-xs leading-snug text-muted-foreground">{option.description}</span>
              </span>
            </DropdownMenuItem>
          );
        })}
        {onInClass?<DropdownMenuItem onSelect={onInClass} className="mt-1 border-t border-border pt-2">In-Class · Set up class recording</DropdownMenuItem>:null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export type ChatAttachment = { id: string; name: string; file: File; versionId?: string; materialId?: string; uploadPath?: string; resumableUploadPath?: string; uploadSessionUrl?: string; uploadComplete?: boolean };
export type ChatNoteMention = { noteId: string; title: string; revision: number; startOffset: number; endOffset: number; excerpt: string };

export function ChatComposer({ value, onChange, attachments, onAttachmentsChange, onSubmit, onCancel, busy, followup, gear, onGearChange, mode = 'ask', onModeChange, noteMentions = [], onAddNoteMention, onRemoveNoteMention, onOpenNoteMention, variant = 'main', conversation, onConversation, onInClass, contextConcept, onRemoveContext, unavailable, onRetry, onVoice }: {
  value: string; onChange: (value: string) => void; attachments: ChatAttachment[];
  onAttachmentsChange: (items: ChatAttachment[]) => void; onSubmit: () => void; onCancel?: () => void; busy: boolean; followup: boolean; gear: Gear; onGearChange: (gear: Gear) => void;
  mode?: ChatMode; onModeChange?: (mode: ChatMode) => void; conversation?:boolean; onConversation?:()=>void; onInClass?:()=>void;
  noteMentions?: ChatNoteMention[]; onAddNoteMention?: (note: WorkspaceNoteSummary) => void; onRemoveNoteMention?: (noteId: string) => void; onOpenNoteMention?: (noteId: string) => void;
  unavailable?: string; onRetry?: () => void;
  onVoice?: () => void;
  variant?: 'main' | 'compact'; contextConcept?: { id: string; title: string } | null; onRemoveContext?: () => void;
}) {
  const reduceMotion = useAppReducedMotion();
  const input = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [noteMatches, setNoteMatches] = useState<WorkspaceNoteSummary[]>([]);
  const mentionMatch = value.match(/(?:^|\s)@([^\s@]*)$/);
  const noteQuery = mentionMatch?.[1] ?? null;
  useEffect(() => {
    if (noteQuery === null || !onAddNoteMention) return;
    const timer = window.setTimeout(() => {
      void learningApi.searchWorkspaceNotes(noteQuery).then(result => setNoteMatches(result.notes.filter(note => !noteMentions.some(item => item.noteId === note.id)).slice(0, 6))).catch(() => setNoteMatches([]));
    }, 120);
    return () => window.clearTimeout(timer);
  }, [noteQuery, noteMentions, onAddNoteMention]);
  function add(files: File[]) {
    const accepted: ChatAttachment[] = [];
    const rejected: string[] = [];
    for (const file of files) {
      const image = /\.(png|jpe?g|webp|gif)$/i.test(file.name);
      if (!/\.(pdf|txt|md|png|jpe?g|webp|gif)$/i.test(file.name) || !file.size || file.size > (image ? 50 : 250) * 1024 * 1024) { rejected.push(file.name); continue; }
      if (!attachments.some(item => item.name === file.name && item.file.size === file.size) && !accepted.some(item => item.name === file.name && item.file.size === file.size)) accepted.push({ id: crypto.randomUUID(), name: file.name, file });
    }
    onAttachmentsChange([...attachments, ...accepted]);
      setError(rejected.length ? `Couldn't attach ${rejected.join(', ')}. Use PDF, TXT, or Markdown files up to 500 MiB, or images up to 50 MiB.` : '');
  }
  const hasLink = /https?:\/\/\S+/i.test(value);
  const resizeTextarea = useCallback(() => {
    const element = textarea.current;
    if (!element) return;
    const mobile = window.innerWidth <= 1023;
    const maxHeight = mobile ? 112 : 196;
    element.style.height = '0px';
    const height = Math.min(Math.max(element.scrollHeight, mobile ? 28 : 44), maxHeight);
    element.style.height = `${height}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, []);
  useLayoutEffect(() => { resizeTextarea(); }, [resizeTextarea, value]);
  useEffect(() => {
    window.addEventListener('resize', resizeTextarea);
    return () => window.removeEventListener('resize', resizeTextarea);
  }, [resizeTextarea]);

  return <><div className={styles.connectionStrip}>{unavailable ? <p className={styles.connectionNotice} role="status"><span>{unavailable}</span>{onRetry ? <button type="button" aria-label="Retry connection" onClick={onRetry}>Retry</button> : null}</p> : null}</div><form className={`${followup ? styles.followupComposer : styles.composer} ${styles.chatComposer} ${variant === 'compact' ? styles.compactComposer : ''} ${dragging ? styles.dragging : ''}`}
    onSubmit={event => { event.preventDefault(); if (!busy && !unavailable) onSubmit(); }}
    onDragEnter={event => { if (!busy && event.dataTransfer.types.includes('Files')) { event.preventDefault(); dragDepth.current++; setDragging(true); } }}
    onDragOver={event => { if (event.dataTransfer.types.some(type => ['Files', 'text/uri-list'].includes(type))) { event.preventDefault(); event.dataTransfer.dropEffect = busy ? 'none' : 'copy'; } }}
    onDragLeave={event => { event.preventDefault(); if (--dragDepth.current <= 0) { dragDepth.current = 0; setDragging(false); } }}
    onDrop={event => { if (event.dataTransfer.files.length) { event.preventDefault(); if (!busy) add(Array.from(event.dataTransfer.files)); } else { const link = event.dataTransfer.getData('text/uri-list').split('\n').find(line => /^https?:\/\//i.test(line)); if (link) { event.preventDefault(); if (!busy) onChange(`${value}${value ? '\n' : ''}${link}`.slice(0, 4000)); } } dragDepth.current = 0; setDragging(false); }}>
    <AnimatePresence>{dragging && <motion.div className={styles.dropOverlay} initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={reduceMotion ? undefined : { opacity: 0 }}><Upload size={26} /><strong>Drop your files here</strong><span>Books, notes, and anything you’re learning from</span></motion.div>}</AnimatePresence>
    {attachments.length > 0 && <div className={styles.attachments} aria-label="Chat attachments"><AnimatePresence initial={false}>{attachments.map(item => <motion.div className={styles.attachment} key={item.id} layout={!reduceMotion} initial={reduceMotion ? false : { opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={reduceMotion ? undefined : { opacity: 0, scale: 0.96 }} transition={{ duration: 0.16 }}><FileText size={21} /><div><strong title={item.name}>{item.name}</strong><span>{item.versionId ? 'In this conversation' : `${item.name.split('.').at(-1)?.toUpperCase()} · ${(item.file.size / 1024 / 1024).toFixed(1)} MB`}</span></div><button type="button" disabled={busy} aria-label={`Remove ${item.name} from this conversation`} onClick={() => onAttachmentsChange(attachments.filter(other => other.id !== item.id))}><X size={14} /></button></motion.div>)}</AnimatePresence></div>}
    {contextConcept ? <div className={styles.contextRow}><span>Asking about: {contextConcept.title}<button type="button" aria-label={`Remove ${contextConcept.title} context`} onClick={onRemoveContext}><X size={13}/></button></span></div> : null}
    {noteMentions.length > 0 ? <div className={styles.noteReceipt} aria-label="Learner note context"><AnimatePresence initial={false}>{noteMentions.map(note => <motion.span key={note.noteId} layout={!reduceMotion} initial={reduceMotion ? false : { opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={reduceMotion ? undefined : { opacity: 0, scale: 0.96 }} transition={{ duration: 0.16 }}><button type="button" onClick={() => onOpenNoteMention?.(note.noteId)} title="Open note in workspace">@{note.title}</button><details><summary>{note.endOffset - note.startOffset} characters</summary><pre>{note.excerpt}</pre></details><button type="button" aria-label={`Remove ${note.title} from context`} onClick={() => onRemoveNoteMention?.(note.noteId)}><X size={12} /></button></motion.span>)}</AnimatePresence><p>Learner-provided context only. It is not a verified source.</p></div> : null}
    <label htmlFor="chat-message" className="sr-only">Message your tutor</label>
    <button type="button" className={styles.mobileOptionsButton} aria-label="Chat options and attachments" onClick={() => setOptionsOpen(true)} disabled={busy}><Plus size={22}/></button>
    {mode !== 'ask' || gear !== 'Quick' ? <button type="button" className={styles.mobileModeBadge} onClick={() => setOptionsOpen(true)}>{CHAT_MODES.find(option => option.value === mode)?.label} · {gear}</button> : null}
    <textarea ref={textarea} id="chat-message" value={value} maxLength={4000}
      placeholder={
        mode === 'quiz'
          ? (followup ? 'Answer the question, or ask for a hint…' : 'Quiz a topic, or ask for practice questions…')
          : mode === 'learn'
          ? (followup ? 'Ask a follow-up about this lesson…' : 'What would you like to learn today?')
          : (followup ? 'Ask a follow-up…' : 'Ask anything, or drop in a book…')
      }
      rows={1} onChange={event => onChange(event.target.value)}
      onPaste={event => { if (event.clipboardData.files.length) { event.preventDefault(); add(Array.from(event.clipboardData.files)); } }}
      onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !busy && !unavailable) { event.preventDefault(); onSubmit(); } }} />
    {noteQuery !== null && noteMatches.length > 0 ? <div className={styles.notePicker} role="listbox" aria-label="Notes to mention">{noteMatches.map(note => <button type="button" role="option" aria-selected="false" key={note.id} onClick={() => { onChange(value.replace(/@[^\s@]*$/, `@${note.title} `)); onAddNoteMention?.(note); setNoteMatches([]); }}><strong>{note.title}</strong><small>Revision {note.revision}</small></button>)}</div> : null}
    <input ref={input} type="file" hidden multiple accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.gif" onChange={event => { add(Array.from(event.target.files || [])); event.target.value = ''; }} />
    <div className={styles.composerBottom}><div className={styles.composerTools}><Button type="button" variant="ghost" size="icon" disabled={busy} aria-label={attachments.length ? `Attach files (${attachments.length} attached)` : 'Attach files'} title="Attach PDF, text, Markdown, or images" onClick={() => input.current?.click()} className={styles.attachButton}><Plus size={19} />{attachments.length > 0 ? <span className={styles.attachCount}>{attachments.length}</span> : null}</Button><ChatModeSelector onInClass={onInClass} conversation={conversation} onConversation={onConversation} mode={mode} onModeChange={onModeChange} disabled={busy} /><Select value={gear} onValueChange={value => onGearChange(value as Gear)} disabled={busy}><SelectTrigger size="sm" aria-label="Explanation depth" title="Explanation depth" className={styles.gearSelect}><span>Explain</span><SelectValue /></SelectTrigger><SelectContent align="start">{(['Quick', 'Guided', 'Deep'] as Gear[]).map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select></div><div className="flex items-center gap-2">{onCancel ? <Button size="icon" type="button" variant="outline" onClick={onCancel} aria-label="Stop generating" title="Stop generating"><Square size={16} fill="currentColor" /></Button> : <Button size="icon" type="submit" disabled={busy || Boolean(unavailable) || (!value.trim() && !attachments.length)} aria-label="Send message" title="Send message"><ArrowUp size={20} /></Button>}</div></div>
    {hasLink && <p className={styles.composerNote}>Public links are imported as readable source material when you send.</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </form><Sheet open={optionsOpen} onOpenChange={setOptionsOpen}><SheetContent side="bottom" className={styles.mobileOptionsSheet}><SheetHeader><SheetTitle>Chat options</SheetTitle><SheetDescription>Choose how your Buddy helps, or attach material.</SheetDescription></SheetHeader><div className={styles.mobileOptionsContent}><Button variant="outline" disabled={busy} onClick={() => { setOptionsOpen(false); input.current?.click(); }}><Plus size={18}/>Attach a file or image</Button><div><span>Conversation mode</span><ChatModeSelector conversation={conversation} onConversation={() => { onConversation?.(); setOptionsOpen(false); }} mode={mode} onModeChange={next => { onModeChange?.(next); setOptionsOpen(false); }} disabled={busy}/></div><div><span>Explanation depth</span><Select value={gear} onValueChange={next => onGearChange(next as Gear)} disabled={busy}><SelectTrigger aria-label="Mobile explanation depth"><SelectValue/></SelectTrigger><SelectContent>{(['Quick','Guided','Deep'] as Gear[]).map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select></div><p>Use @ in your message to mention a note.</p></div></SheetContent></Sheet></>;
}
