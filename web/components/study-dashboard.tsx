"use client";

import { useEffect, useState } from 'react';
import { ArrowRight, Bell, BookOpen, CalendarClock, ChevronRight, Flame, Layers, ListChecks, Plus, RotateCcw, Sparkles, type LucideIcon } from 'lucide-react';
import { learningApi, request, type CourseSummary, type ReviewDashboard } from '@/lib/api';
import { flashcardsApi, type FlashcardSummary } from '@/lib/flashcards-client';
import { calendarApi, dateKey, eventTime, wallInstant, type CalendarEvent } from '@/lib/calendar-client';
import { openWorkspaceFlashcards, openWorkspaceQuiz } from '@/lib/workspace-events';
import type { QuizHistoryItem } from './quiz-workspace';
import { CalendarAgenda } from './calendar/calendar-agenda';
import { RoutineControls } from './routine-controls';
import styles from './study-dashboard.module.css';

type NextUpSources = {
  quizzes: QuizHistoryItem[];
  flashcards: FlashcardSummary | null;
  review: ReviewDashboard | null;
  event: CalendarEvent | null;
  zone: string;
};
type NextUp = { kind: 'quiz' | 'flashcards' | 'review' | 'event' | 'start'; icon: LucideIcon; title: string; detail: string; action: string; run: () => void };

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const unfinished = (quiz: QuizHistoryItem) => quiz.status !== 'completed' && quiz.attempted < quiz.count;

