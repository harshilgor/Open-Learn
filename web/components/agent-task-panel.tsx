"use client";

import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { ArrowUp, Check, CheckCircle2, Circle, FileSearch, FileText, LoaderCircle, NotebookPen, Paperclip, ScanSearch, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { LearningApiError, learningApi, type AgentTask, type AgentTaskEvent } from '@/lib/api';

const LEARNER_ID = 'local';
const MAX_FILES = 3;
const MAX_CHARACTERS_PER_FILE = 300_000;

function mimeTypeFor(file: File): 'text/plain' | 'text/markdown' | 'text/csv' | null {
  const name = file.name.toLowerCase();
  if (file.type === 'text/csv' || name.endsWith('.csv')) return 'text/csv';
  if (file.type === 'text/markdown' || name.endsWith('.md') || name.endsWith('.markdown')) return 'text/markdown';
  if (file.type === 'text/plain' || name.endsWith('.txt')) return 'text/plain';
  return null;
}

const terminalStatuses = new Set<AgentTask['status']>(['completed', 'failed', 'cancelled']);

function eventDescription(event: AgentTaskEvent): { title: string; detail: string; icon: 'plan' | 'read' | 'extract' | 'write' | 'done' } {
  if (event.type === 'task.queued') return { title: 'Task queued', detail: 'The agent is waiting to plan a bounded task.', icon: 'plan' };
  if (event.type === 'task.planned') return { title: 'Plan prepared', detail: 'It will read the selected sources, extract key points, then save a learner note.', icon: 'plan' };
  if (event.type === 'tool.completed' && event.data.tool === 'read_owned_document') {
    const documents = Array.isArray(event.data.documents) ? event.data.documents : [];
    const titles = documents.map((item) => typeof item === 'object' && item && 'title' in item ? String(item.title) : null).filter(Boolean);
    return { title: 'Read source material', detail: titles.length ? titles.join(' · ') : 'Read learner-owned source material.', icon: 'read' };
  }
  if (event.type === 'tool.completed' && event.data.tool === 'extract_key_points') return { title: 'Extracted key points', detail: 'Created an extractive summary and source-derived study prompts.', icon: 'extract' };
  if (event.type === 'tool.completed' && event.data.tool === 'create_learner_note') return { title: 'Saved learner note', detail: 'Created a versioned note with source provenance.', icon: 'write' };
  if (event.type === 'task.completed') return { title: 'Task complete', detail: 'The note is ready in Notes.', icon: 'done' };
  if (event.type === 'task.cancelled') return { title: 'Task cancelled', detail: 'No further tool calls will run.', icon: 'done' };
  return { title: event.type.replace('.', ' '), detail: 'The agent recorded an update.', icon: 'plan' };
}

function ActivityIcon({ kind }: { kind: ReturnType<typeof eventDescription>['icon'] }) {
  if (kind === 'read') return <FileSearch size={15} />;
  if (kind === 'extract') return <ScanSearch size={15} />;
  if (kind === 'write') return <NotebookPen size={15} />;
  if (kind === 'done') return <CheckCircle2 size={15} />;
  return <Circle size={15} />;
}

export function AgentTaskPanel({ onCompleted }: { onCompleted: (task: AgentTask) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [goal, setGoal] = useState('Create study notes from these sources');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<AgentTask | null>(null);
  const [events, setEvents] = useState<AgentTaskEvent[]>([]);
  const onCompletedRef = useRef(onCompleted);
  const notifiedTaskRef = useRef<string | null>(null);
  onCompletedRef.current = onCompleted;

  useEffect(() => {
    if (!activeTask) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const [task, taskEvents] = await Promise.all([
          learningApi.getAgentTask(LEARNER_ID, activeTask.id),
          learningApi.getAgentTaskEvents(LEARNER_ID, activeTask.id),
        ]);
        if (cancelled) return;
        setActiveTask(task);
        setEvents(taskEvents);
        if (task.status === 'completed' && notifiedTaskRef.current !== task.id) {
          notifiedTaskRef.current = task.id;
          onCompletedRef.current(task);
        }
        if (!terminalStatuses.has(task.status)) timer = setTimeout(() => void refresh(), 700);
      } catch {
        if (!cancelled) setError('The task activity feed could not be refreshed. You can safely refresh this page.');
      }
    };
    void refresh();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [activeTask?.id]);

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    const unsupported = selected.find((file) => !mimeTypeFor(file));
    if (unsupported) {
      setError('For now, attach plain text, Markdown, or CSV. PDF, Word, images, and recordings need a sandboxed extractor before they are enabled.');
      event.target.value = '';
      return;
    }
    setFiles((current) => [...current, ...selected].slice(0, MAX_FILES));
    setError(null);
    event.target.value = '';
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length || busy) return;
    setBusy(true);
    setError(null);
    setActiveTask(null);
    setEvents([]);
    try {
      const uploads = await Promise.all(files.map(async (file) => {
        const content = await file.text();
        if (!content.trim()) throw new Error(`${file.name} is empty.`);
        if (content.length > MAX_CHARACTERS_PER_FILE) throw new Error(`${file.name} is too large for this first local text workflow.`);
        const mimeType = mimeTypeFor(file);
        if (!mimeType) throw new Error(`${file.name} is not a supported text source.`);
        return learningApi.createAgentDocument(LEARNER_ID, { title: file.name, content, mimeType });
      }));
      const task = await learningApi.createAgentTask(
        LEARNER_ID,
        { goal: goal.trim() || 'Create study notes from these sources', documentIds: uploads.map((document) => document.id), noteStyle: 'study' },
        crypto.randomUUID(),
      );
      setActiveTask(task);
      setFiles([]);
    } catch (caught) {
      setError(caught instanceof LearningApiError ? caught.message : caught instanceof Error ? caught.message : 'The note task could not run. Retry is safe.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-5 max-w-[750px] rounded-xl border border-[#dce0d5] bg-[#fbfcf9] p-4" aria-label="Agent task">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-[#e9f0e5] text-[#526649]"><FileText size={16} /></span>
        <div>
          <h2 className="text-sm font-semibold text-[#3c4937]">Turn sources into learner notes</h2>
          <p className="mt-1 text-xs leading-5 text-[#71806c]">The task records each source and saves a revisioned note. It never marks a concept as mastered.</p>
        </div>
      </div>
      <form className="mt-3" onSubmit={submit}>
        <label className="sr-only" htmlFor="agent-goal">What should the task make?</label>
        <input id="agent-goal" value={goal} maxLength={1000} onChange={(event) => setGoal(event.target.value)} disabled={busy} className="w-full rounded-lg border border-[#dfe5d9] bg-white px-3 py-2 text-sm text-[#465043] outline-none focus:border-[#9cab90]" />
        {files.length ? <div className="mt-3 flex flex-wrap gap-2">{files.map((file) => <span className="inline-flex items-center gap-1 rounded-md border border-[#d9e3d2] bg-white px-2 py-1 text-xs text-[#596b52]" key={`${file.name}-${file.lastModified}`}><FileText size={13} />{file.name}<button type="button" aria-label={`Remove ${file.name}`} className="ml-1 text-[#798875]" disabled={busy} onClick={() => setFiles((current) => current.filter((item) => item !== file))}><X size={13} /></button></span>)}</div> : null}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input ref={inputRef} className="sr-only" id="agent-source" type="file" multiple accept=".txt,.md,.markdown,.csv,text/plain,text/markdown,text/csv" onChange={chooseFiles} />
          <Button type="button" variant="outline" size="sm" disabled={busy || files.length >= MAX_FILES} onClick={() => inputRef.current?.click()}><Paperclip size={14} />Attach text source</Button>
          <span className="mr-auto text-xs text-[#7b8876]">Up to {MAX_FILES} text files</span>
          <Button type="submit" size="sm" disabled={!files.length || busy}>{busy ? 'Creating notes…' : 'Create notes'}<ArrowUp size={14} /></Button>
        </div>
      </form>
      {error ? <p className="mt-3 rounded-md border border-[#ead7d2] bg-[#fff9f7] px-3 py-2 text-xs leading-5 text-[#9a5549]" role="alert">{error}</p> : null}
      {activeTask ? <section className="mt-4 rounded-lg border border-[#dbe4d5] bg-white" aria-label="Agent task activity" aria-live="polite">
        <header className="flex items-center justify-between gap-3 border-b border-[#edf0e9] px-3 py-2.5"><div className="flex items-center gap-2 text-xs font-semibold text-[#4a5d42]"><LoaderCircle className={terminalStatuses.has(activeTask.status) ? '' : 'animate-spin'} size={15} />Agent activity</div><span className="rounded-full bg-[#eef3e9] px-2 py-0.5 text-[11px] font-medium text-[#617755]">{activeTask.status === 'completed' ? 'Complete' : activeTask.status === 'running' ? 'Working' : activeTask.status === 'planning' ? 'Planning' : activeTask.status === 'failed' ? 'Needs attention' : 'Queued'}</span></header>
        <ol className="divide-y divide-[#edf0e9]">{events.map((event) => { const item = eventDescription(event); return <li className="flex gap-2.5 px-3 py-2.5" key={event.id}><span className="mt-0.5 text-[#78906d]"><ActivityIcon kind={item.icon} /></span><div className="min-w-0"><strong className="block text-xs font-medium text-[#4a5546]">{item.title}</strong><span className="block truncate text-xs leading-5 text-[#778470]" title={item.detail}>{item.detail}</span></div></li>; })}</ol>
        {!terminalStatuses.has(activeTask.status) ? <div className="flex items-center gap-2 px-3 py-2.5 text-xs text-[#778470]"><LoaderCircle className="animate-spin" size={14} />Waiting for the next recorded step…</div> : null}
        {activeTask.status === 'completed' && activeTask.result?.noteId ? <div className="flex items-start gap-2 border-t border-[#edf0e9] px-3 py-2.5 text-xs leading-5 text-[#53684b]"><Check className="mt-0.5 shrink-0" size={14} />Note created and saved to Notes. Its task history and source hash are retained.</div> : null}
      </section> : null}
    </section>
  );
}
