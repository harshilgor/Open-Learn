"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { WorkspacePanel, type WorkspacePanelLayout } from './workspace-panel';
import { WORKSPACE_NOTE_OPEN_EVENT, WORKSPACE_NOTE_SEED_EVENT, WORKSPACE_PANEL_SET_COLLAPSED_EVENT, WORKSPACE_PANEL_TOGGLE_EVENT, WORKSPACE_SOURCE_OPEN_EVENT, WORKSPACE_QUIZ_OPEN_EVENT, type WorkspaceNoteSeed, type WorkspaceQuizOpen } from '@/lib/workspace-events';
import styles from './workspace-split.module.css';
import { DeferredWorkspace } from './deferred-workspace';
import {WORKSPACE_FLASHCARDS_OPEN_EVENT} from '@/lib/workspace-events';
import {WORKSPACE_CANVAS_EVENT} from '@/lib/workspace-events';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import type {FlashcardView} from '@/lib/flashcards-client';
import {CLASS_OPEN_EVENT,setActiveClassContext} from '@/lib/in-class';

const STORAGE_KEY = 'forma-workspace-panel-v1';
const DEFAULT_LAYOUT: WorkspacePanelLayout = { width: 50, collapsed: true, tabs: ['notes', 'sources', 'practice'], activeTab: 'notes' };

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
    && Array.isArray(candidate.tabs) && candidate.tabs.every(tab => tab === 'notes' || tab === 'quiz' || tab === 'sources' || tab==='class' || tab==='flashcards' || tab==='practice' || tab==='canvas')
    && (candidate.activeTab === 'notes' || candidate.activeTab === 'quiz' || candidate.activeTab === 'sources' || candidate.activeTab==='class' || candidate.activeTab==='flashcards' || candidate.activeTab==='practice' || candidate.activeTab==='canvas');
}

