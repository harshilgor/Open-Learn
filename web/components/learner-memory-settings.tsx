'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { learningApi, request } from '@/lib/api';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { openChatSession } from '@/lib/workspace-events';
import {
  MEMORY_KINDS, memoryApi, type FactInput, type ForgetPreview, type MemoryChange, type MemoryEpisode, type MemoryFact,
  type MemoryProfile, type MemorySettings,
} from '@/lib/learner-memory';
import { SourceMemorySettings } from './source-memory-settings';
import styles from './learner-memory-settings.module.css';

type Course = { id: string; name: string };
type Data = {
  active: MemoryFact[]; tentative: MemoryFact[]; archived: MemoryFact[]; profile: MemoryProfile | null;
  changes: MemoryChange[]; episodes: MemoryEpisode[]; settings: MemorySettings | null; courses: Course[]; chats: Record<string, string>;
};
const EMPTY: Data = { active: [], tentative: [], archived: [], profile: null, changes: [], episodes: [], settings: null, courses: [], chats: {} };
const KIND_NAMES: Record<string, string> = Object.fromEntries(MEMORY_KINDS.map(item => [item.kind, item.label.toLowerCase()]));

function day(epochSeconds: number) {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Loads one page of chat titles so memories can say where they were said. Failure just means no titles. */
async function chatTitles(): Promise<Record<string, string>> {
  try {
    const data = await learningApi.listChatSessions({ limit: 100 });
    return Object.fromEntries(data.sessions.map(item => [item.id, item.title]));
  } catch {
    return {};
  }
}

/**
 * "What Open Learn remembers about you" (spec §10). Every memory shows where
 * it came from and can be edited, forgotten or confirmed. Edits never rewrite
 * a memory: the server keeps the old wording in its history.
 */
export function LearnerMemorySettings({ loadChats = chatTitles }: { loadChats?: () => Promise<Record<string, string>> }) {
  const [data, setData] = useState<Data>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [course, setCourse] = useState('all');
  const [showArchived, setShowArchived] = useState(false);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const version = ++generation.current;
    const [active, tentative, archived, profile, changes, episodes, settings, courses, chats] = await Promise.all([
      memoryApi.facts('active'), memoryApi.facts('tentative'), memoryApi.facts('archived'), memoryApi.profile(),
      memoryApi.changes(), memoryApi.episodes(), memoryApi.settings(), request<Course[]>('/v1/courses'), loadChats(),
    ]);
    if (version === generation.current) {
      setData({ active, tentative, archived, profile, changes, episodes, settings, courses, chats });
      setLoaded(true);
    }
  }, [loadChats]);

  useEffect(() => {
    const refresh = () => { generation.current++; setData(EMPTY); setLoaded(false); void reload().catch(error => setMessage(String(error.message))); };
    refresh();
    window.addEventListener(ACCOUNT_CHANGED, refresh);
    return () => { generation.current++; window.removeEventListener(ACCOUNT_CHANGED, refresh); };
  }, [reload]);

  async function run(action: () => Promise<unknown>, done?: string) {
    setBusy(true); setMessage('');
    try {
      await action();
      if (done) setMessage(done);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'That didn’t work. Try again.');
    } finally {
      // A conflict means the memory changed elsewhere; reloading shows the current version.
      await reload().catch(() => undefined);
      setBusy(false);
    }
  }

  const courseName = (id: string | null) => (id ? data.courses.find(item => item.id === id)?.name || 'a course' : null);
  const inCourse = (item: { courseId: string | null }) => course === 'all' || (course === 'global' ? item.courseId === null : item.courseId === course);
  const review = [...data.active, ...data.tentative].filter(item => item.needsReview);
  const current = [...data.active, ...data.tentative].filter(item => !item.needsReview && inCourse(item));
  const archived = data.archived.filter(inCourse);
  const actions = { busy, run, courses: data.courses, chats: data.chats, courseName };

  return <section aria-label="What Open Learn remembers about you" className={styles.page}>
    <p className={styles.lede}>Open Learn remembers things you tell it so the tutor doesn’t have to ask again. It saves only what you said in your own words, and you can change or remove anything here.</p>
    {message ? <p role="status" className={styles.status}>{message}</p> : null}

    {data.settings ? <label className={styles.toggle}>
      <input type="checkbox" disabled={busy} checked={!data.settings.learningEnabled}
        onChange={event => { const settings = data.settings!; void run(() => memoryApi.setLearning(settings, !event.target.checked),
          event.target.checked ? 'Paused. Open Learn won’t learn anything new from your chats.' : 'Learning from your chats is back on.'); }} />
      Pause learning new memories
    </label> : null}

    {review.length ? <section aria-label="Needs your review" className={styles.group}>
      <h3>Needs your review</h3>
      <p className={styles.muted}>These memories disagree. Keep the one that’s right; the other is replaced.</p>
      {review.map(item => <FactRow key={item.id} item={item} {...actions} reviewing />)}
    </section> : null}

    {data.profile?.items.length ? <section aria-label="What the tutor always knows" className={styles.group}>
      <h3>What the tutor always knows</h3>
      <p className={styles.muted}>Your most important memories are included in every chat.</p>
      <ul className={styles.plain}>{data.profile.items.map(item => <li key={item.id}>{item.statement}</li>)}</ul>
    </section> : null}

    <div className={styles.filters}>
      <label>Show memories for<select value={course} onChange={event => setCourse(event.target.value)}>
        <option value="all">Everything</option><option value="global">All courses (not course-specific)</option>
        {data.courses.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
    </div>

    {loaded && !current.length && !review.length ? <p className={styles.muted}>Nothing remembered yet{course === 'all' ? '' : ' for this filter'}.</p> : null}
    {MEMORY_KINDS.map(({ kind, label }) => {
      const items = current.filter(item => item.kind === kind);
      return items.length ? <section key={kind} aria-label={label} className={styles.group}>
        <h3>{label}</h3>{items.map(item => <FactRow key={item.id} item={item} {...actions} />)}
      </section> : null;
    })}

    <AddMemory {...actions} />

    {archived.length ? <details className={styles.group} open={showArchived} onToggle={event => setShowArchived(event.currentTarget.open)}>
      <summary>Faded memories ({archived.length})</summary>
      <p className={styles.muted}>Memories that haven’t come up in a while. The tutor no longer uses them unless you confirm them.</p>
      {archived.map(item => <FactRow key={item.id} item={item} {...actions} />)}
    </details> : null}

    {data.changes.length ? <section aria-label="Recently updated" className={styles.group}>
      <h3>Recently updated</h3>
      <ul className={styles.plain}>{data.changes.slice(0, 10).map(change => <li key={`${change.at}-${change.source}`}>
        <span className={styles.muted}>{day(change.at)}</span> · {change.summary}</li>)}</ul>
    </section> : null}

    {data.episodes.length ? <section aria-label="Session summaries" className={styles.group}>
      <h3>Session summaries</h3>
      <p className={styles.muted}>Short notes on what past chats covered, so you can pick up where you left off.</p>
      {data.episodes.map(episode => <article key={episode.id} className={styles.row}>
        <div><p className={styles.meta}>{day(episode.periodEnd)}{data.chats[episode.sessionId] ? ` · ${data.chats[episode.sessionId]}` : ''}</p><p>{episode.summary}</p></div>
        <div className={styles.actions}><button type="button" disabled={busy} onClick={() => void run(() => memoryApi.deleteEpisode(episode.id), 'Session summary deleted.')}>Delete</button></div>
      </article>)}
    </section> : null}

    <ForgetEverything busy={busy} run={run} />

    <details className={styles.group}>
      <summary>Advanced: sources</summary>
      <SourceMemorySettings />
    </details>
  </section>;
}

