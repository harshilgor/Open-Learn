'use client';

import { useState } from 'react';
import { ArrowUpRight, BookOpen, FolderOpen, Plus, Search } from 'lucide-react';
import type { CourseSummary } from '@/lib/api';
import styles from './course-index.module.css';

export function CourseIndex({ courses, buddyForCourse, onAddCourse, onCourse }: {
  courses: CourseSummary[];
  buddyForCourse: (courseId: string) => string;
  onAddCourse: () => void;
  onCourse: (courseId: string) => void;
}) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleCourses = normalizedQuery
    ? courses.filter(course => `${course.name} ${course.goal} ${buddyForCourse(course.id)}`.toLocaleLowerCase().includes(normalizedQuery))
    : courses;

  return <div className={styles.scroll}>
    <section className={styles.page} aria-labelledby="courses-title">
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>YOUR LEARNING LIBRARY</span>
          <h1 id="courses-title">Courses</h1>
          <p>Keep your chats, notes, materials, and class sessions together by subject.</p>
        </div>
        <button type="button" className={styles.addButton} onClick={onAddCourse}><Plus size={17}/>Add course</button>
      </header>

      {courses.length ? <>
        <div className={styles.listHeader}>
          <h2>Your courses <span>{courses.length}</span></h2>
          <label className={styles.search}>
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Search courses</span>
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search courses" />
            {query ? <button type="button" onClick={() => setQuery('')} aria-label="Clear course search">×</button> : null}
          </label>
        </div>
        {visibleCourses.length ? <div className={styles.grid}>
          {visibleCourses.map(course => {
            const progress = Math.max(0, Math.min(100, course.roadmapProgress || 0));
            return <button type="button" className={styles.course} key={course.id} onClick={() => onCourse(course.id)}>
              <span className={styles.courseIcon}><BookOpen size={19}/></span>
              <span className={styles.courseBody}>
                <span className={styles.courseTitle}>{course.name}<ArrowUpRight size={15}/></span>
                <span className={styles.goal}>{course.goal || 'Your learning space for this subject.'}</span>
                <span className={styles.meta}>
                  <span>{course.sessionCount} {course.sessionCount === 1 ? 'chat' : 'chats'}</span>
                  <span>{course.materialCount} {course.materialCount === 1 ? 'material' : 'materials'}</span>
                  <span>{course.noteCount} {course.noteCount === 1 ? 'note' : 'notes'}</span>
                </span>
                <span className={styles.progressRow}>
                  <span className={styles.progressTrack}><span style={{ width: `${progress}%` }}/></span>
                  <span>{Math.round(progress)}%</span>
                </span>
                <span className={styles.buddy}><span className={styles.buddyDot}/> {buddyForCourse(course.id)}</span>
              </span>
            </button>;
          })}
        </div> : <div className={styles.noResults}>
          <p>No courses match “{query}”.</p>
          <button type="button" onClick={() => setQuery('')}>Clear search</button>
        </div>}
      </> : <div className={styles.empty}>
        <span className={styles.emptyIcon}><FolderOpen size={25}/></span>
        <span className={styles.eyebrow}>A FRESH PLACE TO START</span>
        <h2>Make room for your next subject</h2>
        <p>Create a course to bring its study chats, class notes, materials, and practice together.</p>
        <button type="button" className={styles.emptyButton} onClick={onAddCourse}><Plus size={16}/>Create your first course</button>
      </div>}
    </section>
  </div>;
}
