"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { learningApi, request, type ModeTransitionSuggestion } from '@/lib/api';
import { cancelWorkflow, getQuiz, workflow, waitForJob, type Quiz } from '@/lib/learning-workflows';
import { AssessmentCard } from './assessment-card';
import { HypothesisPanel } from './hypothesis-panel';
import { openWorkspaceSource } from '@/lib/workspace-events';
import { ModeTransitionCard } from './mode-transition-card';
import styles from './quiz.module.css';
import { openWorkspaceQuiz, type WorkspaceQuizOpen } from '@/lib/workspace-events';
import { readSettingsPreferences, useSettingsPreferences } from '@/lib/settings-preferences';

export type QuizHistoryItem = { id: string; title: string; sessionId: string; lessonNoteId?: string | null; origin: string; status: string; count: number; attempted: number; score: number | null; assisted: number; skipped: number; dontKnow: number; contested: number; createdAt?: string; updatedAt?: string };

async function loadQuizHistory(lessonNoteId?: string): Promise<QuizHistoryItem[]> {
  const query = lessonNoteId ? `?lesson_note_id=${encodeURIComponent(lessonNoteId)}` : '';
  const result = await request<{ quizzes: QuizHistoryItem[] }>(`/v1/quizzes${query}`);
  return result.quizzes;
}

