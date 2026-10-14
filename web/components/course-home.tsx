'use client';
import { startClass as requestClassStart } from '@/lib/class-events';

import {FlashcardLibraryEntry} from './flashcard-workspace';
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import styles from './course-dashboard.module.css';
import { CourseAssetPreview } from './course-asset-preview';
import { CalendarRange, FileText, FolderClosed, LayoutDashboard, Library, ListChecks, Loader2, MessageSquare, Mic, MoreHorizontal, NotebookPen, Plus, Search, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseStudyPlanner, type Task } from '@/components/course-study-planner';
import { CanvasConnection } from '@/components/canvas-connection';
import { CourseBuddy, useBuddies } from './buddies';
import type { QuizHistoryItem } from './quiz-workspace';
import { MaterialLibrary } from './material-library';
import {openClassWorkspace} from '@/lib/in-class';
import { learningApi, request, type ChatSessionSummary, type CoursePublic, type WorkspaceNoteSummary } from '@/lib/api';

type CourseSection = 'overview' | 'materials' | 'classes' | 'notes' | 'practice' | 'plan';
const SECTIONS: { id: CourseSection; label: string; icon: typeof FileText }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'materials', label: 'Materials', icon: Library },
  { id: 'classes', label: 'Classes', icon: Mic },
  { id: 'notes', label: 'Notes', icon: NotebookPen },
  { id: 'practice', label: 'Practice', icon: ListChecks },
  { id: 'plan', label: 'Study plan', icon: CalendarRange },
];

interface CourseHomeProps {
  courseId: string;
  onOpenSession: (sessionId: string) => void;
  onNewSession: () => void;
  onOpenNote: (noteId: string) => void;
  onQuizSession: (sessionId: string) => void;
  onUpdated: () => void;
  onDeleted: () => void;
  onLaunchTask: (task: Task) => Promise<string>;
  onLaunchReady: (task: Task, sessionId: string, revision: number) => void;
  onStartClass?:()=>void;
  onSavedQuiz?:(quiz:QuizHistoryItem)=>void;
}

