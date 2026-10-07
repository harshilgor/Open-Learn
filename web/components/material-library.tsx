"use client";
import { authenticatedFetch } from '@/lib/account-session';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { apiBaseUrl, learningApi } from '@/lib/api';
import { RichContent } from './rich-content';

type Material = { id: string; title: string; versionId: string; status: string; role: string; jobId?: string; issues?: { message: string }[] };
type Source = { spanId?: string; id?: string; title?: string; pageIndex: number; text: string };
type Answer = { blocks: { heading: string; body: string }[]; sources: Source[]; message: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(`${apiBaseUrl()}/v1${path}`, init);
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = body as { detail?: { message?: string } };
    throw new Error(error.detail?.message || 'Material request failed.');
  }
  return body as T;
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export function MaterialLibrary({courseId, initiallyOpen=false}:{courseId?:string;initiallyOpen?:boolean}={}) {
  const materialPath='/materials'+(courseId?`?course_id=${encodeURIComponent(courseId)}`:'');
  const [items, setItems] = useState<Material[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [role, setRole] = useState('reference');
  const [passages, setPassages] = useState<Source[]>([]);
  const [open, setOpen] = useState(initiallyOpen);
  const pending = items.some(item => ['queued', 'running', 'uploaded'].includes(item.status));

  async function refresh() {
    const result = await call<{ materials: Material[] }>(materialPath);
    setItems(result.materials);
  }
  useEffect(() => {
    if (!open) return;
    let active = true;
    const load = () => call<{ materials: Material[] }>(materialPath).then(result => { if (active) setItems(result.materials); }).catch(cause => { if (active) setError(String(cause.message)); });
    void load();
    const timer = pending ? window.setInterval(() => void load(), 2000) : undefined;
    return () => { active = false; window.clearInterval(timer); };
  }, [open, pending, materialPath]);

  async function upload(file: File) {
    setBusy(true); setError('');
    try {
      const item = await learningApi.uploadCourseMaterial(courseId || null, file, role as 'reference' | 'textbook' | 'lecture_notes' | 'sample_paper' | 'answer_key');
      setSelected(previous => [...previous, item.versionId]);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Upload failed.'); }
    finally { setBusy(false); }
  }

  async function ask() {
    setBusy(true); setError(''); setAnswer(null);
    try {
      const session = await learningApi.createSession({ topic: question.slice(0, 200), gear: 'Guided', courseId });
      for (const version of selected) await call(`/sessions/${session.id}/materials`, json({ materialVersionId: version }));
      setAnswer(await call<Answer>(`/sessions/${session.id}/material-answer`, json({ message: question })));
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not answer.'); }
    finally { setBusy(false); }
  }

  async function inspect(item: Material) {
    try { setPassages((await call<{ blocks: Source[] }>(`/material-versions/${item.versionId}/blocks`)).blocks); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not open material.'); }
  }

  async function remove(item: Material) {
    try {
      await call(`/materials/${item.id}`, { method: 'DELETE' });
      setSelected(previous => previous.filter(id => id !== item.versionId));
      setAnswer(null); setPassages([]); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not delete material.'); }
  }

  return <section aria-label="Supporting materials" className="w-full max-w-3xl rounded-2xl border p-4 my-4">
    <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>Supporting materials {open ? '−' : '+'}</Button>
    {open && <div className="space-y-4 mt-3">
      <p>Upload PDF, TXT, or Markdown files up to 500 MiB, or images up to 50 MiB. Text files are searchable; images are sent as visual context when your configured model supports vision.</p>
      <label className="block">Material type <select aria-label="Material type" value={role} onChange={event => setRole(event.target.value)} className="border rounded p-2"><option value="reference">Reference</option><option value="textbook">Textbook</option><option value="lecture_notes">Lecture notes</option><option value="sample_paper">Sample paper</option><option value="answer_key">Answer key</option></select></label>
      <label className="block">Upload supporting material <input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.gif" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>
      {items.map(item => <div key={item.id} className="border rounded p-3 space-y-2"><label><input type="checkbox" checked={selected.includes(item.versionId)} onChange={event => setSelected(previous => event.target.checked ? [...previous, item.versionId] : previous.filter(id => id !== item.versionId))} /> {item.title}</label><p role="status">{item.status.replaceAll('_', ' ')} · {item.role.replaceAll('_', ' ')}</p>{item.issues?.map((issue, index) => <p key={index}>{issue.message}</p>)}<Button variant="outline" onClick={() => void inspect(item)}>Inspect extracted text</Button> <Button variant="ghost" onClick={() => void remove(item)}>Delete</Button></div>)}
      <p className="text-sm">Sample papers and answer keys are stored separately and excluded from teaching retrieval in this first release.</p>
      <form onSubmit={event => { event.preventDefault(); void ask(); }} className="space-y-2"><label htmlFor="material-question">Ask your materials</label><textarea id="material-question" className="block w-full border rounded p-3" value={question} maxLength={4000} onChange={event => setQuestion(event.target.value)} /><Button disabled={busy || !question.trim() || !selected.length}>{busy ? 'Working…' : 'Find and explain'}</Button></form>
      {error && <p role="alert">{error}</p>}
      {answer && <article><p>{answer.message}</p>{answer.blocks.map((block, i) => <section key={i}><h3 className="font-semibold mt-4">{block.heading}</h3><RichContent body={block.body} /></section>)}{answer.sources.map((source, i) => <details key={source.spanId || i} className="mt-3"><summary>{source.title} · PDF page {source.pageIndex + 1} · retrieved passage</summary><p className="whitespace-pre-wrap">{source.text}</p></details>)}</article>}
      {passages.length > 0 && <details open><summary>Extracted text ({passages.length} passages)</summary><div className="max-h-96 overflow-auto">{passages.map((source, i) => <section key={source.id || i} className="my-3"><h4>Page {source.pageIndex + 1}</h4><p className="whitespace-pre-wrap">{source.text}</p></section>)}</div></details>}
    </div>}
  </section>;
}
