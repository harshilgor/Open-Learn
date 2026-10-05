"use client";

import {routeFlashcardRequest} from '@/lib/flashcards-client';
import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { ChatComposer, type ChatAttachment } from './chat-composer';
import { RichContent } from './rich-content';
import { learningApi, type Gear } from '@/lib/api';
import { GenerationStream } from '@/lib/generation-stream';
import { getJourney, type Journey } from '@/lib/learning-workflows';
import { materialCommand, materialRequest, prepareAttachment } from '@/lib/chat-materials';
import styles from './compact-tutor-chat.module.css';
import {useBrowserAssistant} from '@/lib/browser-assistant';
import {BrowserTaskCard} from './browser-task-card';
import {ExecutionPanel} from './assistant/execution-panel';

/** A shared context boundary for note discussions and future concept explanations. */
export type TutorChatContext = {
  id: string; title: string; courseId?: string | null; excerpt: string; truncated?: boolean;
  note?: { noteId: string; expectedRevision: number; startOffset: number; endOffset: number };
};
type Block = { id: string; heading: string; body: string };

export function CompactTutorChat({ context, onClose }: { context: TutorChatContext; onClose: () => void }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const browserAssistant = useBrowserAssistant(sessionId, context.courseId);
  const [revision, setRevision] = useState(1);
  const [turns, setTurns] = useState<Journey['turns']>([]);
  const [prompt, setPrompt] = useState('');
  const [gear, setGear] = useState<Gear>('Quick');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<{ question: string; blocks: Block[] } | null>(null);
  const stream = useRef<GenerationStream | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const alive = useRef(true);
  const storageKey = `forma:context-chat:${context.id}`;

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

  async function submit() {
    const question = prompt.trim();
    if (!question || busy) return;
    setBusy(true); setError(''); setPending({ question, blocks: [] });
    const controller = new AbortController(); requestController.current = controller;
    let sid = sessionId;
    try {
      if (!sid) {
        sid = (await learningApi.createSession({ topic: `${context.title} discussion`.slice(0, 200), goal: `Discuss ${context.title}`.slice(0, 1000), gear, courseId: context.courseId })).id;
        if (!alive.current) return;
        setSessionId(sid);
        try { localStorage.setItem(storageKey, sid); } catch { /* Server conversation is still durable. */ }
      }
      if (!attachments.length && await routeFlashcardRequest(question,sid,context.courseId ?? undefined)) {setPrompt('');setPending(null);return;}
      if (!attachments.length && await browserAssistant.tryStart(question, sid)) {
        setPrompt(''); setPending(null); return;
      }
      for (const attachment of attachments) {
        const uploaded = await prepareAttachment(attachment, controller.signal, item => setAttachments(current => current.map(existing => existing.id === item.id ? item : existing)));
        await materialRequest(`/sessions/${sid}/materials`, materialCommand({ materialVersionId: uploaded.versionId }, controller.signal));
      }
      controller.signal.throwIfAborted();
      const nextStream = new GenerationStream(); stream.current = nextStream;
      let generationError = '';
      await nextStream.start(sid, { mode: 'ask', action: 'message', message: question, gear, expectedRevision: revision,
        ...(context.note ? { noteContext: { notes: [context.note] } } : { selectedText: context.excerpt }),
      }, { onEvent: event => {
        if (!alive.current) return;
        if (event.type === 'lesson.block_started') {
          const block = event.data.block as { id?: string; heading?: string } | undefined;
          setPending(current => current ? { ...current, blocks: [...current.blocks, { id: block?.id || String(event.data.blockId), heading: block?.heading || '', body: '' }] } : current);
        } else if (event.type === 'text.delta') {
          setPending(current => current ? { ...current, blocks: current.blocks.map(block => block.id === event.data.blockId ? { ...block, body: block.body + String(event.data.text || '') } : block) } : current);
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
    <header className={styles.header}><div><strong>Discuss</strong><span>{context.title}</span></div><button type="button" aria-label="Close discussion" onClick={onClose}><X size={18} /></button></header>
    <div className={styles.context}><details><summary>{context.truncated ? 'Opening passage attached' : context.note ? 'Note attached' : 'Passage attached'}</summary>{context.truncated ? <p>Select another passage in the note to discuss a later section.</p> : null}<p>{context.excerpt}</p></details></div>
    <div ref={content} className={styles.content}>
      {!turns.length && !pending ? <p className={styles.empty}>Ask about an idea, an example, or something unclear in this note.</p> : null}
      {turns.map((turn, index) => <div className={styles.turn} key={`${turn.generationId || index}`}><p className={styles.question}>{turn.question}</p>{turn.lesson?.blocks.map(block => <div key={block.id}>{block.heading ? <h3>{block.heading}</h3> : null}<RichContent body={block.body} /></div>)}</div>)}
      {pending ? <div className={styles.turn}><p className={styles.question}>{pending.question}</p>{pending.blocks.length ? pending.blocks.map(block => <div key={block.id}>{block.heading ? <h3>{block.heading}</h3> : null}<RichContent body={block.body} /></div>) : <p role="status">Thinking…</p>}</div> : null}
      <ExecutionPanel sessionId={sessionId} courseId={context.courseId} onSession={id => { setSessionId(id); try { localStorage.setItem(storageKey, id); } catch { /* Durable server state remains available. */ } }} />
      {browserAssistant.tasks.map(task=><BrowserTaskCard key={task.id} task={task} onCommand={browserAssistant.command}/>)}
      {browserAssistant.error?<p className={styles.error} role="alert">{browserAssistant.error}</p>:null}
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
    </div>
    <div className={styles.composer}><ChatComposer variant="compact" value={prompt} onChange={setPrompt} attachments={attachments} onAttachmentsChange={setAttachments} onSubmit={() => void submit()} onCancel={busy ? () => { requestController.current?.abort(); void stream.current?.stop().catch(cause => setError(String(cause))); } : undefined} busy={busy} followup={turns.length > 0} gear={gear} onGearChange={setGear} mode="ask" /></div>
  </aside>;
}
