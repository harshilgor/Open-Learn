"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { WorkspacePanel, type WorkspacePanelLayout } from './workspace-panel';
import { WORKSPACE_NOTE_OPEN_EVENT, WORKSPACE_NOTE_SEED_EVENT, WORKSPACE_PANEL_SET_COLLAPSED_EVENT, WORKSPACE_PANEL_TOGGLE_EVENT, WORKSPACE_SOURCE_OPEN_EVENT, WORKSPACE_QUIZ_OPEN_EVENT, type WorkspaceNoteSeed, type WorkspaceQuizOpen } from '@/lib/workspace-events';
import styles from './workspace-split.module.css';

const STORAGE_KEY = 'forma-workspace-panel-v1';
const DEFAULT_LAYOUT: WorkspacePanelLayout = { width: 50, collapsed: true, tabs: ['notes'], activeTab: 'notes' };

export type WorkspaceSplitContextValue = {
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
  toggle: () => void;
};

export const WorkspaceSplitContext = createContext<WorkspaceSplitContextValue>({
  collapsed: true,
  setCollapsed: () => {},
  toggle: () => {},
});

export function useWorkspacePanel() {
  return useContext(WorkspaceSplitContext);
}

function validLayout(value: unknown): value is WorkspacePanelLayout {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<WorkspacePanelLayout>;
  return typeof candidate.width === 'number' && typeof candidate.collapsed === 'boolean'
    && Array.isArray(candidate.tabs) && candidate.tabs.every(tab => tab === 'notes' || tab === 'quiz' || tab === 'sources')
    && (candidate.activeTab === 'notes' || candidate.activeTab === 'quiz' || candidate.activeTab === 'sources');
}

