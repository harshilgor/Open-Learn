'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { request } from '@/lib/api';

type Concept = { id: string; title: string; definition: string; discipline: string; expected_grain: string; review_state: string; retirement?: string; successor_ids: string[] };
type Edge = { id: string; from_concept_id: string; to_concept_id: string; relationship: string; rationale: string; review_state: string };
type Mapping = { id: string; course_id: string; concept_id: string; wording: string; scope: string; capability: string };
type Report = { id: string; concept_id: string; description: string; status: string };
type Graph = { revision: number; stable_concepts: Concept[]; stable_concept_relations: Edge[]; course_concept_mappings: Mapping[]; concept_mapping_reports?: Report[] };
type Resolution = { status: string; concept_id?: string; candidates: { id: string; title: string; definition: string; discipline: string }[] };

const fieldStyle = 'w-full rounded-lg border border-white/20 bg-transparent px-3 py-2';
const buttonStyle = 'rounded-lg border border-white/25 px-4 py-2 hover:bg-white/10 disabled:opacity-40';
const sectionStyle = 'space-y-4 rounded-xl border border-white/15 p-5';

export default function ConceptWorkspace() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [courses, setCourses] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [prerequisites, setPrerequisites] = useState<{ concepts: { concept_id: string; rationale: string; depth: number }[]; truncated: boolean } | null>(null);
  const [selected, setSelected] = useState('');
  const reload = useCallback(async () => {
    const [nextGraph, nextCourses] = await Promise.all([request<Graph>('/v1/concepts'), request<{ id: string; name: string }[]>('/v1/courses')]);
    setGraph(nextGraph); setCourses(nextCourses);
  }, []);
  useEffect(() => { void reload().catch(e => setError(e instanceof Error ? e.message : 'Could not load concepts.')); }, [reload]);
  const active = graph?.stable_concepts.filter(c => c.review_state === 'reviewed') ?? [];
  const title = (id: string) => graph?.stable_concepts.find(c => c.id === id)?.title ?? id;
  const options = () => <><option value="">Choose a concept</option>{active.map(c => <option key={c.id} value={c.id}>{c.title} · {c.discipline}</option>)}</>;

  async function mutate(path: string, value: object, success: string) {
    setBusy(true); setError(''); setMessage('');
    try { await request(path, { method: 'POST', body: JSON.stringify(value) }); await reload(); setMessage(success); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save this change.'); }
    finally { setBusy(false); }
  }
  function form(event: FormEvent<HTMLFormElement>) { event.preventDefault(); return new FormData(event.currentTarget); }
  function list(value: FormDataEntryValue | null) { return String(value ?? '').split(',').map(s => s.trim()).filter(Boolean); }

  return <main className="mx-auto max-w-5xl space-y-7 p-6 text-[var(--foreground)]">
    <header className="space-y-2"><Link href="/" className="underline">← Back to learning</Link><h1 className="text-3xl font-semibold">Concepts and course meanings</h1><p>Review how ideas connect and keep their meaning consistent across lessons.</p><p className="text-sm opacity-70">Personal concept library · Revision {graph?.revision ?? '…'}. Generated relationships need your review. Shared academic catalogs are not edited here.</p></header>
    {error && <p role="alert" className="rounded-lg border border-red-400 p-3">{error}</p>}
    {message && <p role="status" className="rounded-lg border border-emerald-500 p-3">{message}</p>}
    {!graph && !error && <p role="status">Loading concepts…</p>}
    <section className={sectionStyle}><h2 className="text-xl font-semibold">Find the right meaning</h2>
      <form className="space-y-3" onSubmit={async e => { const f = form(e); setError(''); try { const params = new URLSearchParams({ query: String(f.get('query')) }); if (f.get('course')) params.set('course_id', String(f.get('course'))); setResolution(await request<Resolution>('/v1/concepts/resolve?' + params)); } catch (error) { setError(String(error)); } }}>
        <label className="block">Topic<input className={fieldStyle} name="query" required placeholder="For example, fields" /></label>
        <label className="block">Course context<select className={fieldStyle} name="course"><option value="">All my courses</option>{courses.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
        <button className={buttonStyle}>Find concepts</button>
      </form>
      {resolution && <div className="space-y-3"><p>{resolution.status === 'resolved' ? 'One reviewed meaning matches.' : resolution.candidates.length ? 'Which meaning do you want to study?' : 'No reviewed meaning found. Add a concept or provide more course context.'}</p>{resolution.candidates.map(c => <button key={c.id} className={`${buttonStyle} block w-full text-left`} onClick={() => { setSelected(c.id); setMessage(`Selected ${c.title}.`); }}><strong>{c.title} · {c.discipline}</strong><p>{c.definition}</p></button>)}</div>}
    </section>

    <section className={sectionStyle}><h2 className="text-xl font-semibold">Your concepts</h2>
      {graph?.stable_concepts.length === 0 && <p>No reviewed concepts yet. Add a clear definition before connecting learning evidence.</p>}
      {graph?.stable_concepts.map(c => <article key={c.id} className="rounded-lg border border-white/10 p-3"><h3 className="font-semibold">{c.title} · {c.discipline}</h3><p>{c.definition}</p><p className="text-sm opacity-70">Scope: {c.expected_grain}</p>{c.retirement && <p>Historical concept: {c.retirement}. {c.successor_ids.map(title).join(', ')}. Historical evidence remains preserved.</p>}<code className="text-xs break-all opacity-60">{c.id}</code></article>)}
      <details><summary className="cursor-pointer font-medium">Add a reviewed concept</summary><form className="mt-4 space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts', { title: f.get('title'), definition: f.get('definition'), discipline: f.get('discipline'), expected_grain: f.get('grain'), aliases: list(f.get('aliases')), examples: list(f.get('examples')) }, 'Concept added.'); }}>
        <label className="block">Name<input name="title" className={fieldStyle} required maxLength={200} /></label>
        <label className="block">Definition<textarea name="definition" className={fieldStyle} required maxLength={4000} /></label>
        <label className="block">Discipline<input name="discipline" className={fieldStyle} required maxLength={200} /></label>
        <label className="block">What this concept covers<textarea name="grain" className={fieldStyle} required maxLength={1000} /></label>
        <label className="block">Aliases, separated by commas<input name="aliases" className={fieldStyle} /></label><label className="block">Examples, separated by commas<input name="examples" className={fieldStyle} /></label>
        <button disabled={busy} className={buttonStyle}>Save reviewed definition</button>
      </form></details>
    </section>

    <section className={sectionStyle}><h2 className="text-xl font-semibold">Course meanings</h2>
      {graph?.course_concept_mappings.map(m => <p key={m.id}><strong>{m.wording}</strong> → {title(m.concept_id)} · {courses.find(c => c.id === m.course_id)?.name ?? 'Course'} · {m.capability}<br /><span className="opacity-70">{m.scope}</span></p>)}
      <form className="space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts/course-mappings', { concept_id: f.get('concept'), course_id: f.get('course'), outcome_id: f.get('outcome'), wording: f.get('wording'), scope: f.get('scope'), capability: f.get('capability'), aliases: list(f.get('aliases')), material_ids: [] }, 'Course meaning saved.'); }}>
        <label className="block">Concept<select name="concept" required className={fieldStyle}>{options()}</select></label><label className="block">Course<select required name="course" className={fieldStyle}><option value="">Choose a course</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label className="block">Outcome identifier<input required name="outcome" pattern="[A-Za-z0-9_.:-]+" className={fieldStyle} placeholder="For example, eigenvectors-intro" /></label><label className="block">Course wording<input required name="wording" className={fieldStyle} /></label><label className="block">Expected scope<textarea required name="scope" className={fieldStyle} /></label><label className="block">Capability<select name="capability" className={fieldStyle}>{['recall', 'explain', 'apply', 'transfer'].map(v => <option key={v}>{v}</option>)}</select></label><label className="block">Course aliases<input name="aliases" className={fieldStyle} /></label><button disabled={busy} className={buttonStyle}>Save course meaning</button>
      </form>
    </section>

    <section className={sectionStyle}><h2 className="text-xl font-semibold">Relationships and prerequisites</h2><p>“Prerequisite” means the first concept is needed before the second. Related concepts are never mandatory prerequisites.</p>
      {graph?.stable_concept_relations.map(edge => <article className="rounded-lg border border-white/10 p-3 space-y-2" key={edge.id}><p><strong>{title(edge.from_concept_id)}</strong> → {title(edge.to_concept_id)} · {edge.relationship.replaceAll('_', ' ')} · {edge.review_state}</p><p>{edge.rationale}</p><form className="flex flex-wrap gap-2" onSubmit={e => { const f = form(e); void mutate(`/v1/concepts/relationships/${edge.id}/review`, { expected_graph_revision: graph.revision, decision: f.get('decision'), rationale: f.get('rationale') }, 'Relationship review saved.'); }}><label>Review rationale<input name="rationale" required minLength={5} className={fieldStyle} /></label><label>Decision<select name="decision" className={fieldStyle}><option value="reviewed">Accept</option><option value="rejected">Reject</option></select></label><button disabled={busy} className={buttonStyle}>Save review</button></form></article>)}
      <form className="space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts/relationships', { from_concept_id: f.get('from'), to_concept_id: f.get('to'), relationship: f.get('kind'), rationale: f.get('rationale'), origin: 'human' }, 'Relationship proposed. Review it to make it effective.'); }}>
        <label className="block">First concept<select name="from" required className={fieldStyle}>{options()}</select></label><label className="block">Second concept<select name="to" required className={fieldStyle}>{options()}</select></label><label className="block">Relationship<select name="kind" className={fieldStyle}>{['prerequisite', 'part_of', 'related', 'commonly_confused_with'].map(v => <option key={v}>{v}</option>)}</select></label><label className="block">Why this connection matters<textarea name="rationale" required minLength={5} className={fieldStyle} /></label><button disabled={busy} className={buttonStyle}>Propose relationship</button>
      </form>
      <label className="block">Inspect prerequisite scope<select value={selected} onChange={e => { setSelected(e.target.value); setPrerequisites(null); }} className={fieldStyle}>{options()}</select></label><button className={buttonStyle} disabled={!selected} onClick={async () => { try { setPrerequisites(await request(`/v1/concepts/${selected}/prerequisites?depth=3&limit=20`)); } catch (e) { setError(String(e)); } }}>Show prerequisites</button>
      {prerequisites && <div>{!prerequisites.concepts.length && <p>No reviewed prerequisites within this scope.</p>}{prerequisites.concepts.map(c => <p key={c.concept_id}>{title(c.concept_id)} · {c.rationale}</p>)}{prerequisites.truncated && <p>Showing the first three levels, up to twenty concepts.</p>}</div>}
    </section>

    <section className={sectionStyle}><h2 className="text-xl font-semibold">Historical mappings</h2><p>Map imported graph nodes explicitly. Old questions and answers keep their original content.</p>
      <form className="space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts/legacy-mappings', { graph_id: f.get('graph'), graph_revision: Number(f.get('revision')), node_id: f.get('node'), concept_id: f.get('concept'), rationale: f.get('rationale') }, 'Historical mapping recorded.'); }}>
        <label className="block">Imported graph ID<input name="graph" required className={fieldStyle} /></label><label className="block">Graph revision<input name="revision" type="number" min={1} required className={fieldStyle} /></label><label className="block">Original node ID<input name="node" required className={fieldStyle} /></label><label className="block">Stable concept<select name="concept" required className={fieldStyle}>{options()}</select></label><label className="block">Reason<textarea name="rationale" minLength={5} required className={fieldStyle} /></label><button disabled={busy} className={buttonStyle}>Review mapping</button>
      </form>
      <details><summary className="cursor-pointer font-medium">Merge or split concept identities</summary><p className="my-3">Create destination concepts first. Splits retain uncertain evidence on the original concept until reviewed. Relationships and course mappings require a new review.</p><form className="space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts/identity-changes', { expected_graph_revision: graph?.revision, kind: f.get('kind'), source_ids: list(f.get('sources')), target_ids: list(f.get('targets')), rationale: f.get('rationale') }, 'Identity change recorded; historical evidence preserved.'); }}><label className="block">Change<select name="kind" className={fieldStyle}><option value="merge">Merge</option><option value="split">Split</option></select></label><label className="block">Original concept IDs, comma separated<input name="sources" required className={fieldStyle} /></label><label className="block">Destination concept IDs, comma separated<input name="targets" required className={fieldStyle} /></label><label className="block">Review rationale<textarea name="rationale" required minLength={10} className={fieldStyle} /></label><button disabled={busy} className={buttonStyle}>Save reviewed identity change</button></form></details>
    </section>
    <section className={sectionStyle}><h2 className="text-xl font-semibold">Report a mapping error</h2><p>A report preserves the current mapping until it has been reviewed.</p><form className="space-y-3" onSubmit={e => { const f = form(e); void mutate('/v1/concepts/reports', { concept_id: f.get('concept'), description: f.get('description') }, 'Mapping error recorded for review.'); }}><label className="block">Concept<select name="concept" required className={fieldStyle}><option value="">Choose a concept</option>{graph?.stable_concepts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label><label className="block">What seems wrong?<textarea name="description" required minLength={5} className={fieldStyle} /></label><button disabled={busy} className={buttonStyle}>Submit report</button></form>{graph?.concept_mapping_reports?.map(r => <p key={r.id}>{title(r.concept_id)}: {r.description} · {r.status}</p>)}</section>
  </main>;
}