export function WorkspaceSplit({ children, quizSessionId, quizConceptId, hidePanel = false }: { children: ReactNode; quizSessionId?: string | null; quizConceptId?: string; hidePanel?: boolean }) {
  const reduceMotion = useAppReducedMotion();
  const [layout, setLayout] = useState<WorkspacePanelLayout>(DEFAULT_LAYOUT);
  const [accountGeneration, setAccountGeneration] = useState(0);
  const [canvasValue, setCanvasValue] = useState<unknown>(null);
  const [ready, setReady] = useState(false);
  const [compact, setCompact] = useState(false);
  const [noteSeed, setNoteSeed] = useState<WorkspaceNoteSeed | null>(null);
  const [noteToOpen, setNoteToOpen] = useState<string | null>(null);
  const [sourceToOpen, setSourceToOpen] = useState<{ spanId: string; versionId?: string } | null>(null);
  const [quizToOpen, setQuizToOpen] = useState<WorkspaceQuizOpen | null>(null);
  const [flashcardLaunch,setFlashcardLaunch]=useState<FlashcardView|null>(null);
  const [classId,setClassId]=useState<string|null>(null);
  useEffect(()=>{
    const open=(event:Event)=>{const detail=(event as CustomEvent<FlashcardView>).detail;if(!detail)return;setFlashcardLaunch(detail);setLayout(current=>({...current,collapsed:false,tabs:current.tabs.includes('flashcards')?current.tabs:[...current.tabs,'flashcards'],activeTab:'flashcards'}));const url=new URL(window.location.href);url.searchParams.set('flashcards',detail.deckId||'library');if(detail.reviewSessionId)url.searchParams.set('flashcardReview',detail.reviewSessionId);else url.searchParams.delete('flashcardReview');window.history.replaceState({},'',url);};
    const restore=()=>{const query=new URLSearchParams(window.location.search);const deckId=query.get('flashcards'),reviewSessionId=query.get('flashcardReview');if(deckId||reviewSessionId)open(new CustomEvent(WORKSPACE_FLASHCARDS_OPEN_EVENT,{detail:{deckId:deckId==='library'?undefined:deckId||undefined,view:reviewSessionId?'review':deckId==='library'?'library':'editor',reviewSessionId:reviewSessionId||undefined}}));};
    const clear=()=>{setAccountGeneration(value => value + 1);setNoteSeed(null);setNoteToOpen(null);setSourceToOpen(null);setQuizToOpen(null);setCanvasValue(null);setFlashcardLaunch(null);setClassId(null);setActiveClassContext(null);setLayout(DEFAULT_LAYOUT);const url=new URL(window.location.href);url.searchParams.delete('flashcards');url.searchParams.delete('flashcardReview');window.history.replaceState({},'',url);};
    window.addEventListener(WORKSPACE_FLASHCARDS_OPEN_EVENT,open);window.addEventListener('popstate',restore);window.addEventListener(ACCOUNT_CHANGED,clear);restore();return()=>{window.removeEventListener(WORKSPACE_FLASHCARDS_OPEN_EVENT,open);window.removeEventListener('popstate',restore);window.removeEventListener(ACCOUNT_CHANGED,clear);};
  },[]);
  useEffect(()=>{const open=(event:Event)=>{const detail=(event as CustomEvent<{classId:string}>).detail;if(!detail?.classId)return;setClassId(detail.classId);setActiveClassContext(detail.classId);setLayout(current=>({...current,collapsed:false,tabs:current.tabs.includes('class')?current.tabs:[...current.tabs,'class'],activeTab:'class'}));};window.addEventListener(CLASS_OPEN_EVENT,open);return()=>window.removeEventListener(CLASS_OPEN_EVENT,open);},[]);
  const groupRef = useRef<HTMLDivElement | null>(null);
  const resizing = useRef(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!compact || layout.collapsed || hidePanel) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.querySelector<HTMLElement>('button')?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [compact, layout.collapsed, hidePanel]);

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
          const tabs = [...new Set<import('./workspace-panel').WorkspaceTab>(['notes', 'sources', 'practice', ...stored.tabs])].filter(tab => tab !== 'class' && (tab !== 'quiz' || hasSavedQuiz));
          setLayout(current=>current.tabs.includes('class')||current.tabs.includes('flashcards')?current:{ ...stored, width: Math.min(70, Math.max(30, stored.width)), tabs: tabs.length ? tabs : ['notes'], activeTab: tabs.includes(stored.activeTab) ? stored.activeTab : 'notes' });
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

  useEffect(() => {
    const receive = (event: Event) => { setCanvasValue((event as CustomEvent).detail); setLayout(current => ({ ...current, collapsed: false, tabs: current.tabs.includes('canvas') ? current.tabs : [...current.tabs, 'canvas'], activeTab: 'canvas' })); };
    window.addEventListener(WORKSPACE_CANVAS_EVENT, receive); return () => window.removeEventListener(WORKSPACE_CANVAS_EVENT, receive);
  }, []);

  const contextValue = useMemo<WorkspaceSplitContextValue>(() => ({
    collapsed: layout.collapsed,
    setCollapsed: (collapsed: boolean) => setLayout(current => ({ ...current, collapsed })),
    toggle: () => setLayout(current => ({ ...current, collapsed: !current.collapsed })),
  }), [layout.collapsed]);

  const panel = <WorkspacePanel key={accountGeneration} canvasValue={canvasValue} flashcardLaunch={flashcardLaunch} classId={classId} quizSessionId={quizSessionId} quizConceptId={quizConceptId} quizToOpen={quizToOpen} layout={layout} onLayoutChange={setLayout} noteSeed={noteSeed} noteToOpen={noteToOpen} sourceToOpen={sourceToOpen} onNoteSeedConsumed={id => setNoteSeed(current => current?.id === id ? null : current)} onNoteOpenConsumed={noteId => setNoteToOpen(current => current === noteId ? null : current)}
    onCollapse={() => setLayout(current => ({ ...current, collapsed: true }))}
    onExpand={() => setLayout(current => ({ ...current, collapsed: false }))} />;

  return <WorkspaceSplitContext.Provider value={contextValue}>
    <div ref={groupRef} className={compact ? styles.compact : styles.group}>
      <div className={styles.main} inert={compact && !layout.collapsed && !hidePanel}>{children}</div>
      {!compact && !hidePanel && !layout.collapsed && (
        <div className={styles.handle} role="separator" aria-orientation="vertical" aria-label="Resize workspace panel" aria-valuemin={30} aria-valuemax={70} aria-valuenow={layout.width} tabIndex={0}
          onPointerDown={event => { event.preventDefault(); resizing.current = true; }}
          onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); const change = event.key === 'ArrowLeft' ? 2 : -2; setLayout(current => ({ ...current, collapsed: false, width: Math.max(30, Math.min(70, current.width + change)) })); } }} />
      )}
      <motion.div
        ref={panelRef}
        className={`${styles.panel} ${layout.collapsed || hidePanel ? styles.collapsed : ''}`}
        hidden={hidePanel || layout.collapsed}
        role={compact ? 'dialog' : undefined}
        aria-modal={compact && !layout.collapsed && !hidePanel ? true : undefined}
        aria-label={compact ? 'Study workspace' : undefined}
        onKeyDown={event => {
          if (!compact || layout.collapsed) return;
          if (event.key === 'Escape') { event.preventDefault(); setLayout(current => ({ ...current, collapsed: true })); }
          if (event.key !== 'Tab') return;
          const controls = [...(panelRef.current?.querySelectorAll<HTMLElement>('button, a[href], input, textarea, select, [tabindex="0"]') || [])].filter(element => !element.closest('[hidden]') && !element.hasAttribute('disabled') && element.getClientRects().length);
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first && last) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last && first) { event.preventDefault(); first.focus(); }
        }}
        style={{ '--workspace-panel-width': layout.collapsed ? '0px' : `${layout.width}%` } as CSSProperties}
        animate={reduceMotion ? undefined : { opacity: layout.collapsed ? 0 : 1 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <DeferredWorkspace active={!layout.collapsed && !hidePanel}>{panel}</DeferredWorkspace>
      </motion.div>
    </div>
  </WorkspaceSplitContext.Provider>;
}