/** The next calendar item still ahead of the learner today, if any. */
async function loadNextEventToday(zone: string): Promise<CalendarEvent | null> {
  const now = new Date(), day = dateKey(now, zone);
  const tomorrow = new Date(Date.parse(`${day}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const feed = await calendarApi.feed(wallInstant(`${day}T00:00`, zone), wallInstant(`${tomorrow}T00:00`, zone), zone);
  const time = (event: CalendarEvent) => Date.parse(event.temporal.start || event.temporal.dueAt || '') || 0;
  const ahead = feed.items.filter(event => {
    if (event.status === 'completed' || event.status === 'cancelled') return false;
    const t = event.temporal;
    if (t.mode === 'all_day' || t.dueDate) return (t.startDate || t.dueDate) === day;
    const end = Date.parse(t.end || t.start || t.dueAt || '');
    return Number.isFinite(end) && end >= now.getTime();
  });
  return ahead.sort((a, b) => time(a) - time(b))[0] || null;
}

export function StudyDashboard({ courses, onReview, onCourse, onAddCourse, onReminders, onStudy, onPrep, onCalendar = () => window.location.assign('/calendar') }: {
  courses: CourseSummary[]; onReview: () => void; onCourse: (id: string) => void;
  onAddCourse: () => void; onReminders: () => void; onStudy: () => void;
  onCalendar?: () => void;
  onClass: (id: string) => void; onPrep: (id: string, title: string) => void;
}) {
  const [sources, setSources] = useState<NextUpSources | null>(null);
  const [error, setError] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Each source settles independently so one unavailable service never hides the card.
    void Promise.allSettled([
      request<{ quizzes: QuizHistoryItem[] }>('/v1/quizzes?limit=25'),
      flashcardsApi.summary(),
      learningApi.getReviewDashboard(),
      loadNextEventToday(zone),
    ]).then(([quizzes, flashcards, review, event]) => {
      if (!live) return;
      setSources({
        quizzes: quizzes.status === 'fulfilled' ? quizzes.value.quizzes || [] : [],
        flashcards: flashcards.status === 'fulfilled' ? flashcards.value : null,
        review: review.status === 'fulfilled' ? review.value : null,
        event: event.status === 'fulfilled' ? event.value : null,
        zone,
      });
      setError(review.status === 'rejected');
    });
    return () => { live = false; };
  }, [retry]);
  const activeCourses = courses.filter(course => !course.archivedAt);
  const review = sources?.review ?? null;
  const due = review ? review.dueCount : null;
  /** One most-useful action: unfinished quiz, due cards, due concepts, today's next event, then a fresh start. */
  function pickNextUp({ quizzes, flashcards, review, event, zone }: NextUpSources): NextUp {
    const quiz = quizzes.find(unfinished);
    if (quiz) return { kind: 'quiz', icon: ListChecks, title: `Finish “${quiz.title}”`, detail: `You've answered ${quiz.attempted} of ${plural(quiz.count, 'question')}. Pick up where you left off.`, action: 'Resume quiz', run: () => openWorkspaceQuiz({ sessionId: quiz.sessionId, quizId: quiz.id, lessonNoteId: quiz.lessonNoteId || undefined, origin: quiz.origin === 'learn' ? 'learn' : 'ask' }) };
    if (flashcards && flashcards.dueCount > 0) return { kind: 'flashcards', icon: Layers, title: `${plural(flashcards.dueCount, 'flashcard')} ready`, detail: 'A quick pass now keeps these cards from slipping.', action: 'Review flashcards', run: () => openWorkspaceFlashcards({ view: 'library' }) };
    const concepts = review ? (review.dueCount || 0) + (review.weakCount || 0) : 0;
    if (review && concepts > 0) return { kind: 'review', icon: RotateCcw, title: `${plural(concepts, 'concept')} to review`, detail: review.weakCount > 0 ? `${review.dueCount || 0} due and ${review.weakCount} that need another look.` : 'Strengthen what you learned before it fades.', action: 'Start review', run: onReview };
    if (event) {
      const course = activeCourses.find(item => item.id === event.courseId);
      return { kind: 'event', icon: CalendarClock, title: event.title, detail: `${eventTime(event, zone)}${course ? ` · ${course.name}` : ''}. Get ready with your buddy.`, action: event.courseId ? 'Prepare' : 'Open calendar', run: () => event.courseId ? onPrep(event.courseId, event.title) : onCalendar() };
    }
    return { kind: 'start', icon: Sparkles, title: 'Start a new topic', detail: "You're all caught up. Explore something new or go deeper on a course.", action: 'Start learning', run: onStudy };
  }

  const next = sources ? pickNextUp(sources) : null;
  return <div className={styles.scroll}><section className={styles.dashboard} aria-label="Study dashboard">
    <header className={styles.header}><div><h1>Dashboard</h1><p>A little progress, every day. Choose where to pick up.</p></div><button type="button" className={styles.study} onClick={onStudy}><Sparkles size={16}/>Continue studying<ArrowRight size={15}/></button></header>
    <section className={styles.nextUp} aria-labelledby="dashboard-next-up" aria-busy={!next}>
      {next ? <>
        <span className={styles.nextIcon} aria-hidden="true"><next.icon size={22}/></span>
        <div className={styles.nextBody}>
          <span className="ol-eyebrow">Next up</span>
          <h2 id="dashboard-next-up">{next.title}</h2>
          <p>{next.detail}</p>
          {review && (review.streakDays > 0 || review.estimatedMinutes > 0) ? <p className={styles.nextMeta}>
            {review.streakDays > 0 ? <span><Flame size={14} aria-hidden="true"/>{plural(review.streakDays, 'day')} streak</span> : null}
            {review.estimatedMinutes > 0 ? <span>About {review.estimatedMinutes} min of review today</span> : null}
          </p> : null}
        </div>
        <button type="button" className={styles.nextAction} onClick={next.run} data-next-kind={next.kind}>{next.action}<ArrowRight size={15}/></button>
      </> : <div className={styles.nextBody}><span className="ol-eyebrow">Next up</span><h2 id="dashboard-next-up">Finding your next step…</h2><p role="status">Checking quizzes, cards and reviews.</p></div>}
    </section>
    <CalendarAgenda courses={activeCourses} onCalendar={onCalendar} onPrep={onPrep}/>
    <div className={styles.overview}>
      <article className={styles.review}><span className={styles.icon}><RotateCcw size={20}/></span><div><h2>Keep it fresh</h2><p>{error ? 'Your review count is unavailable right now.' : due === null ? 'Checking your review queue…' : due > 0 ? `${due} ${due === 1 ? 'concept is' : 'concepts are'} ready for another look.` : 'Nothing due right now. Explore your review library.'}</p></div><button type="button" className={styles.cardAction} onClick={onReview}>{due !== null && due > 0 ? 'Start review' : 'Open review'}<ArrowRight size={15}/></button>{error ? <button type="button" className={styles.retry} onClick={()=>setRetry(value=>value+1)}>Retry review count</button> : null}</article>
      <article className={styles.reminders}><span className={styles.icon}><Bell size={20}/></span><div><h2>Stay on track</h2><p>Check your reminders and upcoming commitments.</p></div><button type="button" className={styles.cardActionSecondary} onClick={onReminders}>Open reminders<ArrowRight size={15}/></button></article>
    </div>
    <section className={styles.courses}><div className={styles.sectionHeader}><h2>Your courses <span>{activeCourses.length}</span></h2><button type="button" onClick={onAddCourse}><Plus size={15}/>Add course</button></div>{activeCourses.length ? <div className={styles.courseGrid}>{activeCourses.map(course => <button type="button" className={styles.course} key={course.id} onClick={()=>onCourse(course.id)}><BookOpen size={18}/><div><h3>{course.name}</h3><p>{course.goal || 'Continue learning at your own pace.'}</p></div><ChevronRight size={16}/><div className={styles.progress}><progress max={100} value={Math.min(100,Math.max(0,course.roadmapProgress || 0))} aria-label={`${course.name} course progress`}/><span>{Math.round(course.roadmapProgress || 0)}%</span></div></button>)}</div> : <div className={styles.empty}><BookOpen size={24}/><h3>Make space for your next subject</h3><p>Add a course to bring your materials, notes, and study plans together.</p><button type="button" onClick={onAddCourse}>Add your first course<Plus size={15}/></button></div>}</section>
    <section className={styles.schedule}><RoutineControls/></section>
  </section></div>;
}