export function QuizWorkspace({ sessionId, conceptId, inline = false, compact = false, historyOnly = false, launch, quizId, onStartQuiz, onQuizChange, onReturn, onReviewInLearn, onCreateRepairNote }: { sessionId?: string | null; conceptId?: string; inline?: boolean; compact?: boolean; historyOnly?: boolean; launch?: WorkspaceQuizOpen | null; quizId?: string; onStartQuiz?: () => void; onQuizChange?: () => void; onReturn?: () => void; onReviewInLearn?: (suggestion: ModeTransitionSuggestion) => void; onCreateRepairNote?: (attemptId: string) => void }) {
  const reduceMotion = useAppReducedMotion();
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const startedLaunch = useRef<string | null>(null);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [saved, setSaved] = useState<QuizHistoryItem[]>([]);
  const settings = useSettingsPreferences();
  const [countOverride, setCountOverride] = useState<number | null>(null);
  const [difficultyOverride, setDifficultyOverride] = useState<string | null>(null);
  const [modeOverride, setModeOverride] = useState<'topic_drill' | 'timed_short_quiz' | null>(null);
  const [durationOverride, setDurationOverride] = useState<number | null>(null);
  const count = countOverride ?? (inline ? 1 : settings.quizCount);
  const difficulty = difficultyOverride ?? settings.quizDifficulty;
  const mode = modeOverride ?? settings.quizMode;
  const duration = durationOverride ?? settings.quizDurationMinutes * 60;
  const [now, setNow] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [gapSuggestion, setGapSuggestion] = useState<ModeTransitionSuggestion | null>(null);
  const scope = inline ? `inline:${sessionId}:${conceptId || 'current'}` : compact ? `quiz:${launch?.lessonNoteId || sessionId || 'panel'}` : 'quiz';
  useEffect(() => { if (launch?.id || quizId) headingRef.current?.focus({ preventScroll: true }); }, [launch?.id, quizId]);

  useEffect(() => {
    let sid = sessionId;
    try { sid ||= localStorage.getItem('forma-chat-session'); } catch { /* no session */ }
    if (!sid || !quiz) return;
    const currentConcept = conceptId || (quiz as unknown as { conceptIds?: string[] }).conceptIds?.[0];
    if (!currentConcept) return;
    let active = true;
    void learningApi.getTransitionGap(sid, currentConcept, quiz.title, 0).then(res => {
      if (active) setGapSuggestion(res.suggestion || null);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [quiz, sessionId, conceptId]);
  useEffect(() => {
    let active = true;
    async function restore() {
      if (historyOnly) {
        void loadQuizHistory().then(list => { if (active) setSaved(list); }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : 'Could not load quiz history.'); });
        return;
      }
      if (launch && !launch.quizId) {
        if (!inline) void loadQuizHistory(launch.lessonNoteId).then(list => { if (active) setSaved(list); }).catch(() => undefined);
        return;
      }
      try {
        const pending = localStorage.getItem(`forma-job:${scope}`);
        if (pending) { setBusy(true); const result = await waitForJob(pending, scope); if (result?.quizId) localStorage.setItem(`forma-${scope}`, result.quizId); }
        const id = historyOnly ? null : quizId || launch?.quizId || localStorage.getItem(`forma-${scope}`);
        if (id) { const found = await getQuiz(id); if (active) setQuiz(found); }
        if (!inline) { const list = await loadQuizHistory(launch?.lessonNoteId); if (active) setSaved(list); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : 'Could not restore this quiz.'); }
      finally { if (active) setBusy(false); }
    }
    void restore(); return () => { active = false; };
  }, [scope, inline, quizId, launch, historyOnly]);
  useEffect(() => {
    if (!launch || startedLaunch.current === launch.id) return;
    startedLaunch.current = launch.id;
    if (launch.quizId) {
      void getQuiz(launch.quizId).then(found => { setQuiz(found); localStorage.setItem(`forma-${scope}`, found.id); }).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not open this quiz.'));
      return;
    }
    let active = true;
    const create = async () => {
      setQuiz(null); setBusy(true); setError('');
      try {
        // Resolve Learn quizzes against the session's canonical study note so
        // stale or incomplete launch metadata cannot produce lesson_required
        // or invalid_lesson validation errors.
        const lessonNoteId = launch.origin === 'learn'
          ? (await learningApi.createStudyNote(launch.sessionId)).noteId
          : launch.lessonNoteId;
        const defaults = readSettingsPreferences();
        const result = await workflow('/quizzes', { sessionId: launch.sessionId, conceptIds: launch.conceptId ? [launch.conceptId] : [], count: defaults.quizCount, difficulty: defaults.quizDifficulty, origin: launch.origin, lessonNoteId, requestedTopic: launch.requestedTopic, sourceTransitionId: launch.sourceTransitionId, mode: defaults.quizMode, modeConfig: defaults.quizMode === 'timed_short_quiz' ? { duration_seconds: defaults.quizDurationMinutes * 60 } : {} }, scope, launch.id);
        if (!result?.quizId) throw new Error('The quiz was not created.');
        let current = await getQuiz(result.quizId);
        localStorage.setItem(`forma-${scope}`, current.id);
        if (active) setQuiz(current);
        onQuizChange?.();
        if (current.status === 'ready' && !current.current) {
          await workflow(`/quizzes/${current.id}/next`, { expectedRevision: current.revision }, scope, `quiz-first:${current.id}`);
          current = await getQuiz(current.id);
          if (active) setQuiz(current);
        }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : 'Could not prepare the quiz.'); }
      finally { if (active) setBusy(false); }
    };
    void create();
    return () => { active = false; };
  }, [launch, scope, onQuizChange]);
  useEffect(() => { const tick = () => setNow(Date.now()); const timer = window.setInterval(tick, 1000); const first = window.setTimeout(tick, 0); return () => { window.clearInterval(timer); window.clearTimeout(first); }; }, []);
  async function act(path: string, body: unknown) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await workflow(path, body, scope);
      const id = result?.quizId || quiz?.id;
      if (id) { setQuiz(await getQuiz(id)); try { localStorage.setItem(`forma-${scope}`, id); } catch { /* Server retains quiz. */ } }
      onQuizChange?.();
      if (path.endsWith('/challenges')) setNotice('Flag saved. This response is excluded from scoring and learning evidence while disputed.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Please try again.'); }
    finally { setBusy(false); }
  }
  async function start() {
    let sid = sessionId;
    try { sid ||= localStorage.getItem('forma-chat-session'); } catch { /* No current session. */ }
    if (!sid) { setError('Start a chat or choose a topic first, then launch a quiz.'); return; }
    let lessonNoteId = launch?.lessonNoteId;
    if (inline && !lessonNoteId) {
      try { lessonNoteId = (await learningApi.createStudyNote(sid)).noteId; }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'The lesson must be saved before starting a check.'); return; }
    }
    setBusy(true); setError('');
    try {
      const result = await workflow('/quizzes', { sessionId: sid, conceptIds: conceptId ? [conceptId] : [], count, difficulty, origin: lessonNoteId ? 'learn' : 'ask', lessonNoteId, requestedTopic: launch?.requestedTopic, mode, modeConfig: mode === 'timed_short_quiz' ? { duration_seconds: duration } : {} }, scope);
      if (!result?.quizId) throw new Error('The quiz was not created.');
      let current = await getQuiz(result.quizId);
      localStorage.setItem(`forma-${scope}`, current.id);
      setQuiz(current); onQuizChange?.();
      if (current.status === 'ready' && !current.current) {
        await workflow(`/quizzes/${current.id}/next`, { expectedRevision: current.revision }, scope, `quiz-first:${current.id}`);
        current = await getQuiz(current.id);
        setQuiz(current);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not prepare the quiz.'); }
    finally { setBusy(false); }
  }
  async function saveReviewChecklist() {
    let sid = sessionId;
    try { sid ||= localStorage.getItem('forma-chat-session'); } catch { /* No current session. */ }
    if (!sid || !quiz || busy) return;
    const weak = quiz.attempts.filter(attempt => attempt.score === null || attempt.score < 0.7).map(attempt => attempt.id);
    if (!weak.length) { setNotice('No gaps found — nothing to add to your study note.'); return; }
    setBusy(true); setError('');
    try {
      const link = sid ? await learningApi.getStudyNote(sid).catch(() => null) : null;
      const result = await workflow(`/sessions/${sid}/note-proposals`, { origin: 'quiz', attemptIds: weak, expectedNoteRevision: link?.revision ?? null }, `note-proposal:quiz:${quiz.id}`);
      setNotice(result?.status === 'applied' ? 'Review checklist added to your study note.' : 'Review checklist proposed — accept it from the chat.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The checklist could not be proposed.'); }
    finally { setBusy(false); }
  }
  const secondsLeft = quiz?.mode === 'timed_short_quiz' ? Math.max(0, Math.ceil((quiz.deadlineAt ? new Date(quiz.deadlineAt).getTime() - now : (quiz.remainingSeconds || 0) * 1000) / 1000)) : null;
  const timeExpired = secondsLeft === 0 && !!quiz?.deadlineAt;
  return <section className={inline || compact ? styles.inline : styles.page} aria-label={inline ? 'Understanding check' : 'Quiz workspace'}>
    <header><span className={styles.meta}>{inline ? 'CHECK YOUR UNDERSTANDING' : 'PRACTICE WITH PURPOSE'}</span><h1 ref={headingRef} tabIndex={-1}>{inline ? 'Try the idea' : 'Quiz'}</h1><p>Test the reasoning, then try it in a different situation.</p></header>
    {!quiz ? <div className={styles.card}>
      <h2>{inline ? 'One short check' : compact || historyOnly ? 'Your quizzes' : 'Quiz your recent learning'}</h2><p>{(compact || historyOnly) && !launch ? 'Start a quiz from chat, or resume one below.' : 'Questions use the reference material attached to your conversation.'}</p>
      {!inline && !compact && !historyOnly && <div className={styles.setup}><label>Questions<select value={count} onChange={e => setCountOverride(Number(e.target.value))}>{[1, 3, 5, 10].map(n => <option key={n}>{n}</option>)}</select></label><label>Difficulty<select value={difficulty} onChange={e => setDifficultyOverride(e.target.value)}>{['adaptive', 'foundational', 'standard', 'stretch'].map(d => <option key={d} value={d}>{d}</option>)}</select></label><label>Practice mode<select value={mode} onChange={e => setModeOverride(e.target.value as 'topic_drill' | 'timed_short_quiz')}><option value="topic_drill">Topic drill</option><option value="timed_short_quiz">Timed short quiz</option></select></label>{mode === 'timed_short_quiz' && <label>Time<select value={duration} onChange={e => setDurationOverride(Number(e.target.value))}>{[300,600,900,1200].map(seconds => <option key={seconds} value={seconds}>{seconds / 60} minutes</option>)}</select></label>}</div>}
      {historyOnly ? <Button onClick={onStartQuiz}>Start new quiz</Button> : !compact ? <Button disabled={busy} onClick={() => void start()}>Prepare quiz</Button> : null}
      {!inline && saved.map(q => <button className={styles.saved} key={q.id} disabled={busy} onClick={() => { setError(''); if (onReturn) { onReturn(); openWorkspaceQuiz({ quizId: q.id, sessionId: q.sessionId, lessonNoteId: q.lessonNoteId || undefined, origin: q.lessonNoteId ? 'learn' : 'ask' }); return; } if (q.lessonNoteId && !launch?.lessonNoteId) { openWorkspaceQuiz({ quizId: q.id, sessionId: q.sessionId, lessonNoteId: q.lessonNoteId, origin: 'learn' }); return; } void getQuiz(q.id).then(setQuiz).catch(e => setError(e.message)); }}>{q.title}<Badge variant="secondary">{q.status.replaceAll('_', ' ')} · {q.attempted}/{q.count}</Badge></button>)}
    </div> : <>
      <div className={styles.progress}><strong>{quiz.title}</strong><span>{quiz.summary.attempted} of {quiz.count} answered</span><div className={styles.progressTrack} aria-hidden="true"><motion.span initial={false} animate={{ width: `${(quiz.summary.attempted / quiz.count) * 100}%` }} transition={reduceMotion ? { duration: 0 } : { duration: 0.24, ease: 'easeOut' }} /></div>{quiz.mode === 'timed_short_quiz' && <span aria-live="polite">Time left {secondsLeft} seconds</span>}</div>
      {quiz.contextSource ? <p className={styles.meta}>This quiz uses your study context, which has not been independently verified.</p> : null}
      {quiz.challenges?.map(challenge => <div key={challenge.id} role="status" className={styles.card}>
        <strong>{challenge.status === 'resolved' ? 'Question review complete' : 'Question review pending'}</strong>
        <p>{challenge.explanation || 'Your response is saved and excluded while this question is reviewed.'}</p>
        {challenge.status !== 'resolved' && <Button variant="outline" disabled={busy} onClick={() => void act(`/challenges/${challenge.id}/review`, {})}>Review question</Button>}
      </div>)}
      {timeExpired && <div className={styles.card} role="status"><h2>Time is up</h2><p>Your saved work is still available, but this timed quiz no longer accepts answers.</p></div>}
      <AnimatePresence mode="wait">{quiz.current && quiz.status !== 'paused' && !timeExpired && <motion.div key={quiz.current.id} initial={reduceMotion ? false : { opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: -10 }} transition={{ duration: 0.2, ease: 'easeOut' }}><AssessmentCard item={quiz.current} busy={busy} attempt={quiz.attempts.find(a => a.id === quiz.current?.attemptId)}
        onAnswer={answer => void act(`/quizzes/${quiz.id}/attempts`, { ...answer, presentationId: quiz.current!.id, expectedRevision: quiz.revision })}
        onHint={() => void act(`/presentations/${quiz.current!.id}/hints`, {})}
        onChallenge={reason => void act(`/attempts/${quiz.current!.attemptId}/challenges`, { reason })} onCreateRepairNote={onCreateRepairNote} onOpenSource={openWorkspaceSource} /></motion.div>}</AnimatePresence>
      {gapSuggestion ? (
        <ModeTransitionCard
          suggestion={gapSuggestion}
          disabled={busy}
          onAccept={async () => {
            let sid = sessionId;
            try { sid ||= localStorage.getItem('forma-chat-session'); } catch { /* no session */ }
            if (onReviewInLearn) { onReviewInLearn(gapSuggestion); return; }
            if (sid) {
              await learningApi.recordTransitionInteraction(gapSuggestion.id, 'accept', 'learn', sid, gapSuggestion.modeRevision ?? undefined);
            }
            onReturn?.();
          }}
          onDismiss={async () => {
            let sid = sessionId;
            try { sid ||= localStorage.getItem('forma-chat-session'); } catch { /* no session */ }
            if (sid) {
              await learningApi.recordTransitionInteraction(gapSuggestion.id, 'dismiss', 'learn', sid, gapSuggestion.modeRevision ?? undefined);
            }
            setGapSuggestion(null);
          }}
        />
      ) : null}
      {quiz.status === 'completed' ? <div className={styles.card}><h2>Session complete</h2><p>{quiz.summary.score === null ? 'No scored answers yet.' : `${quiz.summary.score}% across ${quiz.summary.evaluated} evaluated answers.`}</p><p>{quiz.summary.assisted} with help · {quiz.summary.skipped} skipped · {quiz.summary.dontKnow} marked “I don’t know”</p><p className={styles.meta}>Practice score, not mastery. Questions adapt, so scores are not rankings.</p><div className={styles.actions}>{onReturn ? <Button variant="outline" onClick={onReturn}>Return to lesson</Button> : null}<Button variant="outline" disabled={busy} onClick={() => void saveReviewChecklist()}>Save review checklist</Button>{!compact ? <Button variant="ghost" onClick={() => { setQuiz(null); localStorage.removeItem(`forma-${scope}`); }}>New quiz</Button> : null}</div></div> : <div className={styles.actions}>
        {!timeExpired && quiz.status !== 'paused' && (!quiz.current || quiz.current.attemptId) && <Button disabled={busy} onClick={() => void act(`/quizzes/${quiz.id}/next`, { expectedRevision: quiz.revision })}>{quiz.current ? 'Next question' : 'Generate first question'}</Button>}
        {!timeExpired && <Button disabled={busy} variant="ghost" onClick={() => void act(`/quizzes/${quiz.id}/${quiz.status === 'paused' ? 'resume' : 'pause'}`, { expectedRevision: quiz.revision })}>{quiz.status === 'paused' ? 'Resume quiz' : 'Pause'}</Button>}
        {onReturn && <Button variant="outline" onClick={onReturn}>Return to Learn</Button>}
      </div>}
    </>}
    {quiz?.current?.attemptId && <HypothesisPanel conceptId={quiz.current.concept_id} refreshKey={quiz.current.attemptId} />}
    {busy && <div><p role="status">Saving and checking this activity… You can return to it later.</p><Button variant="ghost" onClick={() => void cancelWorkflow(scope).catch(cause => setError(cause.message))}>Stop</Button></div>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}

/** Practice is a structured part of a lesson, outside its learner-editable Markdown. */
export function LessonPractice({ noteId, sessionId, noteTitle, launch }: { noteId: string; sessionId: string; noteTitle: string; launch?: WorkspaceQuizOpen | null }) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [history, setHistory] = useState<QuizHistoryItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [localLaunch, setLocalLaunch] = useState<WorkspaceQuizOpen | null>(null);
  const [dismissedLaunchId, setDismissedLaunchId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const refreshHistory = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    let current = true;
    void loadQuizHistory(noteId).then(items => { if (current) setHistory(items); }).catch(cause => { if (current) setError(cause instanceof Error ? cause.message : 'Could not load lesson quizzes.'); });
    return () => { current = false; };
  }, [noteId, version]);
  useEffect(() => { if (launch?.lessonNoteId === noteId) sectionRef.current?.scrollIntoView({ block: 'start' }); }, [launch?.id, launch?.lessonNoteId, noteId]);
  const externalLaunch = launch?.lessonNoteId === noteId && launch.id !== dismissedLaunchId ? launch : null;
  const selectedLaunch = externalLaunch || (activeId ? null : localLaunch);
  const selectedQuizId = externalLaunch ? null : activeId;
  const showPlayer = Boolean(selectedLaunch || selectedQuizId);
  return <section ref={sectionRef} className={styles.lessonPractice} aria-label="Lesson practice">
    <div className={styles.lessonPracticeHeader}><div><span className={styles.meta}>PRACTICE</span><h2>Quiz this lesson</h2><p>Your answers and feedback stay linked to this lesson.</p></div><Button type="button" size="sm" onClick={() => { setActiveId(null); setLocalLaunch({ id: crypto.randomUUID(), sessionId, lessonNoteId: noteId, requestedTopic: noteTitle, origin: 'learn' }); }}>New quiz</Button></div>
    {history.length ? <div className={styles.lessonHistory}>{history.map(item => <button type="button" key={item.id} onClick={() => { setLocalLaunch(null); setActiveId(item.id); }}><strong>{item.title}</strong><span>{item.status.replaceAll('_', ' ')} · {item.attempted}/{item.count} answered{item.score === null ? '' : ` · ${item.score}% practice score`}{item.assisted ? ` · ${item.assisted} assisted` : ''}{item.skipped ? ` · ${item.skipped} skipped` : ''}{item.contested ? ` · ${item.contested} disputed` : ''}</span></button>)}</div> : <p className={styles.meta}>No quizzes for this lesson yet.</p>}
    {showPlayer ? <QuizWorkspace key={selectedLaunch?.id || selectedQuizId || noteId} sessionId={sessionId} compact launch={selectedLaunch} quizId={selectedQuizId || undefined} onQuizChange={refreshHistory} onReturn={() => { setActiveId(null); setLocalLaunch(null); if (launch) setDismissedLaunchId(launch.id); }} /> : null}
    {error ? <p role="alert" className={styles.meta}>{error}</p> : null}
  </section>;
}
