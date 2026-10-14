"use client";

import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, GraduationCap, Layers, ListChecks, RotateCcw, Target } from 'lucide-react';
import { learningApi, request, type ReviewDashboard } from '@/lib/api';
import { flashcardsApi, type FlashcardSummary } from '@/lib/flashcards-client';
import { openReview, openWorkspaceFlashcards, openWorkspaceQuiz } from '@/lib/workspace-events';
import type { QuizHistoryItem } from './quiz-workspace';
import styles from './workspace-panel.module.css';
import own from './practice-overview.module.css';

type Overview = { quizzes: QuizHistoryItem[]; flashcards: FlashcardSummary | null; review: ReviewDashboard | null };

const unfinished = (quiz: QuizHistoryItem) => quiz.status !== 'completed' && quiz.attempted < quiz.count;
const when = (value?: string) => value ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value)) : '';

/**
 * The top of the Practice tool: unfinished work first, then what is due, then history.
 * Each source loads independently so one unavailable service never hides the others.
 */
export function PracticeOverview() {
  const [data, setData] = useState<Overview>({ quizzes: [], flashcards: null, review: null });
  const [loaded, setLoaded] = useState(false);
  const load = useCallback(async () => {
    const [quizzes, flashcards, review] = await Promise.allSettled([
      request<{ quizzes: QuizHistoryItem[] }>('/v1/quizzes?limit=25'),
      flashcardsApi.summary(),
      learningApi.getReviewDashboard(),
    ]);
    setData({
      quizzes: quizzes.status === 'fulfilled' ? quizzes.value.quizzes : [],
      flashcards: flashcards.status === 'fulfilled' ? flashcards.value : null,
      review: review.status === 'fulfilled' ? review.value : null,
    });
    setLoaded(true);
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);

  const openQuizzes = data.quizzes.filter(unfinished).slice(0, 4);
  const openCardSessions = (data.flashcards?.sessions || []).filter(session => session.status !== 'completed' && session.cursor < session.total).slice(0, 2);
  const cardsDue = data.flashcards?.dueCount || 0;
  const conceptsDue = (data.review?.dueCount || 0) + (data.review?.weakCount || 0);
  // Class quizzes get their own shelf; anything already under Continue or the shelf is not repeated below.
  const fromClass = data.quizzes.filter(quiz => quiz.origin === 'in_class' && !openQuizzes.includes(quiz)).slice(0, 4);
  const weakCount = data.review?.weakCount || 0;
  const history = data.quizzes.filter(quiz => !unfinished(quiz) && !fromClass.includes(quiz)).slice(0, 5);
  const hasContinue = openQuizzes.length > 0 || openCardSessions.length > 0 || !!data.review?.unfinishedSessionId;

  if (!loaded) return <div className={styles.practiceSkeleton} aria-hidden="true"><span/><span/></div>;
  return <>
    {hasContinue ? <section className={styles.practiceSection} aria-labelledby="practice-continue">
      <h3 id="practice-continue">Continue</h3>
      <div className={styles.practiceList}>
        {openQuizzes.map(quiz => <button type="button" key={quiz.id} className={styles.practiceRow} onClick={() => openWorkspaceQuiz({ sessionId: quiz.sessionId, quizId: quiz.id, origin: 'ask' })}>
          <span className={styles.practiceIcon} data-kind="quiz"><ListChecks size={16}/></span>
          <span className={styles.practiceRowMain}><strong>{quiz.title || 'Quiz'}</strong><small>{quiz.attempted} of {quiz.count} answered{quiz.origin === 'in_class' ? ' · From class' : ''}{quiz.createdAt ? ` · ${when(quiz.createdAt)}` : ''}</small><span className={styles.practiceProgress} aria-hidden="true"><span style={{ width: `${Math.round(quiz.attempted / Math.max(1, quiz.count) * 100)}%` }}/></span></span>
          <span className={styles.practiceAction}>Resume<ChevronRight size={15}/></span>
        </button>)}
        {openCardSessions.map(session => <button type="button" key={session.id} className={styles.practiceRow} onClick={() => openWorkspaceFlashcards({ view: 'review', reviewSessionId: session.id })}>
          <span className={styles.practiceIcon} data-kind="cards"><Layers size={16}/></span>
          <span className={styles.practiceRowMain}><strong>Flashcard review</strong><small>{session.cursor} of {session.total} cards</small><span className={styles.practiceProgress} aria-hidden="true"><span style={{ width: `${Math.round(session.cursor / Math.max(1, session.total) * 100)}%` }}/></span></span>
          <span className={styles.practiceAction}>Resume<ChevronRight size={15}/></span>
        </button>)}
        {data.review?.unfinishedSessionId ? <button type="button" className={styles.practiceRow} onClick={() => openReview({ sessionId: data.review!.unfinishedSessionId! })}>
          <span className={styles.practiceIcon} data-kind="review"><RotateCcw size={16}/></span>
          <span className={styles.practiceRowMain}><strong>Concept review</strong><small>Pick up where you left off</small></span>
          <span className={styles.practiceAction}>Resume<ChevronRight size={15}/></span>
        </button> : null}
      </div>
    </section> : null}

    <section className={styles.practiceSection} aria-labelledby="practice-due">
      <h3 id="practice-due">Due today</h3>
      <div className={styles.practiceDue}>
        <button type="button" onClick={() => openWorkspaceFlashcards({ view: 'library' })}>
          <span className={styles.practiceIcon} data-kind="cards"><Layers size={16}/></span>
          <span><strong>{cardsDue}</strong><small>{cardsDue === 1 ? 'flashcard' : 'flashcards'}</small></span>
        </button>
        <button type="button" onClick={() => openReview()}>
          <span className={styles.practiceIcon} data-kind="review"><RotateCcw size={16}/></span>
          <span><strong>{conceptsDue}</strong><small>{conceptsDue === 1 ? 'concept to review' : 'concepts to review'}</small></span>
        </button>
      </div>
      {!cardsDue && !conceptsDue ? <p className={styles.practiceHint}>You’re caught up. Make a quiz or flashcards below to keep going.</p> : null}
    </section>

    {weakCount > 0 ? <section className={styles.practiceSection} aria-labelledby="practice-weak">
      <h3 id="practice-weak">Weak spots</h3>
      <div className={styles.practiceList}>
        <button type="button" className={styles.practiceRow} onClick={() => openReview()}>
          <span className={`${styles.practiceIcon} ${own.icon}`} data-kind="weak"><Target size={16}/></span>
          <span className={styles.practiceRowMain}><strong>{weakCount} {weakCount === 1 ? 'concept needs' : 'concepts need'} another look</strong><small>A short concept review targets what you missed</small></span>
          <span className={styles.practiceAction}>Review<ChevronRight size={15}/></span>
        </button>
      </div>
    </section> : null}

    {fromClass.length ? <section className={styles.practiceSection} aria-labelledby="practice-class">
      <h3 id="practice-class">From your classes</h3>
      <div className={styles.practiceList}>{fromClass.map(quiz => <button type="button" key={quiz.id} className={styles.practiceRow} onClick={() => openWorkspaceQuiz({ sessionId: quiz.sessionId, quizId: quiz.id, origin: 'ask' })}>
        <span className={`${styles.practiceIcon} ${own.icon}`} data-kind="class"><GraduationCap size={16}/></span>
        <span className={styles.practiceRowMain}><strong>{quiz.title || 'Class quiz'}</strong><small>{quiz.score !== null ? `Score ${quiz.score}%` : quiz.attempted ? `${quiz.attempted} of ${quiz.count} answered` : `${quiz.count} ${quiz.count === 1 ? 'question' : 'questions'}`}{quiz.createdAt ? ` · ${when(quiz.createdAt)}` : ''}</small></span>
        <ChevronRight size={15} className={styles.practiceChevron}/>
      </button>)}</div>
    </section> : null}

    {history.length ? <details className={styles.practiceHistory}>
      <summary>Recent quizzes <small>{history.length}</small></summary>
      <div className={styles.practiceList}>{history.map(quiz => <button type="button" key={quiz.id} className={styles.practiceRow} onClick={() => openWorkspaceQuiz({ sessionId: quiz.sessionId, quizId: quiz.id, origin: 'ask' })}>
        <span className={styles.practiceIcon} data-kind="quiz"><ListChecks size={16}/></span>
        <span className={styles.practiceRowMain}><strong>{quiz.title || 'Quiz'}</strong><small>{quiz.score === null ? `${quiz.attempted} answered` : `Score ${quiz.score}%`}{quiz.createdAt ? ` · ${when(quiz.createdAt)}` : ''}</small></span>
        <ChevronRight size={15} className={styles.practiceChevron}/>
      </button>)}</div>
    </details> : null}
  </>;
}
