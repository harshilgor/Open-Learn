"use client";

import {FlashcardLibraryEntry} from './flashcard-workspace';
import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { ArrowRight, BookOpen, Check, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  learningApi,
  type ReviewConfidence,
  type ReviewDashboard,
  type ReviewItem,
  type ReviewSession,
} from '@/lib/api';
import { workflow } from '@/lib/learning-workflows';
import {
  REVIEW_ASK_TUTOR_EVENT,
  type ReviewAskTutorDetail,
  openChatSession,
} from '@/lib/workspace-events';
import styles from './review.module.css';
import { RichContent } from './rich-content';

const CONFIDENCE: { id: ReviewConfidence; label: string }[] = [
  { id: 'guessing', label: 'I was guessing' },
  { id: 'somewhat', label: 'Somewhat confident' },
  { id: 'confident', label: 'Confident' },
  { id: 'very', label: 'Very confident' },
];

export function ReviewWorkspace({
  resumeSessionId,
  focusConceptId,
  onDone,
  onStartLearning,
}: {
  resumeSessionId?: string | null;
  focusConceptId?: string;
  onDone?: () => void;
  onStartLearning?: () => void;
}) {
  const reduceMotion = useAppReducedMotion();
  const [dash, setDash] = useState<ReviewDashboard | null>(null);
  const [session, setSession] = useState<ReviewSession | null>(null);
  const [length, setLength] = useState<'quick' | 'standard' | 'deep'>('standard');
  const [answer, setAnswer] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadDash = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const next = await learningApi.getReviewDashboard();
      setDash(next);
      if (next.unfinishedSessionId && !session) {
        const unfinished = await learningApi.getReviewSession(next.unfinishedSessionId);
        setSession(unfinished);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load review.');
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadDash(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadDash]);

  useEffect(() => {
    if (!resumeSessionId) return;
    const timer = window.setTimeout(() => {
      setBusy(true);
      void learningApi.getReviewSession(resumeSessionId)
        .then(setSession)
        .catch(cause => setError(cause instanceof Error ? cause.message : 'Could not resume review.'))
        .finally(() => setBusy(false));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [resumeSessionId]);

  const current: ReviewItem | null = session
    ? session.items[Math.min(session.currentIndex, Math.max(0, session.items.length - 1))] || null
    : null;

  async function start(optional = false) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      let sid: string | undefined;
      try { sid = localStorage.getItem('forma-chat-session') || undefined; } catch { /* optional */ }
      const created = await learningApi.createReviewSession({
        length, optional, sessionId: sid,
        conceptIds: focusConceptId ? [focusConceptId] : [],
        resumeSessionId: dash?.unfinishedSessionId || undefined,
      });
      const next = await learningApi.getReviewSession(created.sessionId);
      setSession(next);
      try { localStorage.setItem('forma-review-session', created.sessionId); } catch { /* server owns session */ }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not start review.');
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer() {
    if (!session || !current || busy) return;
    setBusy(true); setError('');
    try {
      await workflow(
        `/review/sessions/${session.id}/items/${current.id}/answer`,
        { response: answer, selectedIds: selected, expectedRevision: session.revision },
        `review:${session.id}`,
      );
      const next = await learningApi.getReviewSession(session.id);
      setSession(next);
      setAnswer('');
      setSelected([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not submit answer.');
    } finally {
      setBusy(false);
    }
  }

  async function submitConfidence(confidence: ReviewConfidence) {
    if (!session || !current || busy) return;
    setBusy(true); setError('');
    try {
      const next = await learningApi.submitReviewConfidence(session.id, current.id, confidence, session.revision);
      setSession(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save confidence.');
    } finally {
      setBusy(false);
    }
  }

  async function skip() {
    if (!session || !current || busy) return;
    setBusy(true); setError('');
    try {
      setSession(await learningApi.skipReviewItem(session.id, current.id, session.revision));
      setAnswer('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not skip.');
    } finally {
      setBusy(false);
    }
  }

  async function remediate() {
    if (!session || !current || busy) return;
    setBusy(true); setError('');
    try {
      setSession(await learningApi.remediateReviewItem(session.id, current.id, session.revision));
      setAnswer('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not open remediation.');
    } finally {
      setBusy(false);
    }
  }

  async function complete() {
    if (!session || busy) return;
    setBusy(true); setError('');
    try {
      setSession(await learningApi.completeReviewSession(session.id, session.revision));
      await loadDash();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not complete review.');
    } finally {
      setBusy(false);
    }
  }

  async function askTutor() {
    if (!session || !current || busy) return;
    setBusy(true); setError('');
    try {
      const payload = await learningApi.askTutorFromReview(session.id, current.id);
      if (payload.sessionId) openChatSession(payload.sessionId);
      window.dispatchEvent(new CustomEvent<ReviewAskTutorDetail>(REVIEW_ASK_TUTOR_EVENT, {
        detail: {
          prompt: payload.prompt,
          context: payload.context,
          returnReviewSessionId: payload.returnReviewSessionId,
          chatSessionId: payload.sessionId,
        },
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not open chat.');
    } finally {
      setBusy(false);
    }
  }

  if (loading && !session) {
    return <section className={styles.page} aria-busy="true" aria-label="Review"><div className={styles.skeleton} /><div className={styles.skeleton} /><div className={styles.skeleton} /></section>;
  }

  if (session && session.status !== 'completed') {
    const index = session.items.findIndex(item => item.id === current?.id);
    const progress = `${Math.max(1, index + 1)} / ${session.itemCount}`;
    const attempt = current?.attempt as { status?: string; feedback?: string; correctness?: string; confidence?: string; idealAnswer?: string; response?: string; needsRemediation?: boolean } | null | undefined;
    const awaitingConfidence = attempt && attempt.correctness && !attempt.confidence && attempt.status !== 'evaluation_failed' && attempt.status !== 'skipped';
    const showFeedback = attempt && (attempt.status === 'evaluated' || attempt.status === 'evaluation_failed');

    return <section className={styles.page} aria-label="Review session">
      <header className={styles.sessionHeader}>
        <div><span className={styles.meta}>REVIEW</span><h1>Review</h1></div>
        <span className={styles.progress}>{progress}</span>
      </header>

      {current?.remediation ? <aside className={styles.remediation} aria-label="Short refresher">
        <strong>{current.remediation.heading}</strong>
        <RichContent body={current.remediation.body} />
        <p className={styles.hint}>Now try retrieving it again.</p>
      </aside> : null}

      {current ? <AnimatePresence mode="wait">
        <motion.article
          key={current.id + (current.status || '')}
          className={styles.card}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
        >
          <div className={styles.conceptRow}>
            <strong>{current.conceptTitle}</strong>
            {current.dueReason ? <span>{current.dueReason}</span> : null}
          </div>
          <p className={styles.prompt}>{current.prompt}</p>

          {!showFeedback ? <>
            {current.options?.length ? <div className={styles.options} role="group" aria-label="Answer choices">
              {current.options.map(option => (
                <button type="button" key={option.id} className={selected.includes(option.id) ? styles.optionOn : styles.option}
                  disabled={busy} onClick={() => setSelected(selected.includes(option.id) ? [] : [option.id])}>{option.label}</button>
              ))}
            </div> : <label className={styles.answerLabel}>
              <span className="sr-only">Your answer</span>
              <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={5} maxLength={8000}
                placeholder="Retrieve what you remember…" disabled={busy} aria-label="Your answer" />
            </label>}
            <div className={styles.actions}>
              <Button disabled={busy || (!answer.trim() && !selected.length)} onClick={() => void submitAnswer()}>Submit answer</Button>
              <Button variant="ghost" disabled={busy} onClick={() => void skip()}>Skip</Button>
            </div>
          </> : <>
            {attempt?.response ? <div className={styles.feedbackBlock}><span>Your answer</span><p>{String(attempt.response)}</p></div> : null}
            <div className={styles.feedbackBlock} role="status">
              <span>Tutor evaluation</span>
              <RichContent body={String(attempt?.feedback || '')} />
              {attempt?.idealAnswer && attempt.status === 'evaluated' ? <details><summary>Show explanation</summary><RichContent body={String(attempt.idealAnswer)} /></details> : null}
            </div>
            {awaitingConfidence ? <fieldset className={styles.confidence}>
              <legend>How confident were you?</legend>
              {CONFIDENCE.map(option => (
                <label key={option.id}><input type="radio" name="confidence" value={option.id} disabled={busy}
                  onChange={() => void submitConfidence(option.id)} />{option.label}</label>
              ))}
            </fieldset> : null}
            {!awaitingConfidence && attempt?.status === 'evaluated' ? <div className={styles.actions}>
              {(attempt.correctness === 'incorrect' || attempt.needsRemediation) && !current.remediation
                ? <Button variant="outline" disabled={busy} onClick={() => void remediate()}>Short refresher</Button> : null}
              <Button variant="outline" disabled={busy} onClick={() => void askTutor()}>Ask Tutor</Button>
              <Button disabled={busy} onClick={() => {
                const nextIndex = session.currentIndex + 1;
                if (nextIndex >= session.itemCount) void complete();
                else setSession({ ...session, currentIndex: nextIndex });
              }}>Continue</Button>
            </div> : null}
            {attempt?.status === 'evaluation_failed' ? <div className={styles.actions}>
              <Button disabled={busy} onClick={() => { setAnswer(String(attempt.response || '')); void submitAnswer(); }}>Try again</Button>
            </div> : null}
          </>}
        </motion.article>
      </AnimatePresence> : null}

      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {busy ? <p className={styles.hint} role="status">Working…</p> : null}
    </section>;
  }

  if (session?.status === 'completed' && session.summary) {
    const summary = session.summary;
    return <section className={styles.page} aria-label="Review complete">
      <header><span className={styles.meta}>REVIEW COMPLETE</span><h1>Review complete</h1>
        <p>You reviewed {summary.reviewed} concepts.</p></header>
      <div className={styles.card}>
        {summary.strengthened?.length ? <div><strong>Strengthened</strong><ul>{summary.strengthened.map(item => <li key={item}>{item}</li>)}</ul></div> : null}
        {summary.improving?.length ? <div><strong>Improving</strong><ul>{summary.improving.map(item => <li key={item}>{item}</li>)}</ul></div> : null}
        {summary.needsPractice?.length ? <div><strong>Needs more practice</strong><ul>{summary.needsPractice.map(item => <li key={item}>{item}</li>)}</ul></div> : null}
        <p className={styles.hint}>{summary.message || "We'll adjust your next reviews automatically."}</p>
        <div className={styles.actions}>
          <Button onClick={() => { setSession(null); void loadDash(); onDone?.(); }}>Done</Button>
          {summary.needsPractice?.length ? <Button variant="outline" disabled={busy} onClick={() => { setSession(null); void start(false); }}>Review weak concepts</Button> : null}
        </div>
      </div>
    </section>;
  }

  return <section className={styles.page} aria-label="Review"><FlashcardLibraryEntry/>
    <header>
      <span className={styles.meta}>KEEP WHAT YOU LEARN</span>
      <h1>Review</h1>
      <p>Short retrieval practice, scheduled from what you have already learned.</p>
    </header>

    {dash?.preparing ? <p className={styles.hint} role="status">Your recent lesson is still being prepared for review.</p> : null}

    {dash?.empty ? <div className={styles.card}>
      <h2>Nothing to review yet</h2>
      <p>Learn something first and we will automatically build your review memory from it.</p>
      <Button onClick={onStartLearning}>Start learning <ArrowRight size={15} /></Button>
    </div> : null}

    {dash && !dash.empty ? <>
      {dash.unfinishedSessionId ? <div className={styles.resume} role="status">
        <span>You have an unfinished review.</span>
        <Button size="sm" disabled={busy} onClick={() => void start(false)}>Continue where you left off</Button>
      </div> : null}

      <div className={styles.hero}>
        <div>
          <h2>{dash.caughtUp ? "You're caught up" : "Today's review"}</h2>
          {dash.caughtUp
            ? <p>Nothing urgent to review. You can still do an optional mixed recall session.</p>
            : <p>{dash.dueCount + dash.weakCount + dash.newCount} concepts · ~{dash.estimatedMinutes || 5} minutes</p>}
          <ul className={styles.stats}>
            <li>{dash.dueCount} due for review</li>
            <li>{dash.weakCount} need reinforcement</li>
            <li>{dash.newCount} new recall</li>
          </ul>
          {dash.streakDays > 1 ? <p className={styles.streak}>{dash.streakDays}-day review streak</p> : null}
        </div>
        <div className={styles.launch}>
          <label>Session length
            <select value={length} onChange={e => setLength(e.target.value as typeof length)} aria-label="Review session length">
              <option value="quick">Quick · ~5 min</option>
              <option value="standard">Standard · ~10 min</option>
              <option value="deep">Deep · ~20 min</option>
            </select>
          </label>
          {dash.caughtUp
            ? <Button disabled={busy} onClick={() => void start(true)}>Do optional review</Button>
            : <Button disabled={busy} onClick={() => void start(false)}><RotateCcw size={15} /> Start review</Button>}
        </div>
      </div>

      {dash.needsAttention.length ? <section className={styles.section}>
        <h2>Needs attention</h2>
        <ul className={styles.list}>{dash.needsAttention.map(item => (
          <li key={item.conceptId}>
            <strong>{item.title}</strong>
            <span>{item.reason}</span>
            {item.lastReviewedAt ? <small>Reviewed {new Date(item.lastReviewedAt).toLocaleDateString()}</small> : null}
          </li>
        ))}</ul>
      </section> : null}

      {dash.recentlyStrengthened.length ? <section className={styles.section}>
        <h2>Recently strengthened</h2>
        <ul className={styles.chips}>{dash.recentlyStrengthened.map(item => (
          <li key={item.conceptId}><Check size={14} />{item.title}</li>
        ))}</ul>
      </section> : null}

      {dash.recentlyLearned.length ? <section className={styles.section}>
        <h2>Recently learned</h2>
        <ul className={styles.chips}>{dash.recentlyLearned.map(item => (
          <li key={item.conceptId}><BookOpen size={14} />{item.title}</li>
        ))}</ul>
      </section> : null}
    </> : null}

    {error ? <p className={styles.error} role="alert">{error}</p> : null}
  </section>;
}
