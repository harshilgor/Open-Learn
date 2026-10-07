"use client";

import { useEffect, useState } from 'react';
import { ArrowUpRight, Bell, BookOpen, Plus, RotateCcw, Sparkles } from 'lucide-react';
import { learningApi, type CourseSummary } from '@/lib/api';
import { BuddyToday } from './buddy-today';
import styles from './study-dashboard.module.css';

export function StudyDashboard({ courses, onReview, onCourse, onAddCourse, onReminders, onStudy, onClass, onPrep }: {
  courses: CourseSummary[]; onReview: () => void; onCourse: (id: string) => void;
  onAddCourse: () => void; onReminders: () => void; onStudy: () => void;
  onClass: (id: string) => void; onPrep: (id: string, title: string) => void;
}) {
  const [due, setDue] = useState<number | null>(null);
  const [error, setError] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    learningApi.getReviewDashboard().then(result => { if (live) { setDue(result.dueCount); setError(false); } }).catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [retry]);
  const activeCourses = courses.filter(course => !course.archivedAt);
  return <div className={styles.scroll}><section className={styles.dashboard} aria-label="Study dashboard">
    <header className={styles.header}><div><span className={styles.eyebrow}>YOUR LEARNING, AT A GLANCE</span><h1>Dashboard</h1><p>A little progress, every day. Choose where to pick up.</p></div><button type="button" className={styles.study} onClick={onStudy}><Sparkles size={16}/>Continue studying<ArrowUpRight size={15}/></button></header>
    <div className={styles.overview}>
      <article className={styles.review}><span className={styles.icon}><RotateCcw size={20}/></span><div><h2>Keep it fresh</h2><p>{error ? 'Your review count is unavailable right now.' : due === null ? 'Checking your review queue…' : due > 0 ? `${due} ${due === 1 ? 'concept is' : 'concepts are'} ready for another look.` : 'Nothing due right now. Explore your review library.'}</p></div><button type="button" onClick={onReview}>{due !== null && due > 0 ? 'Start review' : 'Open review'}<ArrowUpRight size={15}/></button>{error ? <button type="button" className={styles.retry} onClick={()=>setRetry(value=>value+1)}>Retry review count</button> : null}</article>
      <button type="button" className={styles.reminders} onClick={onReminders}><Bell size={20}/><h2>Stay on track</h2><p>Check your reminders and upcoming commitments.</p><span>Open reminders<ArrowUpRight size={15}/></span></button>
    </div>
    <section className={styles.courses}><div className={styles.sectionHeader}><h2>Your courses <span>{activeCourses.length}</span></h2><button type="button" onClick={onAddCourse}><Plus size={15}/>Add course</button></div>{activeCourses.length ? <div className={styles.courseGrid}>{activeCourses.map(course => <button type="button" className={styles.course} key={course.id} onClick={()=>onCourse(course.id)}><BookOpen size={18}/><div><h3>{course.name}</h3><p>{course.goal || 'Continue learning at your own pace.'}</p></div><ArrowUpRight size={15}/><div className={styles.progress}><progress max={100} value={Math.min(100,Math.max(0,course.roadmapProgress || 0))} aria-label={`${course.name} course progress`}/><span>{Math.round(course.roadmapProgress || 0)}%</span></div></button>)}</div> : <div className={styles.empty}><BookOpen size={24}/><h3>Make space for your next subject</h3><p>Add a course to bring your materials, notes, and study plans together.</p><button type="button" onClick={onAddCourse}>Add your first course<Plus size={15}/></button></div>}</section>
    <section className={styles.schedule}><h2>Coming up</h2><BuddyToday scheduleOnly courses={activeCourses} due={0} onCourse={onCourse} onReview={onReview} onAdd={onAddCourse} onReminders={onReminders} onClass={onClass} onPrep={onPrep}/></section>
  </section></div>;
}