type Actions = {
  busy: boolean; run: (action: () => Promise<unknown>, done?: string) => Promise<void>; courses: Course[];
  chats: Record<string, string>; courseName: (id: string | null) => string | null;
};

function origin(item: MemoryFact, chats: Record<string, string>) {
  const turn = item.basis?.find(ref => ref.type === 'turn' && ref.sessionId);
  if (turn) return { text: `You said this on ${day(item.learnedAt)}${chats[turn.sessionId!] ? ` in “${chats[turn.sessionId!]}”` : ''}`, sessionId: turn.sessionId!, quote: turn.quote };
  if (item.basis?.some(ref => ref.type === 'learner')) return { text: `You ${item.origin === 'user_confirmed' ? 'edited' : 'added'} this on ${day(item.learnedAt)}` };
  if (item.basis?.some(ref => ref.type === 'memory_source')) return { text: `Saved from your preferences on ${day(item.learnedAt)}` };
  return { text: `Remembered on ${day(item.learnedAt)}` };
}

function FactRow({ item, busy, run, courses, chats, courseName, reviewing = false }: Actions & { item: MemoryFact; reviewing?: boolean }) {
  const [editing, setEditing] = useState(false);
  const [forgetting, setForgetting] = useState(false);
  const [history, setHistory] = useState<MemoryFact[] | null>(null);
  const source = origin(item, chats);
  const unsure = item.status === 'tentative' || item.origin === 'inferred';
  const scope = courseName(item.courseId);
  if (editing) return <FactForm initial={item} courses={courses} busy={busy} submitLabel="Save changes" onCancel={() => setEditing(false)}
    onSubmit={input => run(() => memoryApi.edit(item, input), 'Memory updated. The earlier version is kept in its history.').then(() => setEditing(false))} />;
  return <article className={styles.row} aria-label={item.statement}>
    <div>
      <p>{item.statement}</p>
      <p className={styles.meta}>
        {reviewing ? `${KIND_NAMES[item.kind] || item.kind} · ` : ''}{scope ? `${scope} · ` : ''}
        {source.sessionId ? <button type="button" className={styles.link} onClick={() => openChatSession(source.sessionId!)}>{source.text}</button> : source.text}
        {unsure ? ' · Not confirmed yet' : ''}{item.status === 'archived' ? ' · Faded' : ''}
      </p>
      {source.quote ? <p className={styles.quote}>“{source.quote}”</p> : null}
      {item.sensitive ? <label className={styles.toggle}>
        <input type="checkbox" disabled={busy} checked={Boolean(item.sensitiveEnabled)}
          onChange={event => void run(() => memoryApi.setSensitive(item, event.target.checked),
            event.target.checked ? 'The tutor can now use this memory.' : 'The tutor will no longer use this memory.')} />
        Personal topic. Let the tutor use this memory
      </label> : null}
      {history ? <ol className={styles.history} aria-label="Earlier versions">{history.map(version => <li key={version.id}>
        {version.statement} <span className={styles.muted}>({day(version.learnedAt)}{version.id === item.id ? ', current' : ''})</span></li>)}</ol> : null}
    </div>
    <div className={styles.actions}>
      {reviewing ? <button type="button" disabled={busy} onClick={() => void run(() => memoryApi.confirm(item), 'Kept. The other version was replaced.')}>Keep this one</button>
        : unsure || item.status === 'archived' ? <button type="button" disabled={busy} onClick={() => void run(() => memoryApi.confirm(item), 'Confirmed. The tutor will keep this in mind.')}>Confirm</button> : null}
      <button type="button" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
      {history ? null : <button type="button" disabled={busy} onClick={() => void memoryApi.history(item.id).then(setHistory).catch(() => setHistory([]))}>History</button>}
      {forgetting
        ? <><button type="button" className={styles.danger} disabled={busy} onClick={() => void run(() => memoryApi.forget(item), 'Forgotten.')}>Yes, forget</button>
          <button type="button" disabled={busy} onClick={() => setForgetting(false)}>Cancel</button></>
        : <button type="button" disabled={busy} onClick={() => setForgetting(true)}>Forget</button>}
    </div>
  </article>;
}