export function WorkspaceSplit({ children, quizSessionId, quizConceptId, hidePanel = false }: { children: ReactNode; quizSessionId?: string | null; quizConceptId?: string; hidePanel?: boolean }) {
  const reduceMotion = useAppReducedMotion();
  const [layout, setLayout] = useState<WorkspacePanelLayout>(DEFAULT_LAYOUT);
  const [ready, setReady] = useState(false);
  const [compact, setCompact] = useState(false);
  const [noteSeed, setNoteSeed] = useState<WorkspaceNoteSeed | null>(null);
  const [noteToOpen, setNoteToOpen] = useState<string | null>(null);
  const [sourceToOpen, setSourceToOpen] = useState<{ spanId: string; versionId?: string } | null>(null);
  const [quizToOpen, setQuizToOpen] = useState<WorkspaceQuizOpen | null>(null);
  const groupRef = useRef<HTMLDivElement | null>(null);
  const resizing = useRef(false);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1220px)');
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const receiveDraft = (event: Event) => {
      const draft = (event as CustomEvent<WorkspaceNoteSeed>).detail;
      if (!draft?.id) return;
      setNoteSeed(draft);
      setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('notes') ? current.tabs : [...current.tabs, 'notes'], activeTab: 'notes' }));
    };
    window.addEventListener(WORKSPACE_NOTE_SEED_EVENT, receiveDraft);
    return () => window.removeEventListener(WORKSPACE_NOTE_SEED_EVENT, receiveDraft);
  }, []);
  useEffect(() => {
    const receiveOpen = (event: Event) => {
      const noteId = (event as CustomEvent<string>).detail;
      if (!noteId) return;
      setNoteToOpen(noteId);
      setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('notes') ? current.tabs : [...current.tabs, 'notes'], activeTab: 'notes' }));
    };
    window.addEventListener(WORKSPACE_NOTE_OPEN_EVENT, receiveOpen);
    return () => window.removeEventListener(WORKSPACE_NOTE_OPEN_EVENT, receiveOpen);
  }, []);
  useEffect(() => {
    const receiveSource = (event: Event) => { const detail = (event as CustomEvent<{ spanId: string; versionId?: string }>).detail; if (!detail?.spanId) return; setSourceToOpen(detail); setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('sources') ? current.tabs : [...current.tabs, 'sources'], activeTab: 'sources' })); };
    window.addEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receiveSource);
    return () => window.removeEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receiveSource);
  }, []);
  useEffect(() => {
    const receiveQuiz = (event: Event) => {
      const detail = (event as CustomEvent<WorkspaceQuizOpen>).detail;
      if (!detail?.sessionId) return;
      setQuizToOpen(detail);
      if (detail.origin === 'learn' && detail.lessonNoteId) {
        setNoteToOpen(detail.lessonNoteId);
        setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('notes') ? current.tabs : [...current.tabs, 'notes'], activeTab: 'notes' }));
      } else {
        setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('quiz') ? current.tabs : [...current.tabs, 'quiz'], activeTab: 'quiz' }));
      }
    };
    window.addEventListener(WORKSPACE_QUIZ_OPEN_EVENT, receiveQuiz);
    return () => window.removeEventListener(WORKSPACE_QUIZ_OPEN_EVENT, receiveQuiz);
  }, []);
  useEffect(() => {
    const handleToggle = () => {
      setLayout(current => ({ ...current, collapsed: !current.collapsed }));
    };
    const handleSet = (event: Event) => {
      const collapsed = (event as CustomEvent<boolean>).detail;
      setLayout(current => ({ ...current, collapsed }));
    };
    window.addEventListener(WORKSPACE_PANEL_TOGGLE_EVENT, handleToggle);
    window.addEventListener(WORKSPACE_PANEL_SET_COLLAPSED_EVENT, handleSet);
    return () => {
      window.removeEventListener(WORKSPACE_PANEL_TOGGLE_EVENT, handleToggle);
      window.removeEventListener(WORKSPACE_PANEL_SET_COLLAPSED_EVENT, handleSet);
    };
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
        if (validLayout(stored)) {
          const hasSavedQuiz = Boolean(localStorage.getItem(`forma-quiz:${quizSessionId || 'panel'}`) || localStorage.getItem('forma-quiz'));
          const tabs = stored.tabs.filter(tab => tab !== 'quiz' || hasSavedQuiz);
          setLayout({ ...stored, width: Math.min(70, Math.max(30, stored.width)), tabs: tabs.length ? tabs : ['notes'], activeTab: tabs.includes(stored.activeTab) ? stored.activeTab : 'notes' });
        }
      } catch { /* A session remains usable without browser storage. */ }
      setReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (!ready) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); } catch { /* Layout persistence is optional. */ }
  }, [layout, ready]);
  useEffect(() => {
    const resize = (event: PointerEvent) => {
      if (!resizing.current || !groupRef.current) return;
      const bounds = groupRef.current.getBoundingClientRect();
      const width = ((bounds.right - event.clientX) / bounds.width) * 100;
      setLayout(current => ({ ...current, collapsed: false, width: Math.round(Math.min(70, Math.max(30, width))) }));
    };
    const stop = () => { resizing.current = false; };
    window.addEventListener('pointermove', resize);
    window.addEventListener('pointerup', stop);
    return () => { window.removeEventListener('pointermove', resize); window.removeEventListener('pointerup', stop); };
  }, []);

  const contextValue = useMemo<WorkspaceSplitContextValue>(() => ({
    collapsed: layout.collapsed,
    setCollapsed: (collapsed: boolean) => setLayout(current => ({ ...current, collapsed })),
    toggle: () => setLayout(current => ({ ...current, collapsed: !current.collapsed })),
  }), [layout.collapsed]);

  const panel = <WorkspacePanel quizSessionId={quizSessionId} quizConceptId={quizConceptId} quizToOpen={quizToOpen} layout={layout} onLayoutChange={setLayout} noteSeed={noteSeed} noteToOpen={noteToOpen} sourceToOpen={sourceToOpen} onNoteSeedConsumed={id => setNoteSeed(current => current?.id === id ? null : current)} onNoteOpenConsumed={noteId => setNoteToOpen(current => current === noteId ? null : current)}
    onCollapse={() => setLayout(current => ({ ...current, collapsed: true }))}
    onExpand={() => setLayout(current => ({ ...current, collapsed: false }))} />;

  if (hidePanel) return <WorkspaceSplitContext.Provider value={contextValue}><div className={styles.notesGroup}>{children}</div></WorkspaceSplitContext.Provider>;
  if (compact) return <WorkspaceSplitContext.Provider value={contextValue}><div className={styles.compact}><div className={styles.compactMain}>{children}</div><AnimatePresence initial={false}>{!layout.collapsed && <motion.div key="workspace-panel" className={styles.panel} initial={reduceMotion ? false : { opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 24 }} transition={{ duration: 0.2, ease: 'easeOut' }}>{panel}</motion.div>}</AnimatePresence></div></WorkspaceSplitContext.Provider>;

  return <WorkspaceSplitContext.Provider value={contextValue}>
    <div ref={groupRef} className={styles.group}>
      <div className={styles.main}>{children}</div>
      {!layout.collapsed && (
        <div className={styles.handle} role="separator" aria-orientation="vertical" aria-label="Resize workspace panel" aria-valuemin={30} aria-valuemax={70} aria-valuenow={layout.width} tabIndex={0}
          onPointerDown={event => { event.preventDefault(); resizing.current = true; }}
          onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); const change = event.key === 'ArrowLeft' ? 2 : -2; setLayout(current => ({ ...current, collapsed: false, width: Math.max(30, Math.min(70, current.width + change)) })); } }} />
      )}
      <motion.div
        className={`${styles.panel} ${layout.collapsed ? styles.collapsed : ''}`}
        style={{ '--workspace-panel-width': layout.collapsed ? '0px' : `${layout.width}%` } as CSSProperties}
        animate={reduceMotion ? undefined : { opacity: layout.collapsed ? 0 : 1 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {panel}
      </motion.div>
    </div>
  </WorkspaceSplitContext.Provider>;
}