export function CourseHome({ courseId, onOpenSession, onNewSession, onOpenNote, onQuizSession, onUpdated, onDeleted, onLaunchTask, onLaunchReady, onStartClass, onSavedQuiz }: CourseHomeProps) {
  const buddies=useBuddies();
  const [quizzes,setQuizzes]=useState<QuizHistoryItem[]>([]);
  const [quizError,setQuizError]=useState('');
  const [section,setSection]=useState<CourseSection>('overview');
  const [course, setCourse] = useState<CoursePublic | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [allSessions, setAllSessions] = useState<ChatSessionSummary[]>([]);
  const [allNotes, setAllNotes] = useState<WorkspaceNoteSummary[]>([]);
  const [picker, setPicker] = useState<'chats' | 'notes' | null>(null);
  const [search, setSearch] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [courseData, sessionData, noteData] = await Promise.all([
        learningApi.getCourse(courseId),
        learningApi.listCourseSessions(courseId, { limit: 200 }),
        learningApi.listCourseNotes(courseId),
      ]);
      setCourse(courseData);
      setName(courseData.name);
      setSessions(sessionData.sessions);
      setNotes(noteData.notes);
      setError('');
      try{const result=await request<{quizzes:QuizHistoryItem[]}>('/v1/quizzes');const ids=new Set(sessionData.sessions.map(item=>item.id));setQuizzes(result.quizzes.filter(quiz=>ids.has(quiz.sessionId)));setQuizError('');}catch{setQuizError('Saved quizzes could not load. Retry by reopening this course.');}
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load this course.');
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => { const timer = window.setTimeout(() => { setCourse(null); setPicker(null); void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  async function openPicker(kind: 'chats' | 'notes') {
    setSearch('');
    if (picker === kind) { setPicker(null); return; }
    setBusyId('picker');
    try {
      if (kind === 'chats') setAllSessions((await learningApi.listChatSessions({limit: 200})).sessions);
      else setAllNotes(await learningApi.listWorkspaceNotes());
      setPicker(kind);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load available items.'); }
    finally { setBusyId(null); }
  }

  async function addChat(sessionId: string) {
    setBusyId(sessionId);
    setError('');
    try {
      await learningApi.addCourseSession(courseId, sessionId);
      setPicker(null);
      await load();
      onUpdated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not add this chat.'); }
    finally { setBusyId(null); }
  }

  async function removeChat(sessionId: string) {
    setBusyId(sessionId);
    setError('');
    try {
      await learningApi.removeCourseSession(courseId, sessionId);
      await load();
      onUpdated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not remove this chat.'); }
    finally { setBusyId(null); }
  }

  async function setNoteCourse(noteId: string, remove = false) {
    setBusyId(noteId);
    setError('');
    try {
      const note = await learningApi.getWorkspaceNote(noteId);
      const frontmatter = { ...note.frontmatter };
      frontmatter.courseId = null;
      frontmatter.course_id = remove ? null : courseId;
      await learningApi.updateWorkspaceNote(noteId, {
        title: note.title, body: note.body, frontmatter, expectedRevision: note.revision,
      });
      setPicker(null);
      await load();
      onUpdated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update this note.'); }
    finally { setBusyId(null); }
  }

  async function renameCourse() {
    const trimmed = name.trim();
    if (!trimmed || !course || busyId) return;
    setBusyId('rename');
    try {
      const updated = await learningApi.updateCourse(courseId, { name: trimmed });
      setCourse(updated);
      setEditing(false);
      onUpdated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not rename this course.'); }
    finally { setBusyId(null); }
  }

  async function deleteCourse() {
    if (!course || !window.confirm(`Delete “${course.name}”? Its chats and notes will stay in your workspace.`)) return;
    setBusyId('delete');
    try { await learningApi.deleteCourse(courseId); onDeleted(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not delete this course.'); }
    finally { setBusyId(null); }
  }

  const availableChats = allSessions.filter(item => item.courseId !== courseId && !sessions.some(current => current.id === item.id) && item.title.toLowerCase().includes(search.toLowerCase()));
  const availableNotes = allNotes.filter(item => !notes.some(current => current.id === item.id) && item.title.toLowerCase().includes(search.toLowerCase()));
  const recentSession = sessions.reduce<ChatSessionSummary | null>((latest, item) => !latest || Date.parse(item.updatedAt) > Date.parse(latest.updatedAt) ? item : latest, null);

  const buddyId = buddies.snapshot?.courses[courseId] || buddies.snapshot?.defaultBuddyId;
  const buddyName = buddies.snapshot?.profiles.find(profile => profile.id === buddyId)?.name || 'Buddy';
  const courseClasses = buddies.snapshot?.classes.filter(item => item.courseId === courseId) ?? [];
  const materialCount = course?.summary?.materialCount;
  const meta = [
    `${sessions.length} ${sessions.length === 1 ? 'chat' : 'chats'}`,
    `${notes.length} ${notes.length === 1 ? 'note' : 'notes'}`,
    ...(typeof materialCount === 'number' ? [`${materialCount} ${materialCount === 1 ? 'material' : 'materials'}`] : []),
    ...(courseClasses.length ? [`${courseClasses.length} ${courseClasses.length === 1 ? 'class' : 'classes'}`] : []),
  ];
  const askBuddy = () => { if (buddyId) buddies.select(buddyId); onNewSession(); };
  /** Class mode listens for this request; the existing recorder setup remains the fallback when nothing handles it. */
  const startClass = () => {
    const handled = requestClassStart(courseId);
    if (!handled) onStartClass?.();
  };
  const sectionNav = <nav aria-label="Course sections" className={styles.sectionNav}>
    {SECTIONS.map(item => <button key={item.id} type="button" className={styles.sectionLink} aria-current={section === item.id ? 'page' : undefined} onClick={() => setSection(item.id)}><item.icon size={16} aria-hidden="true" />{item.label}</button>)}
  </nav>;

  return <section className={`course-folder ${styles.dashboard}`} aria-label="Course dashboard">
    {loading && !course ? <div className="course-folder-state"><Loader2 size={18} className="animate-spin" />Loading course…</div> : null}
    {error ? <p className="course-folder-error" role="alert">{error}</p> : null}
    {course ? <div className="course-folder-inner">
      <header className={`course-folder-header ${styles.header}`}>
        <div className="course-folder-title"><span className="course-folder-icon"><FolderClosed size={24} /></span><div className={styles.headerText}>
          <span className="ol-eyebrow">Course</span>
          {editing ? <form onSubmit={event => { event.preventDefault(); void renameCourse(); }} className="course-folder-rename"><input aria-label="Course name" autoFocus value={name} maxLength={300} onChange={event => setName(event.target.value)} /><Button size="sm" type="submit" disabled={!name.trim() || !!busyId}>Save</Button><Button size="sm" type="button" variant="ghost" onClick={() => { setEditing(false); setName(course.name); }}>Cancel</Button></form> : <h1>{course.name}</h1>}
          {course.goal ? <p className={styles.goal}>{course.goal}</p> : null}
          <p className={styles.meta}>{meta.join(' · ')} · <Link href="/concepts">Review course concepts</Link></p>
        </div></div>
        <div className={`course-folder-actions ${styles.headerActions}`}>
          <Button type="button" onClick={askBuddy}><MessageSquare size={16} />Ask {buddyName}</Button>
          <Button type="button" variant="outline" onClick={startClass}><Mic size={16} />Start class</Button>
          <div className="course-folder-menu-wrap"><Button type="button" variant="ghost" size="icon" aria-label="Course options" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><MoreHorizontal size={19} /></Button>{menuOpen ? <div className="course-folder-menu"><button type="button" onClick={() => { setEditing(true); setMenuOpen(false); }}>Rename course</button><button type="button" className="danger" onClick={() => { setMenuOpen(false); void deleteCourse(); }}><Trash2 size={15} />Delete course</button></div> : null}</div>
        </div>
      </header>

      <div className={styles.layout}>
      {sectionNav}
      <div className={styles.main}>
      {section === 'overview' ? <div>
        <CourseBuddy courseId={courseId} onChat={askBuddy}/>
        <div className={styles.resume}>
          <div><span className={styles.eyebrow}>YOUR NEXT STEP</span><h2>{sessions.length ? 'Pick up where you left off' : 'Start learning '+course.name}</h2><p>{sessions.length ? recentSession?.title : 'Ask a question, add your course materials, or capture a class.'}</p></div>
          <Button onClick={()=>sessions.length ? recentSession && onOpenSession(recentSession.id) : onNewSession()}>{sessions.length ? 'Continue conversation' : 'Start a conversation'}</Button>
        </div>
        <div className={styles.cards}>
          <button type="button" onClick={()=>setSection('materials')}><Library size={22}/><strong>Materials</strong><span>{typeof materialCount === 'number' ? `${materialCount} in your library` : 'Textbooks, slides and past papers'}</span><small>Open your library →</small></button>
          <button type="button" onClick={()=>setSection('classes')}><Mic size={22}/><strong>Classes</strong><span>{courseClasses.length} captured {courseClasses.length === 1 ? 'class' : 'classes'}</span><small>Record or revisit a class →</small></button>
          <button type="button" onClick={()=>setSection('notes')}><NotebookPen size={22}/><strong>Notes</strong><span>{notes.length} {notes.length === 1 ? 'note' : 'notes'} in this course</span><small>Open your notes →</small></button>
          <button type="button" onClick={()=>setSection('practice')}><ListChecks size={22}/><strong>Practice</strong><span>{quizzes.length} saved {quizzes.length === 1 ? 'quiz' : 'quizzes'} · flashcards</span><small>Quizzes and flashcards →</small></button>
          <button type="button" onClick={()=>setSection('plan')}><CalendarRange size={22}/><strong>Study plan</strong><span>Exams, assignments and study activities</span><small>Plan your next session →</small></button>
        </div>

        <CourseAssetPreview courseId={courseId} onOpen={()=>setSection('materials')} />
        <div className="course-folder-section"><div className="course-folder-section-head"><div><h2>Chats</h2><p>Conversations in this course</p></div><Button variant="outline" size="sm" disabled={busyId === 'picker'} onClick={() => void openPicker('chats')}><Plus size={15} />Add chats</Button></div>
          {sessions.length ? <div className="course-folder-list">{sessions.map(item => <div className="course-folder-row" key={item.id}><button type="button" className="course-folder-row-title" onClick={() => onOpenSession(item.id)}><MessageSquare size={18} /><span>{item.title}</span></button><Button variant="ghost" size="sm" onClick={() => onQuizSession(item.id)}>Create quiz</Button><button type="button" className="course-folder-remove" aria-label={`Remove ${item.title} from course`} disabled={busyId === item.id} onClick={() => void removeChat(item.id)}>Remove</button></div>)}</div> : <p className="course-folder-empty">Start a chat here, or add one you already have.</p>}
        </div>
      </div> : null}

      {section === 'materials' ? <div className={styles.panel}><h2>Course materials</h2><p className={styles.lede}>Keep your textbooks, slides and references together. All buddies in this course can use this library.</p><MaterialLibrary courseId={courseId} initiallyOpen /></div> : null}

      {section === 'classes' ? <section className={styles.panel} aria-labelledby="course-classes-title"><div className="course-folder-section-head"><div><h2 id="course-classes-title">Class sessions</h2><p>Open a class for live notes, supporting material, practice and its revision package.</p></div><Button onClick={startClass}><Mic size={15} />Start class</Button></div>
        {courseClasses.length ? <div className="course-folder-list">{courseClasses.map(item => <div className="course-folder-row" key={item.id}><button type="button" className="course-folder-row-title" onClick={() => item.classId ? openClassWorkspace(item.classId) : onOpenNote(item.noteId)}><Mic size={18} /><span>{item.title}</span></button><small className={styles.rowMeta}>{new Date(item.startedAt * 1000).toLocaleDateString()} · {buddies.snapshot?.profiles.find(p => p.id === item.buddyId)?.name || 'Buddy'} · {item.status}</small></div>)}</div> : <p className="course-folder-empty">No class recordings yet. Start a class to capture notes.</p>}
        <p className={styles.footnote}>Older recordings open their saved note.</p>
      </section> : null}

      {section === 'notes' ? <section className={styles.panel} aria-labelledby="course-notes-title"><div className="course-folder-section-head"><div><h2 id="course-notes-title">Notes</h2><p>Notes kept with this course</p></div><Button variant="outline" size="sm" disabled={busyId === 'picker'} onClick={() => void openPicker('notes')}><Plus size={15} />Add notes</Button></div>
        {notes.length ? <div className="course-folder-list">{notes.map(item => <div className="course-folder-row" key={item.id}><button type="button" className="course-folder-row-title" onClick={() => onOpenNote(item.id)}><FileText size={18} /><span>{item.title}</span></button><button type="button" className="course-folder-remove" aria-label={`Remove ${item.title} from course`} disabled={busyId === item.id} onClick={() => void setNoteCourse(item.id, true)}>Remove</button></div>)}</div> : <p className="course-folder-empty">Add a note from your workspace to keep it here.</p>}
      </section> : null}

      {section === 'practice' ? <section className={styles.panel} aria-labelledby="course-practice-title"><h2 id="course-practice-title">Practice</h2><p className={styles.lede}>Saved quizzes from this course&apos;s chats, and flashcards to keep ideas fresh.</p>
        <h3 className={styles.subheading}>Saved quizzes</h3>
        {quizError ? <p role="alert">{quizError}</p> : quizzes.length ? <div className="course-folder-list">{quizzes.map(quiz => <div className="course-folder-row" key={quiz.id}><button type="button" className="course-folder-row-title" onClick={() => onSavedQuiz?.(quiz)}><ListChecks size={18} /><span>{quiz.title}</span></button><span className="ol-badge" data-tone={quiz.status === 'completed' ? undefined : 'brand'}>{quiz.status.replaceAll('_', ' ')} · {quiz.attempted}/{quiz.count}</span></div>)}</div> : <p className="course-folder-empty">No saved quizzes yet. Create one from any chat in this course.</p>}
        <h3 className={styles.subheading}>Flashcards</h3>
        <FlashcardLibraryEntry courseId={courseId}/>
      </section> : null}

      {section === 'plan' ? <div className={styles.panel}><CourseStudyPlanner courseId={courseId} onLaunchTask={onLaunchTask} onLaunchReady={onLaunchReady}/><CanvasConnection courseId={courseId}/></div> : null}
      </div>
      </div>

      {picker ? <><button type="button" className="course-folder-picker-overlay" aria-label="Close picker" onClick={() => setPicker(null)} /><div className="course-folder-picker" role="dialog" aria-modal="true" aria-label={`Add ${picker} to course`}><div className="course-folder-picker-head"><h2>Add {picker}</h2><button type="button" aria-label="Close" onClick={() => setPicker(null)}>✕</button></div><label className="course-folder-search"><Search size={16} /><input autoFocus value={search} onChange={event => setSearch(event.target.value)} placeholder={`Search ${picker}`} /></label><div className="course-folder-picker-list">{picker === 'chats' ? availableChats.map(item => <button type="button" key={item.id} disabled={!!busyId} onClick={() => void addChat(item.id)}><MessageSquare size={17} /><span>{item.title}</span><Plus size={16} /></button>) : availableNotes.map(item => <button type="button" key={item.id} disabled={!!busyId} onClick={() => void setNoteCourse(item.id)}><FileText size={17} /><span>{item.title}</span><Plus size={16} /></button>)}{(picker === 'chats' ? availableChats : availableNotes).length === 0 ? <p>No available {picker} found.</p> : null}</div></div></> : null}
    </div> : null}
  </section>;
}