function FactForm({ initial, courses, busy, submitLabel, onSubmit, onCancel }: {
  initial?: MemoryFact; courses: Course[]; busy: boolean; submitLabel: string; onSubmit: (input: FactInput) => Promise<unknown>; onCancel?: () => void;
}) {
  const [statement, setStatement] = useState(initial?.statement || '');
  const [kind, setKind] = useState(initial?.kind || 'goal');
  const [courseId, setCourseId] = useState(initial?.courseId || '');
  const [eventDate, setEventDate] = useState(initial?.eventDate?.slice(0, 10) || '');
  const ready = statement.trim().length > 0 && statement.length <= 300 && (kind !== 'deadline' || eventDate);
  return <form className={styles.form} onSubmit={event => {
    event.preventDefault();
    if (ready) void onSubmit({ statement: statement.trim(), kind, courseId: courseId || null, eventDate: eventDate || null });
  }}>
    <label>Memory<input value={statement} maxLength={300} onChange={event => setStatement(event.target.value)} placeholder="e.g. Wants to finish the linear algebra course by May" /></label>
    <label>Type<select value={kind} onChange={event => setKind(event.target.value)}>
      {MEMORY_KINDS.map(item => <option key={item.kind} value={item.kind}>{item.label}</option>)}</select></label>
    <label>Applies to<select value={courseId} onChange={event => setCourseId(event.target.value)}>
      <option value="">All courses</option>{courses.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    {kind === 'deadline' || eventDate ? <label>Date<input type="date" value={eventDate} onChange={event => setEventDate(event.target.value)} /></label> : null}
    <div className={styles.actions}>
      <button type="submit" disabled={busy || !ready}>{submitLabel}</button>
      {onCancel ? <button type="button" disabled={busy} onClick={onCancel}>Cancel</button> : null}
    </div>
  </form>;
}

function AddMemory({ busy, run, courses }: Actions) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(0);
  return <details className={styles.group} open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Add a memory</summary>
    <FactForm key={key} courses={courses} busy={busy} submitLabel="Remember this"
      onSubmit={input => run(() => memoryApi.add(input), 'Remembered.').then(() => setKey(value => value + 1))} />
  </details>;
}

function ForgetEverything({ busy, run }: { busy: boolean; run: Actions['run'] }) {
  const [preview, setPreview] = useState<ForgetPreview | null>(null);
  const [error, setError] = useState('');
  return <section aria-label="Forget everything" className={styles.group} data-danger="true">
    <h3>Forget everything</h3>
    {preview ? <>
      <p>This permanently deletes {preview.facts} {preview.facts === 1 ? 'memory' : 'memories'} and {preview.episodes} session {preview.episodes === 1 ? 'summary' : 'summaries'}. Your chats, notes and courses stay.</p>
      <div className={styles.actions}>
        <button type="button" className={styles.danger} disabled={busy} onClick={() => void run(() => memoryApi.forgetAll(preview.confirmation), 'Everything Open Learn remembered about you is deleted.').then(() => setPreview(null))}>Delete all memories</button>
        <button type="button" disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
      </div>
    </> : <>
      <p className={styles.muted}>Delete every memory and session summary. This can’t be undone.</p>
      <button type="button" disabled={busy} onClick={() => { setError(''); void memoryApi.forgetPreview().then(setPreview).catch(cause => setError(cause instanceof Error ? cause.message : 'Couldn’t check your memories.')); }}>Forget everything…</button>
    </>}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
