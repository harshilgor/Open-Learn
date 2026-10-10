"use client";

import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { ChatComposer, type ChatAttachment } from './chat-composer';
import { LessonReader } from './lesson-reader';
import { parseVisualArtifact, VISUAL_PROMPT_DRAFT } from '@/lib/generated-visual';
import { learningApi, type Gear,type NoteDraft } from '@/lib/api';
import {NoteDraftCard} from './note-draft-card';
import { GenerationStream } from '@/lib/generation-stream';
import { getJourney, type Journey } from '@/lib/learning-workflows';
import { materialCommand, materialRequest, prepareAttachment } from '@/lib/chat-materials';
import styles from './compact-tutor-chat.module.css';
import {useBrowserAssistant} from '@/lib/browser-assistant';
import {BrowserTaskDock} from './browser-task-dock';
import {ExecutionPanel} from './assistant/execution-panel';
import { useBuddies } from './buddies';
import {useVoice} from './voice/voice-provider';
import {reportVoiceFocus,VOICE_REFRESH} from '@/lib/voice/client';

/** A shared context boundary for note discussions and future concept explanations. */
export type TutorChatContext = {
  storageOwner?: string;
  sourceLabel?: string;
  floating?: boolean;
  id: string; title: string; prompt?: string; courseId?: string | null; excerpt: string; truncated?: boolean;
  note?: { noteId: string; expectedRevision: number; startOffset: number; endOffset: number };
  source?: {lessonId?:string;sessionId?:string;blockId?:string};
};
type Block = { id: string; heading: string; body: string };

export function CompactTutorChat({ context, onClose }: { context: TutorChatContext; onClose: () => void }) {
  const {active:buddy} = useBuddies();
  const voice=useVoice();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const browserAssistant = useBrowserAssistant(sessionId, context.courseId);
  const [revision, setRevision] = useState(1);
  const [turns, setTurns] = useState<Journey['turns']>([]);
  const [prompt, setPrompt] = useState(context.prompt || '');
  const [gear, setGear] = useState<Gear>('Quick');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [drafts,setDrafts]=useState<NoteDraft[]>([]);
  useEffect(()=>{const ready=(event:Event)=>{const detail=(event as CustomEvent).detail;if(detail?.chatId!==sessionId||!detail?.draftId)return;void learningApi.getNoteDraft(detail.draftId).then(draft=>setDrafts(current=>[...current.filter(value=>value.id!==draft.id),draft])).catch(cause=>setError(String(cause)));};window.addEventListener('openlearn:note-draft-ready',ready);return()=>window.removeEventListener('openlearn:note-draft-ready',ready);},[sessionId]);
  const [pending, setPending] = useState<{ question: string; blocks: Block[]; visualizations?:unknown[] } | null>(null);
  useEffect(()=>{
    const draft=(event:Event)=>{const value=(event as CustomEvent).detail;if(typeof value?.text==='string'&&value.text.length<=4000&&event.target instanceof Node&&panel.current?.contains(event.target))setPrompt(value.text);};
    window.addEventListener(VISUAL_PROMPT_DRAFT,draft);return()=>window.removeEventListener(VISUAL_PROMPT_DRAFT,draft);
  },[]);
  const stream = useRef<GenerationStream | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const alive = useRef(true);
  const storageKey = `forma:context-chat:${context.storageOwner || 'session'}:${context.id}`;
  const [restoredDraftKey,setRestoredDraftKey] = useState('');
  useEffect(()=>{const timer=window.setTimeout(()=>{try{const saved=localStorage.getItem(`${storageKey}:draft`);if(saved!==null)setPrompt(saved);}catch{/* Optional draft recovery. */}setRestoredDraftKey(storageKey);},0);return()=>window.clearTimeout(timer);},[storageKey]);
  useEffect(()=>{if(restoredDraftKey!==storageKey)return;try{localStorage.setItem(`${storageKey}:draft`,prompt);}catch{/* Keep the in-memory draft. */}},[prompt,restoredDraftKey,storageKey]);

  useEffect(() => {
    alive.current = true;
    panel.current?.querySelector<HTMLTextAreaElement>('textarea')?.focus();
    let live = true;
    const sid = (() => { try { return localStorage.getItem(storageKey); } catch { return null; } })();
    const restoreTimer = window.setTimeout(() => {
    if (sid) {
      setBusy(true);
      void getJourney(sid).then(journey => {
        if (live) { setSessionId(sid); setRevision(journey.revision); setTurns(journey.turns); }
      }).catch(() => { try { localStorage.removeItem(storageKey); } catch { /* Optional hint. */ } }).finally(() => { if (live) setBusy(false); });
    }
    }, 0);
    return () => { window.clearTimeout(restoreTimer); live = false; alive.current = false; requestController.current?.abort(); void stream.current?.stop().catch(() => undefined); };
  }, [storageKey]);
  useEffect(() => { content.current?.scrollTo({ top: content.current.scrollHeight }); }, [turns, pending]);
  useEffect(()=>{const refresh=(event:Event)=>{if((event as CustomEvent).detail!==sessionId||!sessionId)return;void getJourney(sessionId).then(journey=>{setRevision(journey.revision);setTurns(journey.turns);}).catch(()=>{});};window.addEventListener(VOICE_REFRESH,refresh);return()=>window.removeEventListener(VOICE_REFRESH,refresh);},[sessionId]);
  async function startVoice(){try{const sid=sessionId||(await learningApi.createSession({topic:`${context.title} discussion`.slice(0,200),goal:`Discuss ${context.title}`.slice(0,1000),gear,courseId:context.courseId,buddyId:buddy?.id,parentSessionId:context.source?.sessionId})).id;setSessionId(sid);try{localStorage.setItem(storageKey,sid);}catch{/* Conversation saved on server. */}reportVoiceFocus(context.note?{quiz_id:null,presentation_id:null,lesson_id:null,visualization_id:null,note_id:context.note.noteId,expected_revision:context.note.expectedRevision,selection_start:context.note.startOffset,selection_end:context.note.endOffset,selected_text:null,source_span_id:null}:{quiz_id:null,presentation_id:null,lesson_id:null,visualization_id:null,note_id:null,selection_start:null,selection_end:null,selected_text:context.excerpt.slice(0,6000),source_span_id:null});await voice?.start(sid);}catch(cause){setError(String(cause));}}

  async function submit() {
    const question = prompt.trim();
    if (!question || busy) return;
    setBusy(true); setError(''); setPending({ question, blocks: [] });
    const controller = new AbortController(); requestController.current = controller;
    let sid = sessionId;
    try {
      if (!sid) {
        sid = (await learningApi.createSession({ topic: `${context.title} discussion`.slice(0, 200), goal: `Discuss ${context.title}`.slice(0, 1000), gear, courseId: context.courseId, buddyId:buddy?.id,parentSessionId:context.source?.sessionId })).id;
        if (!alive.current) return;
        setSessionId(sid);
        try { localStorage.setItem(storageKey, sid); } catch { /* Server conversation is still durable. */ }
      }
      const admittedAttachments: {versionId:string;name:string}[] = [];
      for (const attachment of attachments) {
        const uploaded = await prepareAttachment(attachment, controller.signal, item => setAttachments(current => current.map(existing => existing.id === item.id ? item : existing)));
        await materialRequest(`/sessions/${sid}/materials`, materialCommand({ materialVersionId: uploaded.versionId }, controller.signal));
        admittedAttachments.push({versionId:uploaded.versionId!,name:uploaded.name});
      }
      if (await browserAssistant.tryStart(question,sid,admittedAttachments,'ask')) { setPrompt('');setPending(null);return; }
      controller.signal.throwIfAborted();
      const nextStream = new GenerationStream(); stream.current = nextStream;
      let generationError = '';
      await nextStream.start(sid, { mode: 'ask', action: 'message', message: question, gear, expectedRevision: revision,
        ...(context.note ? { noteContext: { notes: [context.note] } } : { selectedText: context.excerpt,selectedLessonId:context.source?.lessonId,selectedBlockId:context.source?.blockId }),
      }, { onEvent: event => {
        if (!alive.current) return;
        if (event.type === 'lesson.block_started') {
          const block = event.data.block as { id?: string; heading?: string } | undefined;
          setPending(current => current ? { ...current, blocks: [...current.blocks, { id: block?.id || String(event.data.blockId), heading: block?.heading || '', body: '' }] } : current);
        } else if (event.type === 'text.delta') {
          setPending(current => current ? { ...current, blocks: current.blocks.map(block => block.id === event.data.blockId ? { ...block, body: block.body + String(event.data.text || '') } : block) } : current);
        } else if (event.type === 'visualization.error') {
          setError('The interactive visual could not be completed. Your explanation is still available.');
          setPending(current => current ? { ...current, visualizations: [] } : current);
        } else if (event.type === 'visualization.ready') {
          const visual=parseVisualArtifact(event.data.spec);
          if(visual)setPending(current=>current?{...current,visualizations:[...(current.visualizations||[]).filter(value=>parseVisualArtifact(value)?.id!==visual.id),visual]}:current);
        } else if (event.type === 'generation.error') generationError = String(event.data.message || 'The tutor response could not finish.');
      } });
      if (!alive.current) return;
      const journey = await getJourney(sid);
      setRevision(journey.revision); setTurns(journey.turns); setPending(null);
      if (generationError) throw new Error(generationError);
      if (!nextStream.wasCancelled) { setPrompt(''); setAttachments([]); }
      window.dispatchEvent(new Event('forma:chat-history-changed'));
    } catch (cause) {
      if (alive.current) {
        setError(cause instanceof Error ? cause.message : 'The note discussion could not start.');
        if (sid) await getJourney(sid).then(journey => {
          if (alive.current) { setRevision(journey.revision); setTurns(journey.turns); setPending(null); }
        }).catch(() => undefined);
      }
    } finally {
      stream.current = null;
      requestController.current = null;
      if (alive.current) setBusy(false);
    }
  }

  return <aside ref={panel} className={styles.panel} aria-label="Note discussion" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}>
    {!context.floating ? <header className={styles.header}><div><strong>Discuss</strong><span>{context.title}</span></div><button type="button" aria-label="Close discussion" onClick={onClose}><X size={18} /></button></header> : null}
    <div className={styles.context}><details><summary>{context.truncated ? 'Opening passage attached' : context.note ? 'Note attached' : 'Passage attached'}</summary>{context.truncated ? <p>Select another passage in the note to discuss a later section.</p> : null}<p>{context.excerpt}</p></details></div>
    <div ref={content} className={styles.content}>
      {drafts.map(draft=><NoteDraftCard key={draft.id} draft={draft} onHandled={updated=>setDrafts(current=>current.map(value=>value.id===updated.id?updated:value))}/>)}
      {!turns.length && !pending ? <p className={styles.empty}>Ask about an idea, an example, or something unclear in this note.</p> : null}
      {turns.map((turn, index) => <div className={styles.turn} key={`${turn.generationId || index}`}><p className={styles.question}>{turn.question}</p>{turn.lesson?<LessonReader id={turn.lesson.id} lessonId={turn.lesson.id} blocks={turn.lesson.blocks}/>:null}</div>)}
      {pending ? <div className={styles.turn}><p className={styles.question}>{pending.question}</p>{pending.blocks.length ? <LessonReader id="side-chat-stream" blocks={pending.blocks.map((block,index)=>({...block,visualizations:(pending.visualizations||[]).filter(value=>parseVisualArtifact(value)?.blockIndex===index)}))}/> : <p role="status">Thinking…</p>}</div> : null}
      <ExecutionPanel showTools={false} sessionId={sessionId} courseId={context.courseId} onSession={id => { setSessionId(id); try { localStorage.setItem(storageKey, id); } catch { /* Durable server state remains available. */ } }} />
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
    </div>
    <div className={styles.composer}><BrowserTaskDock tasks={browserAssistant.tasks} onCommand={browserAssistant.command} notice={browserAssistant.notice} error={browserAssistant.error} replyTarget={browserAssistant.replyTarget} replyTargets={browserAssistant.replyTargets} onReplyTargetChange={browserAssistant.setReplyTarget}/><ChatComposer onVoice={voice?()=>void startVoice():undefined} variant="compact" value={prompt} onChange={setPrompt} attachments={attachments} onAttachmentsChange={setAttachments} onSubmit={() => void submit()} onCancel={busy ? () => { requestController.current?.abort(); void stream.current?.stop().catch(cause => setError(String(cause))); } : undefined} busy={busy} followup={turns.length > 0} gear={gear} onGearChange={setGear} mode="ask" /></div>
  </aside>;
}
