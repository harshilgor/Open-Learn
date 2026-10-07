"use client";
import { useVoice } from "./voice/voice-provider";
import { VoiceHistory } from "./voice/voice-history";
import { reportVoiceFocus, VOICE_REFRESH, voiceApi } from "@/lib/voice/client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { LoaderCircle, FileText, Check, X, ArrowDown, GraduationCap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { LearningApiError, learningApi, request, type Gear, type LessonArtifact, type ModeTransitionSuggestion, type WorkspaceNoteSummary, type NoteDraft } from '@/lib/api';
import styles from './learn-chat.module.css';
import { chatDraftFiles } from '@/lib/chat-draft-files';
import { ChatComposer, type ChatAttachment, type ChatNoteMention } from './chat-composer';
import { LessonReader } from './lesson-reader';
import { parseVisualization } from '@/lib/visualization-spec';
import { RichContent } from './rich-content';
import { materialRequest, materialCommand, prepareAttachment, type MaterialAnswer } from '@/lib/chat-materials';
import { getJourney, workflow, waitForJob, rememberSessionHint, navigateToSession, restoreSessionAuthority, isStaleSessionConflict, type ChatMode, type Journey } from '@/lib/learning-workflows';
import { GenerationStream, type GenerationEvent, type GenerationMode } from '@/lib/generation-stream';
import { QuizWorkspace } from './quiz-workspace';
import { NoteDraftCard } from './note-draft-card';
import panelStyles from './study-note-panel.module.css';
import { NextActionCards } from './next-action-cards';
import { ConceptProgressWhy } from './concept-progress-why';
import { captureReadingBlocks } from '@/lib/study-capture';
import { SaveToNote } from './save-to-note';
import { WORKSPACE_CAPTURE_EVENT, WORKSPACE_ASK_EVENT, WORKSPACE_NOTE_IMPROVE_EVENT } from '@/lib/workspace-events';
import { openWorkspaceNote, openWorkspaceNoteDraft, openWorkspaceSource, WORKSPACE_NOTE_MENTION_EVENT, WORKSPACE_NOTE_REPLACE_DRAFT_EVENT, WORKSPACE_QUIZ_REQUEST_EVENT, type WorkspaceNoteMention } from '@/lib/workspace-events';
import { WebResearchActivity, type AgentActivity } from './web-research-activity';
import { ModeTransitionCard, OriginBadge } from './mode-transition-card';
import { useBuddies, BuddyAvatar } from './buddies';
import { buddyApi } from '@/lib/buddies';
import { DevContextInspector } from './dev-context-inspector';
import { readSettingsPreferences } from '@/lib/settings-preferences';
import { splitTutorContent } from '@/lib/tutor-format';
import { VerificationBadge, type MessageVerification } from './message-action-bar';
import {useBrowserAssistant} from '@/lib/browser-assistant';
import {BrowserTaskCard} from './browser-task-card';
import {ExecutionPanel} from './assistant/execution-panel';
import {parseClassReferenceOpenRequest,requestClassReferenceOpen} from '@/lib/in-class';

type NoteContextReceipt = { label: string; notes: { noteId: string; title: string; revision: number; startOffset?: number | null; endOffset?: number | null }[]; totalCharacters: number };
type ReplacementTarget = { noteId: string; title: string; revision: number; startOffset: number; endOffset: number };
type StreamedBlock = { id: string; kind: string; heading: string; body: string; status: 'streaming' | 'completed'; visualizations?: unknown[] };
type StreamedLesson = { id: string; blocks: StreamedBlock[]; status: 'streaming' | 'completed'; visualizations?: unknown[]; visualPending?: boolean };
type Turn = { question: string; lesson?: LessonArtifact; answer?: MaterialAnswer; stream?: StreamedLesson; files?: string[]; sessionId?: string; generationId?: string; status?: 'pending' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; errorCode?: string; noteContext?: NoteContextReceipt; transitionSuggestion?: ModeTransitionSuggestion | null; verification?: MessageVerification | null };
type SelectedPassage = { blockId: string; selectedText: string; lessonId?: string; sessionId?: string };
type SelectionPanel = { selection: SelectedPassage; blocks: StreamedBlock[]; status: 'preparing' | 'streaming' | 'completed' | 'error'; error?: string };
type GenerationRecovery = { generationId: string; sessionId: string; mode: GenerationMode; lastAppliedSequence: number; status: string };

const GREETINGS = [
  'Hi, what do you want to learn today?',
  'What are you curious about right now?',
  'Drop in a book, or ask anything…',
  'What idea should we unpack next?',
  'Where should we start exploring?',
];

/** Journey actions invent these labels; they are not learner messages. */
const SYNTHETIC_QUESTIONS = new Set(['Start learning', 'Continue', 'Help me understand this differently']);

function RotatingGreeting() {
  const reduceMotion = useAppReducedMotion();
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (reduceMotion) return;
    const timer = window.setInterval(() => setIndex(i => (i + 1) % GREETINGS.length), 3500);
    return () => window.clearInterval(timer);
  }, [reduceMotion]);
  return (
    <p className={styles.greeting} aria-live="polite">
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={index}
          initial={reduceMotion ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
        >
          {GREETINGS[index]}
        </motion.span>
      </AnimatePresence>
    </p>
  );
}

export function LearnChat({
  onQuiz,
  onReview,
  initialPrompt,
  onInitialPromptConsumed,
  preferredMode,
  autoSubmitInitialPrompt,
  studyTask,
  onStudyTaskCompleted,
  initialSessionId,
  courseId,
  courseName,
  onCourseClick,
  onSessionCreated,
  onInClass,
  onMissingSession,
}: {
  onQuiz?: (sessionId: string, conceptId?: string, origin?: 'ask' | 'learn', requestedTopic?: string, sourceTransitionId?: string) => void | Promise<void>;
  onReview?: (sessionId: string, conceptId?: string) => void;
  initialPrompt?: string;
  onInitialPromptConsumed?: () => void;
  preferredMode?: ChatMode;
  autoSubmitInitialPrompt?: boolean;
  studyTask?: { taskId: string; courseId: string; revision: number; canonicalConceptIds: string[] } | null;
  onStudyTaskCompleted?: () => void;
  /** Route session id wins over disposable localStorage hints. */
  initialSessionId?: string | null;
  courseId?: string | null;
  courseName?: string | null;
  onCourseClick?: (courseId: string) => void;
  onSessionCreated?: (id:string)=>void;
  onInClass?:()=>void;
  onMissingSession?:()=>void;
}) {
  const reduceMotion = useAppReducedMotion();
  const voice = useVoice();
  const [voiceRefresh, setVoiceRefresh] = useState(0);
  const buddies=useBuddies();
  const [conversation,setConversation]=useState(()=>initialSessionId?buddies.snapshot?.modes[initialSessionId]!=='ask':true);
  const restoredPresentation = useRef(initialSessionId ? buddies.snapshot?.modes[initialSessionId] : undefined);
  const pendingDraftKey=`openlearn-pending-chat-draft:${initialSessionId||'new'}`;
  const draftKey=buddies.active?`openlearn-chat-draft:${buddies.active.id}:${initialSessionId||'new'}`:null;
  const [prompt, setPrompt] = useState(()=>{try{return (draftKey?localStorage.getItem(draftKey):null)||sessionStorage.getItem(pendingDraftKey)||'';}catch{return '';}});
  useEffect(()=>{try{if(draftKey){if(prompt)localStorage.setItem(draftKey,prompt);else localStorage.removeItem(draftKey);sessionStorage.removeItem(pendingDraftKey);}else{if(prompt)sessionStorage.setItem(pendingDraftKey,prompt);else sessionStorage.removeItem(pendingDraftKey);}}catch{/* Optional drafts */}},[prompt,draftKey,pendingDraftKey]);
  const [dismissedConceptId, setDismissedConceptId] = useState<string|null>(null);
  const [selectedConcept, setSelectedConcept] = useState<{ id: string; title: string } | null>(null);
  const [resolvedExercises, setResolvedExercises] = useState<Set<string>>(new Set());
  const [gear, setGear] = useState<Gear>('Quick');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const browserAssistant = useBrowserAssistant(sessionId, courseId);
  const [chatMode, setChatMode] = useState<ChatMode>('ask');
  const [journey, setJourney] = useState<Journey | null>(null);
  const [checking, setChecking] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>(()=>draftKey?chatDraftFiles.get(draftKey)?.attachments||[]:[]);
  const [noteMentions, setNoteMentions] = useState<ChatNoteMention[]>(()=>draftKey?chatDraftFiles.get(draftKey)?.notes||[]:[]);
  useEffect(()=>{if(draftKey)chatDraftFiles.set(draftKey,{attachments,notes:noteMentions});},[draftKey,attachments,noteMentions]);
  const [noteDrafts, setNoteDrafts] = useState<NoteDraft[]>([]);
  const [replacementTarget, setReplacementTarget] = useState<ReplacementTarget | null>(null);
  const attachedVersions = useRef<string[]>([]);
  const [progress, setProgress] = useState('Thinking about that…');
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const [classActionReply,setClassActionReply]=useState('');
  const [scheduledMessages,setScheduledMessages]=useState<{id:string;title:string;body:string;url:string}[]>([]);
  useEffect(()=>{
    if(!sessionId)return;
    let live=true;
    const load=()=>void request<{messages:{id:string;title:string;body:string;url:string}[]}>('/v1/reminder-messages?sessionId='+encodeURIComponent(sessionId)).then(result=>{if(live)setScheduledMessages(result.messages);}).catch(()=>{});
    load();const timer=window.setInterval(load,15000);
    return()=>{live=false;window.clearInterval(timer);};
  },[sessionId]);
  const [selection, setSelection] = useState<SelectedPassage | null>(null);
  const [selectionPanel, setSelectionPanel] = useState<SelectionPanel | null>(null);
  const [selectionFollowup, setSelectionFollowup] = useState('');
  const [appliedNote, setAppliedNote] = useState<{ heading: string; noteId: string; applyKind?: 'added' | 'refined' } | null>(null);
  const [activity, setActivity] = useState<AgentActivity>(null);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<string>>(new Set());
  const [originBadge, setOriginBadge] = useState<string | null>(null);
  const [activeModeSuggestion, setActiveModeSuggestion] = useState<ModeTransitionSuggestion | null>(null);
  const [waitingForModeChoice, setWaitingForModeChoice] = useState(false);
  const [quizClarification, setQuizClarification] = useState<{ sessionId?: string; conceptId?: string; origin: 'ask' | 'learn'; sourceTransitionId?: string } | null>(null);
  const quizOrigin = useRef<'ask' | 'learn'>('ask');
  const classificationBypass = useRef<string | null>(null);
  const submitRef = useRef<(() => Promise<void>) | null>(null);
  const completedStudyTask = useRef<string | null>(null);

  useEffect(() => {
    if (!initialSessionId && !sessionId) setGear(readSettingsPreferences().defaultGear);
  }, [initialSessionId, sessionId]);

  const requestQuiz = useCallback(async (sid: string, conceptId?: string, requestText?: string, sourceTransitionId?: string, requestedOrigin?: 'ask' | 'learn'): Promise<boolean> => {
    if (!onQuiz) throw new Error('Quiz is unavailable here.');
    const origin = requestedOrigin || (chatMode === 'learn' || (chatMode === 'quiz' && quizOrigin.current === 'learn') ? 'learn' : 'ask');
    const explicitTopic = requestText?.match(/(?:quiz|test)(?: me)?\s+(?:on|about|with)\s+(.+)/i)?.[1]?.trim()
      || requestText?.match(/(?:practice questions|practice problems|questions|problems)\s+(?:on|about)\s+(.+)/i)?.[1]?.trim();
    const currentConcept = journey?.steps.find(step => step.conceptId === conceptId)?.title || journey?.steps[journey.position]?.title;
    const session = await learningApi.getSession(sid);
    const requestedTopic = requestText?.trim() || '';
    const genericRequest = /^(hi|hello|hey|chat|help|quiz(?: me)?|test(?: me)?|new topic|untitled conversation)$/i.test(requestedTopic);
    const topic = explicitTopic || (!genericRequest ? requestedTopic : '') || currentConcept || session.goal?.trim() || '';
    if (!topic || /^(hi|hello|hey|chat|help|quiz(?: me)?|test(?: me)?|new topic|untitled conversation)$/i.test(topic)) {
      setQuizClarification({ sessionId: sid, conceptId, origin, sourceTransitionId });
      setChatMode('ask');
      setPrompt('');
      return false;
    }
    await onQuiz(sid, conceptId, origin, topic, sourceTransitionId);
    return true;
  }, [onQuiz, chatMode, journey]);
  useEffect(() => {
    const receive = () => {
      const sid = initialSessionId || sessionId;
      if (sid) void requestQuiz(sid);
      else { setQuizClarification({ origin: 'ask' }); setChatMode('ask'); setPrompt(''); }
    };
    window.addEventListener(WORKSPACE_QUIZ_REQUEST_EVENT, receive);
    return () => window.removeEventListener(WORKSPACE_QUIZ_REQUEST_EVENT, receive);
  }, [sessionId, initialSessionId, requestQuiz]);

  async function handleAcceptTransition(suggestion: ModeTransitionSuggestion) {
    const sid = sessionId || (typeof suggestion.context?.sessionId === 'string' ? suggestion.context.sessionId : null);
    if (!sid) { setError('This conversation is not ready to switch modes.'); return; }
    let latestJourney = journey;
    let decisionSaved = false;
    const acceptedSuggestion = { ...suggestion, status: 'accepted' as const };
    try {
      if (streaming) await activeGeneration.current?.stop();
      await learningApi.recordTransitionInteraction(suggestion.id, 'accept', suggestion.targetMode, sid, suggestion.modeRevision ?? journey?.modeRevision);
      decisionSaved = true;
      setActiveModeSuggestion(acceptedSuggestion);
      latestJourney = await getJourney(sid);
      applyJourney(latestJourney);
      setWaitingForModeChoice(false);
    } catch (cause) {
      if (decisionSaved) {
        await learningApi.recordTransitionInteraction(suggestion.id, 'failed', suggestion.targetMode, sid).catch(() => undefined);
        setActiveModeSuggestion(acceptedSuggestion);
      }
      setError(decisionSaved ? 'The switch was saved, but the destination could not be loaded. Press Continue to retry.' : cause instanceof Error ? cause.message : 'The mode switch could not be saved. Please retry.');
      return;
    }

    try {
      if (suggestion.targetMode === 'learn') {
        setChatMode('learn');
        setChecking(false);
        if (suggestion.context?.originSummary) setOriginBadge(String(suggestion.context.originSummary));
        try {
          const lessonNote = await learningApi.createStudyNote(sid);
          openWorkspaceNote(lessonNote.noteId);
        } catch { /* Living lesson note is best effort */ }

        const seed = (typeof suggestion.context?.seedPrompt === 'string' ? suggestion.context.seedPrompt : '') ||
          (typeof suggestion.context?.conceptTitle === 'string' ? `Teach me about ${suggestion.context.conceptTitle}` : '');
        if (seed && !latestJourney?.steps.length) {
          setProgress('Planning your learning path…');
          setBusy(true);
          try {
            await workflow(`/sessions/${sid}/journey`, { mode: 'learn', gear, message: seed, action: 'message', expectedRevision: latestJourney?.revision || 1, classificationBypassId: suggestion.id, noteContext }, 'chat');
            const next = await getJourney(sid);
            applyJourney(next);
            if (next.status === 'proposed' && next.steps.length) {
              await streamTurn({ action: 'start', message: '', question: 'Start learning' }, sid);
            }
          } finally {
            setBusy(false);
          }
        } else if (seed) {
          setChecking(false);
          setProgress('Continuing in Learn…');
          await streamTurn({ action: 'message', message: seed, question: seed }, sid, suggestion.id, 'learn');
        }
      } else if (suggestion.targetMode === 'quiz') {
        const launched = await requestQuiz(sid, typeof suggestion.context?.conceptId === 'string' ? suggestion.context.conceptId : undefined,
          typeof suggestion.context?.seedPrompt === 'string' ? suggestion.context.seedPrompt : undefined, suggestion.id);
        if (!launched) { setActiveModeSuggestion(null); return; }
      } else {
        setChatMode('ask');
        setChecking(false);
        const seed = (typeof suggestion.context?.seedPrompt === 'string' ? suggestion.context.seedPrompt : '') ||
          `Please answer directly about ${suggestion.context?.conceptTitle || 'this topic'}.`;
        setProgress('Answering directly…');
        await streamTurn({ action: 'message', message: seed, question: seed }, sid, suggestion.id, 'ask');
      }
      await learningApi.recordTransitionInteraction(suggestion.id, 'applied', suggestion.targetMode, sid);
      setActiveModeSuggestion(null);
    } catch (cause) {
      await learningApi.recordTransitionInteraction(suggestion.id, 'failed', suggestion.targetMode, sid).catch(() => undefined);
      setActiveModeSuggestion(acceptedSuggestion);
      setError(cause instanceof Error ? `Switch saved, but ${suggestion.targetMode === 'quiz' ? 'Quiz' : 'Learn'} did not start: ${cause.message}` : 'Switch saved, but the destination did not start. Press Continue to retry.');
    }
  }

  async function handleDismissTransition(suggestion: ModeTransitionSuggestion) {
    const sid = sessionId || (typeof suggestion.context?.sessionId === 'string' ? suggestion.context.sessionId : null);
    if (sid) {
      try {
        await learningApi.recordTransitionInteraction(suggestion.id, 'dismiss', suggestion.targetMode, sid, suggestion.modeRevision ?? journey?.modeRevision);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'The suggestion could not be dismissed.');
        return;
      }
    }
    setDismissedSuggestions(prev => new Set(prev).add(suggestion.id));
    setActiveModeSuggestion(null);
    const continueRequest = waitingForModeChoice;
    setWaitingForModeChoice(false);
    if (continueRequest) {
      classificationBypass.current = suggestion.id;
      window.setTimeout(() => void submitRef.current?.(), 0);
    }
  }

  useEffect(() => { submitRef.current = submit; });

  useEffect(() => {
    if (!studyTask || !journey?.turns.length || journey.turns.some(turn => turn.status !== 'completed')) return;
    if (!studyTask.canonicalConceptIds.every(id => journey.canonicalConceptIds?.includes(id))) return;
    const sid = journey.sessionId;
    const key = `${studyTask.courseId}:${studyTask.taskId}:${journey.id}`;
    if (completedStudyTask.current === key) return;
    completedStudyTask.current = key;
    void request(`/v1/courses/${encodeURIComponent(studyTask.courseId)}/academic/tasks/${encodeURIComponent(studyTask.taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'completed', workflowId: journey.id, sessionId: sid, revision: studyTask.revision }),
    }).then(() => onStudyTaskCompleted?.()).catch(() => { completedStudyTask.current = null; });
  }, [studyTask, journey, onStudyTaskCompleted]);

  useEffect(() => {
    if (!initialPrompt) return;
    setPrompt(initialPrompt);
    if (preferredMode) setChatMode(preferredMode);
    onInitialPromptConsumed?.();
    if (autoSubmitInitialPrompt) window.setTimeout(() => void submitRef.current?.(), 0);
  }, [initialPrompt, onInitialPromptConsumed, preferredMode, autoSubmitInitialPrompt]);

  // Learn-mode lessons are filed to the session study note automatically; the
  // chat keeps a receipt per lesson. Filed state survives journey reloads via
  // localStorage so restored sessions stay receipt-only too.
  type FiledLesson = { noteId: string; heading: string };
  const filedRef = useRef<Record<string, FiledLesson>>({});
  function filedKey(sid: string) { return `forma-filed-lessons:${sid}`; }
  const recallFiled = useCallback((sid: string) => {
    let next: Record<string, FiledLesson> = {};
    try {
      const raw = JSON.parse(localStorage.getItem(`forma-filed-lessons:${sid}`) || 'null') as unknown;
      if (raw && typeof raw === 'object') next = raw as Record<string, FiledLesson>;
    } catch { next = {}; }
    filedRef.current = next;
  }, []);
  function rememberFiled(sid: string, lessonId: string, receipt: FiledLesson) {
    const next = { ...filedRef.current, [lessonId]: receipt };
    filedRef.current = next;
    try { localStorage.setItem(filedKey(sid), JSON.stringify(next)); } catch { /* Filed state stays in memory. */ }
  }

  async function announceApplied(result: { proposalId?: string; status?: string; heading?: string; noteId?: string; applyKind?: string } | null, sid: string) {
    if (result?.status !== 'applied') return;
    const announce = (noteId: string, heading: string, applyKind: 'added' | 'refined') => {
      setAppliedNote({ heading, noteId, applyKind });
    };
    if (result.heading && result.noteId) {
      announce(result.noteId, result.heading, result.applyKind === 'refined' ? 'refined' : 'added');
      return;
    }
    if (!result?.proposalId) return;
    try {
      const items = await learningApi.listNoteProposals(sid);
      const item = items.proposals.find(entry => entry.id === result.proposalId);
      if (item) announce(item.noteId, item.heading, 'added');
    } catch { /* The toast is optional; the Lesson still updated in Notes. */ }
  }
  const autoOpenedSessions = useRef<Set<string>>(new Set());
  const scrollArea = useRef<HTMLDivElement | null>(null);
  const activeGeneration = useRef<GenerationStream | null>(null);
  const activeSubmissionSessionId = useRef<string | null>(null);
  const isNearBottomRef = useRef(true);
  const isProgrammaticScrollRef = useRef(false);
  const [hasNewContentBelow, setHasNewContentBelow] = useState(false);
  const scrollRafRef = useRef<number | null>(null);
  const lesson = [...turns].reverse().find(turn => turn.lesson)?.lesson || null;
  function rememberGeneration(value: GenerationRecovery | null) { try { if (value) localStorage.setItem('forma-generation', JSON.stringify(value)); else localStorage.removeItem('forma-generation'); } catch { /* Recovery remains in memory. */ } }

  const checkIfNearBottom = useCallback(() => {
    const el = scrollArea.current;
    if (!el) return true;
    const threshold = 120;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    return distance <= threshold;
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollArea.current;
    if (!el) return;
    isProgrammaticScrollRef.current = true;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth && !reduceMotion ? 'smooth' : 'auto',
    });
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        isProgrammaticScrollRef.current = false;
        isNearBottomRef.current = true;
        setHasNewContentBelow(false);
      });
    });
  }, [reduceMotion]);

  useEffect(() => {
    const el = scrollArea.current;
    if (!el) return;
    const onScroll = () => {
      if (isProgrammaticScrollRef.current) return;
      const nearBottom = checkIfNearBottom();
      isNearBottomRef.current = nearBottom;
      if (nearBottom) {
        setHasNewContentBelow(false);
      }
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [checkIfNearBottom]);

  // When turns length changes (new user question or assistant response added):
  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom(turns.length > 1);
    } else if (streaming) {
      setHasNewContentBelow(true);
    }
  }, [turns.length, streaming, scrollToBottom]);

  useEffect(() => {
    const refresh = (event: Event) => { if ((event as CustomEvent<string>).detail === sessionId) setVoiceRefresh(value => value + 1); };
    window.addEventListener(VOICE_REFRESH, refresh);
    return () => window.removeEventListener(VOICE_REFRESH, refresh);
  }, [sessionId]);
  useEffect(() => { reportVoiceFocus({ lesson_id: lesson?.id || null }); }, [lesson?.id]);
  async function startVoice() {
    try {
      const capabilities = await voiceApi.capabilities();
      if (!capabilities.enabled) { await voice?.start(sessionId || ''); return; }
      const current = sessionId ? { id: sessionId } : await learningApi.createSession({ topic: 'Study conversation', goal: 'Study with Buddy', gear, courseId: courseId ?? undefined, buddyId: buddies.active?.id });
      if (!sessionId) { setSessionId(current.id); onSessionCreated?.(current.id); }
      await voice?.start(current.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not start voice.'); }
  }
  function applyJourney(next: Journey) { setJourney(next); setTurns(next.turns); setChatMode(next.mode); setGear(next.gear); }
  useEffect(() => {
    let active = true;
    async function restore() {
      try {
        const sid = initialSessionId;
        if (!sid) return;
        if (activeSubmissionSessionId.current === sid) {
          // Submission in flight for this session; skip restore to avoid race conditions.
          return;
        }
        setBusy(true); setSessionId(sid);
        rememberSessionHint(sid);
        navigateToSession(sid, true);
        const pending = (() => { try { return localStorage.getItem('forma-job:chat'); } catch { return null; } })();
        if (pending) await waitForJob(pending, 'chat');
        // Snapshot-first: committed pointers come from the server even with cleared localStorage.
        const { journey: saved } = await restoreSessionAuthority(sid);
        if (active) {
          applyJourney(saved);
          const presentation = restoredPresentation.current;
          if (presentation === 'conversation' || presentation === 'ask' || presentation === 'learn' || presentation === 'quiz') { setChatMode(presentation === 'conversation' ? 'ask' : presentation); setConversation(presentation === 'conversation'); }
          recallFiled(sid);
          const transition = await learningApi.getPendingModeTransition(sid).catch(() => ({ pending: null }));
          if (active && transition.pending) {
            setActiveModeSuggestion(transition.pending.suggestion);
            const waiting = transition.pending.status === 'pending' && transition.pending.decision === 'request_transition';
            setWaitingForModeChoice(waiting);
            if (waiting && transition.pending.originalRequest) setPrompt(transition.pending.originalRequest);
          }
          if (saved.turns.length > 0) {
            autoOpenedSessions.current.add(sid);
          }
        }
        if (active && saved.mode === 'learn') {
          try { const note = await learningApi.createStudyNote(sid); if (active) openWorkspaceNote(note.noteId); } catch { /* Optional; teaching remains available. */ }
        }
        const recovery = (() => {
          try { return JSON.parse(localStorage.getItem('forma-generation') || 'null') as GenerationRecovery | null; }
          catch { return null; }
        })();
        if (active && recovery?.sessionId === sid) {
          const stream = new GenerationStream(); activeGeneration.current = stream;
          setBusy(true); setStreaming(true); setProgress('Reconnecting to your lesson…');
          let replayExpired = false;
          await stream.resume({ id: recovery.generationId, sessionId: recovery.sessionId, mode: recovery.mode, status: recovery.status, sequence: recovery.lastAppliedSequence, provider: '', model: '' }, {
            onEvent: event => {
              if (event.type === 'generation.error' && event.data.code === 'REPLAY_EXPIRED') replayExpired = true;
              else if (event.type === 'generation.error') setError('The previous generation could not be completed.');
              if (['generation.completed', 'generation.cancelled', 'generation.error'].includes(event.type)) rememberGeneration(null);
            },
            onSequence: sequence => rememberGeneration({ ...recovery, lastAppliedSequence: sequence }),
          });
          // REPLAY_EXPIRED is a canonical-reconciliation signal: refetch snapshot + Journey.
          if (active) {
            if (replayExpired) {
              const reconciled = await restoreSessionAuthority(sid);
              applyJourney(reconciled.journey);
            } else {
              applyJourney(await getJourney(sid));
            }
          }
          rememberGeneration(null); activeGeneration.current = null; setStreaming(false);
        }
      } catch (cause) {
        if (!active || activeSubmissionSessionId.current === (initialSessionId)) return;
        if (isStaleSessionConflict(cause)) {
          setError('This tab is out of date. Reloading the latest session…');
          try {
            const sid = initialSessionId;
            if (sid) applyJourney((await restoreSessionAuthority(sid)).journey);
          } catch { /* Keep the stale notice. */ }
          return;
        }
        if (cause instanceof LearningApiError && cause.status === 404) {
          rememberSessionHint(null);
          navigateToSession(null, true);
          setSessionId(null);
          onMissingSession?.();
          if (initialSessionId) {
            setError('That conversation is no longer available.');
          }
          return;
        }
        setError(cause instanceof Error ? cause.message : 'Could not restore the conversation.');
      }
      finally {
        if (active && activeSubmissionSessionId.current !== (initialSessionId)) {
          setBusy(false);
        }
      }
    }
    void restore(); return () => { active = false; };
  }, [initialSessionId, recallFiled, voiceRefresh]);

  useEffect(() => {
    const receiveExcerpt = (event: Event) => {
      const mention = (event as CustomEvent<WorkspaceNoteMention>).detail;
      if (!mention || mention.startOffset >= mention.endOffset) return;
      setNoteMentions(current => [
        ...current.filter(item => item.noteId !== mention.noteId),
        mention,
      ]);
      setError('');
      if (mention.prompt) setPrompt(current => current.trim() ? `${current}\n\n${mention.prompt}` : mention.prompt!);
    };
    window.addEventListener(WORKSPACE_NOTE_MENTION_EVENT, receiveExcerpt);
    return () => window.removeEventListener(WORKSPACE_NOTE_MENTION_EVENT, receiveExcerpt);
  }, []);

  useEffect(() => {
    const ask = (event: Event) => { const text = (event as CustomEvent<string>).detail; if (typeof text === 'string') setPrompt(current => current.trim() ? `${current}\n\n${text}` : text); };
    const capture = () => {
      const body = turns.map(turn => `## ${turn.question}\n\n${captureReadingBlocks(turn.lesson?.blocks || turn.stream?.blocks || turn.answer?.blocks || [], turn.lesson?.id)}`).join('\n\n---\n\n');
      if (body.trim()) openWorkspaceNoteDraft({ title: 'Conversation notes', body, frontmatter: { source: 'conversation_capture', session_ids: sessionId ? [sessionId] : [] } });
      else setPrompt('Help me start a study note about ');
    };
    window.addEventListener(WORKSPACE_ASK_EVENT, ask); window.addEventListener(WORKSPACE_CAPTURE_EVENT, capture);
    return () => { window.removeEventListener(WORKSPACE_ASK_EVENT, ask); window.removeEventListener(WORKSPACE_CAPTURE_EVENT, capture); };
  }, [turns, sessionId]);

  useEffect(() => {
    const improve = (event: Event) => {
      const target = (event as CustomEvent<WorkspaceNoteMention>).detail;
      if (!target?.noteId || busy) return;
      setBusy(true); setError(''); setProgress('Preparing a reviewable note suggestion...');
      void (async () => {
        try {
          const sid = sessionId || (await learningApi.createSession({topic: target.title, goal: 'Refine a selected note passage', courseId: courseId || undefined})).id;
          if (!sessionId) { setSessionId(sid); rememberSessionHint(sid); navigateToSession(sid); }
          const range = {noteId: target.noteId, expectedRevision: target.revision, startOffset: target.startOffset, endOffset: target.endOffset};
          const result = await workflow(`/sessions/${sid}/note-drafts`, {originKind: 'mentioned_notes', noteContext: {notes: [range]}, replacement: range}, `note-improvement:${crypto.randomUUID()}`);
          if (!result?.noteDraftId) throw new Error('The suggestion could not be recovered.');
          const draft = await learningApi.getNoteDraft(result.noteDraftId);
          setNoteDrafts(current => [...current.filter(item => item.id !== draft.id), draft]);
        } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not prepare a suggestion.'); }
        finally { setBusy(false); }
      })();
    };
    window.addEventListener(WORKSPACE_NOTE_IMPROVE_EVENT, improve); return () => window.removeEventListener(WORKSPACE_NOTE_IMPROVE_EVENT, improve);
  }, [busy, sessionId, courseId]);

  useEffect(() => {
    const receiveReplacementTarget = (event: Event) => {
      const target = (event as CustomEvent<ReplacementTarget>).detail;
      if (!target || target.startOffset >= target.endOffset) return;
      setReplacementTarget(target); setError(`Selected section in “${target.title}” is ready for a draft replacement.`);
    };
    window.addEventListener(WORKSPACE_NOTE_REPLACE_DRAFT_EVENT, receiveReplacementTarget);
    return () => window.removeEventListener(WORKSPACE_NOTE_REPLACE_DRAFT_EVENT, receiveReplacementTarget);
  }, []);
  const noteContext = noteMentions.length ? { notes: noteMentions.map(note => ({ noteId: note.noteId, expectedRevision: note.revision, startOffset: note.startOffset, endOffset: note.endOffset })) } : undefined;

  async function addNoteMention(summary: WorkspaceNoteSummary) {
    try {
      const note = await learningApi.getWorkspaceNote(summary.id);
      if (note.body.length > 6000) { setError(`“${note.title}” is too long to mention as a whole note. Select a shorter passage from the note first.`); return; }
      setNoteMentions(current => current.some(item => item.noteId === note.id) ? current : [...current, { noteId: note.id, title: note.title, revision: note.revision, startOffset: 0, endOffset: note.body.length, excerpt: note.body }]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'This note could not be added as context.'); }
  }

  async function createQuizFeedbackDraft(attemptId: string) {
    if (!sessionId || busy) return;
    setBusy(true); setError(''); setProgress('Preparing a repair note draft…');
    try {
      const result = await workflow(`/sessions/${sessionId}/note-drafts`, { originKind: 'quiz_feedback', quizAttemptId: attemptId, replacement: replacementTarget ? { noteId: replacementTarget.noteId, expectedRevision: replacementTarget.revision, startOffset: replacementTarget.startOffset, endOffset: replacementTarget.endOffset } : undefined }, `note-draft:quiz:${attemptId}`);
      if (!result?.noteDraftId) throw new Error('The note draft could not be recovered.');
      const draft = await learningApi.getNoteDraft(result.noteDraftId);
      setNoteDrafts(current => [...current.filter(item => item.id !== draft.id), draft]); setReplacementTarget(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create a repair note draft.'); }
    finally { setBusy(false); }
  }
  async function saveSelectionInsight() {
    const sid = selection?.sessionId || sessionId;
    if (!selection || !sid || busy) return;
    setBusy(true); setError('');
    try {
      await learningApi.saveStudyInsight(sid, { body: selection.selectedText });
      setSelection(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The insight could not be saved.'); }
    finally { setBusy(false); }
  }
  async function proposeInsight(sourceText: string, label: string, sid: string | null) {
    const target = sid || sessionId;
    if (!target || busy || !sourceText.trim()) return;
    setBusy(true); setError(''); setAppliedNote(null); setProgress('Distilling this insight for your note…');
    try {
      const link = await learningApi.getStudyNote(target).catch(() => null);
      const result = await workflow(`/sessions/${target}/note-proposals`, {
        origin: 'insight', sourceText: sourceText.slice(0, 4000), sourceLabel: label.slice(0, 200),
        expectedNoteRevision: link?.revision ?? null,
      }, `note-proposal:insight:${target}:${crypto.randomUUID()}`);
      await announceApplied(result, target);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The insight could not be proposed.'); }
    finally { setBusy(false); }
  }
  // Quietly evolve the living Lesson after meaningful Learn turns. The chat
  // stays primary; synthesis skips chatter and may refine existing sections.
  async function evolveLessonFromNewest(sid: string) {
    try {
      const next = await getJourney(sid);
      const lessonTurns = next.turns.filter(turn => turn.lesson);
      const newest = lessonTurns.at(-1);
      const lessonId = newest?.lesson?.id;
      if (!lessonId || filedRef.current[lessonId]) return;
      const lessonIndex = lessonTurns.length - 1;
      const link = await learningApi.getStudyNote(sid).catch(() => learningApi.createStudyNote(sid));
      const result = await workflow(
        `/sessions/${sid}/note-proposals`,
        { origin: 'turn', turnIndex: lessonIndex, expectedNoteRevision: link?.revision ?? null },
        `note-proposal:${sid}:${lessonIndex}`,
      );
      if (!result || result.status === 'skipped' || (result as { skipped?: string }).skipped) return;
      if (result.status === 'applied') {
        rememberFiled(sid, lessonId, { noteId: String(result.noteId || link?.noteId || ''), heading: String(result.heading || 'Lesson') });
        await announceApplied(result, sid);
      }
    } catch {
      /* Chat remains the source of truth; Lesson growth is best-effort. */
    }
  }
  async function fileNewestLearnLesson(next: Journey, sid: string) {
    const lessonTurns = next.turns.filter(turn => turn.lesson);
    const lessonId = lessonTurns.at(-1)?.lesson?.id;
    if (!lessonId || filedRef.current[lessonId]) return;
    await evolveLessonFromNewest(sid);
  }
  async function journeyAction(action: string) {
    if (!sessionId || busy) return;
    const wasLearn = chatMode === 'learn';
    if (['start', 'next', 'repair'].includes(action)) {
      await streamTurn({ action: action as 'start' | 'next' | 'repair', message: '', question: action === 'start' ? 'Start learning' : action === 'repair' ? 'Help me understand this differently' : 'Continue' });
      return;
    }
    setBusy(true); setError(''); setProgress('Preparing the next learning step…');
    try {
      await workflow(`/sessions/${sessionId}/journey`, { action, mode: chatMode, gear, message: action === 'adjust' ? prompt : '', expectedRevision: journey?.revision || 1, noteContext }, 'chat');
      const next = await getJourney(sessionId);
      applyJourney(next);
      if (wasLearn) await fileNewestLearnLesson(next, sessionId);
      scrollToBottom(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Please try again.'); }
    finally { setBusy(false); }
  }

  async function streamTurn(input: { action: 'message' | 'start' | 'next' | 'repair'; message: string; question: string }, sid = sessionId, bypassId?: string | null, modeOverride?: ChatMode) {
    if (!sid || busy) return;
    const submittedDraft = prompt;
    const requestMode = modeOverride || chatMode;
    const stream = new GenerationStream();
    activeGeneration.current = stream;
    let finalError = '';
    let streamId = '';
    let replayExpired = false;
    setBusy(true); setStreaming(true); setError(''); setProgress('Preparing your lesson…'); setActivity(null);
    try {
      await stream.start(sid, { mode: requestMode === 'learn' ? 'learn' : 'ask', gear, message: input.message, action: input.action, expectedRevision: journey?.revision || 1, classificationBypassId: bypassId || undefined, taskId: studyTask?.taskId, canonicalConceptIds: studyTask?.canonicalConceptIds, noteContext }, {
        onEvent: (event: GenerationEvent) => {
          if (event.type === 'tool.started' && event.data.tool === 'search_web_evidence') {
            const query = typeof event.data.query === 'string' ? event.data.query : undefined;
            setActivity({ type: 'web_search', status: 'searching', query, sourceCount: 0 });
            return;
          }
          if (event.type === 'source.added') {
            setActivity(current => {
              if (!current || current.type !== 'web_search') return current;
              return { ...current, sourceCount: current.sourceCount + 1 };
            });
            return;
          }
          if (event.type === 'tool.completed' && event.data.tool === 'search_web_evidence') {
            const ok = event.data.ok !== false;
            const count = typeof event.data.sourceCount === 'number' ? event.data.sourceCount : undefined;
            setActivity(current => {
              if (!current || current.type !== 'web_search') return current;
              if (!ok) return { ...current, status: 'error' };
              return { ...current, status: 'complete', sourceCount: count ?? current.sourceCount };
            });
            return;
          }
          if (event.type === 'generation.context_ready') {
            setProgress('Writing your lesson…');
            setActivity(current => {
              if (current && current.type === 'web_search' && current.status !== 'error') {
                return { type: 'synthesizing' };
              }
              return current;
            });
            return;
          }
          if (event.type === 'lesson.block_started') {
            setActivity(current => {
              if (current && current.type === 'synthesizing') {
                return { type: 'writing' };
              }
              return current;
            });
            const block = event.data.block as { id?: string; kind?: string; heading?: string } | undefined;
            streamId = event.generationId;
            const nextBlock: StreamedBlock = { id: block?.id || `${event.generationId}-block`, kind: block?.kind || 'explanation', heading: block?.heading || 'Working through it', body: '', status: 'streaming' };
            setTurns(current => {
              const index = current.findIndex(turn => turn.generationId === event.generationId || turn.stream?.id === event.generationId);
              if (index >= 0) return current.map((turn, turnIndex) => turnIndex === index ? { ...turn, stream: { ...turn.stream, id: event.generationId, blocks: [...(turn.stream?.blocks || []), nextBlock], status: 'streaming' } } : turn);
              return [...current, { question: input.question, sessionId: sid, generationId: event.generationId, status: 'pending', stream: { id: event.generationId, blocks: [nextBlock], status: 'streaming' } }];
            });
            return;
          }
          if (event.type === 'visualization.planning') {
            setTurns(current => current.map(turn => turn.generationId === event.generationId
              ? { ...turn, stream: { id: event.generationId, blocks: turn.stream?.blocks || [], status: 'streaming', ...turn.stream, visualPending: true } }
              : turn));
            return;
          }
          if (event.type === 'visualization.skipped') {
            setTurns(current => current.map(turn => turn.stream?.id === event.generationId
              ? { ...turn, stream: { ...turn.stream, visualPending: false } } : turn));
            return;
          }
          if (event.type === 'visualization.ready') {
            const spec = parseVisualization(event.data.spec);
            if (!spec) return;
            setTurns(current => current.map(turn => {
              if (turn.stream?.id !== event.generationId) return turn;
              return { ...turn, stream: { ...turn.stream, visualPending: false,
                visualizations: [...(turn.stream.visualizations || []), spec] } };
            }));
            return;
          }
          if (event.type === 'text.delta') {
            setActivity(null);
            const text = typeof event.data.text === 'string' ? event.data.text : '';
            const blockId = String(event.data.blockId || '');
            setTurns(current => current.map(turn => turn.stream?.id === event.generationId ? { ...turn, stream: { ...turn.stream, blocks: turn.stream.blocks.map(block => block.id === blockId ? { ...block, body: block.body + text } : block) } } : turn));
            if (isNearBottomRef.current) {
              if (!scrollRafRef.current) {
                scrollRafRef.current = window.requestAnimationFrame(() => {
                  scrollRafRef.current = null;
                  if (isNearBottomRef.current && scrollArea.current) {
                    isProgrammaticScrollRef.current = true;
                    scrollArea.current.scrollTop = scrollArea.current.scrollHeight;
                    window.requestAnimationFrame(() => {
                      isProgrammaticScrollRef.current = false;
                    });
                  }
                });
              }
            } else {
              setHasNewContentBelow(true);
            }
            return;
          }
          if (event.type === 'lesson.block_completed') {
            const blockId = String(event.data.blockId || '');
            setTurns(current => current.map(turn => turn.stream?.id === event.generationId ? { ...turn, stream: { ...turn.stream, blocks: turn.stream.blocks.map(block => block.id === blockId ? { ...block, status: 'completed' } : block) } } : turn));
            return;
          }
          if (event.type === 'generation.error' && event.data.code === 'REPLAY_EXPIRED') replayExpired = true;
          else if (event.type === 'generation.error') {
            finalError = typeof event.data.message === 'string' ? event.data.message : 'The lesson could not be completed.';
            setActivity(null);
          }
          if (event.type === 'generation.cancelled') {
            finalError = 'Generation stopped. Your previous lessons are still saved.';
            setActivity(null);
          }
          if (event.type === 'generation.completed') {
            setActivity(null);
          }
        },
        onReconnect: () => setProgress('Reconnecting to your lesson…'),
        onDescriptor: descriptor => {
          rememberGeneration({ generationId: descriptor.id, sessionId: sid, mode: descriptor.mode, lastAppliedSequence: descriptor.sequence, status: descriptor.status });
          if (descriptor.journeyRevision) setJourney(current => current ? { ...current, revision: descriptor.journeyRevision! } : current);
          setTurns(current => current.some(turn => turn.generationId === descriptor.id) ? current : [...current, {
            question: input.question, sessionId: sid, generationId: descriptor.id, status: 'pending',
          }]);
        },
        onSequence: sequence => {
          const descriptor = stream.descriptor;
          if (descriptor) rememberGeneration({ generationId: descriptor.id, sessionId: sid, mode: descriptor.mode, lastAppliedSequence: sequence, status: 'streaming' });
        },
      });
      if (stream.wasCancelled) throw new Error('Generation stopped. Your previous lessons are still saved.');
      if (finalError) throw new Error(finalError);
      if (replayExpired) applyJourney((await restoreSessionAuthority(sid)).journey);
      else applyJourney(await getJourney(sid));
      rememberGeneration(null);
      setPrompt(current => current === submittedDraft ? '' : current); setNoteMentions([]);
      if (requestMode === 'learn') void evolveLessonFromNewest(sid);
    } catch (cause) {
      setActivity(null);
      if (isStaleSessionConflict(cause)) {
        try { applyJourney((await restoreSessionAuthority(sid)).journey); setError('This tab was out of date. Showing the latest committed lesson.'); }
        catch { setError('This tab is out of date. Reload to continue.'); }
      } else {
        try { applyJourney(await getJourney(sid)); }
        catch { setTurns(current => current.map(turn => turn.generationId === streamId ? { ...turn, stream: undefined, status: 'failed' } : turn)); }
        setError(cause instanceof Error ? cause.message : 'The lesson could not be completed.');
      }
    } finally {
      activeGeneration.current = null; setStreaming(false); setBusy(false); setActivity(null);
      if (isNearBottomRef.current) {
        scrollToBottom(true);
      }
    }
  }

  async function explainSelection(selected: SelectedPassage, question = 'Explain this selected passage') {
    const sid = selected.sessionId || sessionId;
    if (!sid || busy) return;
    const stream = new GenerationStream(); activeGeneration.current = stream;
    setSelection(null); setSelectionPanel({ selection: selected, blocks: [], status: 'preparing' }); setBusy(true);
    try {
      await stream.start(sid, { mode: 'ask', gear, message: question, action: 'message', expectedRevision: journey?.revision || 1,
        selectedText: selected.selectedText, selectedLessonId: selected.lessonId, selectedBlockId: selected.blockId, noteContext }, {
        onEvent: event => {
          if (event.type === 'lesson.block_started') {
            const raw = event.data.block as { id?: string; kind?: string; heading?: string } | undefined;
            const block: StreamedBlock = { id: raw?.id || `${event.generationId}-selection`, kind: raw?.kind || 'explanation', heading: raw?.heading || 'A closer look', body: '', status: 'streaming' };
            setSelectionPanel(current => current ? { ...current, status: 'streaming', blocks: [...current.blocks, block] } : current); return;
          }
          if (event.type === 'text.delta') {
            const blockId = String(event.data.blockId || ''); const text = String(event.data.text || '');
            setSelectionPanel(current => current ? { ...current, blocks: current.blocks.map(block => block.id === blockId ? { ...block, body: block.body + text } : block) } : current); return;
          }
          if (event.type === 'lesson.block_completed') {
            const blockId = String(event.data.blockId || '');
            setSelectionPanel(current => current ? { ...current, blocks: current.blocks.map(block => block.id === blockId ? { ...block, status: 'completed' } : block) } : current); return;
          }
          if (event.type === 'generation.error') setSelectionPanel(current => current ? { ...current, status: 'error', error: String(event.data.message || 'Could not explain this selection.') } : current);
          if (event.type === 'generation.cancelled') setSelectionPanel(current => current ? { ...current, status: 'error', error: 'Explanation stopped.' } : current);
        },
      });
      if (!stream.wasCancelled) { setSelectionPanel(current => current ? { ...current, status: 'completed' } : current); applyJourney(await getJourney(sid)); }
    } catch (cause) {
      setSelectionPanel(current => current ? { ...current, status: 'error', error: cause instanceof Error ? cause.message : 'Could not explain this selection.' } : current);
      try { applyJourney(await getJourney(sid)); } catch { /* Keep the visible selection error. */ }
    } finally { activeGeneration.current = null; setBusy(false); }
  }

  async function submit(quickAction?: string) {
    const submittedDraft = prompt;
    const clearSubmittedDraft = () => setPrompt(current => current === submittedDraft ? '' : current);
    const text = quickAction?.trim() || prompt.trim() || (attachments.length ? `Help me understand ${attachments.map(item => item.name).join(', ')}` : '');
    if (!text || busy) return;
    if (!buddies.active) { setError('Reconnect to Open Learn before sending. Your draft is still here.'); void buddies.refresh(); return; }
    if (buddies.active.archived && !sessionId) { setError('Choose an active Buddy to start a new conversation.'); return; }
    setClassActionReply('');
    if(onInClass && !attachments.length && /^(?:please\s+)?(?:start (?:taking notes|listening|recording)(?: for (?:this|my) class)?|start (?:an? )?in[- ]class (?:mode|session))\s*[.!]?$/i.test(text)){clearSubmittedDraft();onInClass();return;}
    if(!attachments.length){
      const intent=parseClassReferenceOpenRequest(text);
      const opened=intent?await requestClassReferenceOpen(intent,initialSessionId||sessionId):null;
      if(opened){clearSubmittedDraft();setClassActionReply(`Opened ${opened.title} · Page ${opened.pageIndex+1} in your live class.`);setProgress('');return;}
    }
    if (quizClarification) {
      const pending = quizClarification;
      setQuizClarification(null);
      clearSubmittedDraft();
      try {
        const sid = pending.sessionId || (await learningApi.createSession({ topic: text.slice(0, 200), goal: text.slice(0, 1000), gear, courseId: courseId ?? undefined, buddyId:buddies.active?.id })).id;
        await buddyApi.mode(sid, 'quiz');
        if (!pending.sessionId) {
          if (draftKey) { localStorage.removeItem(draftKey); chatDraftFiles.delete(draftKey); }
          setSessionId(sid); rememberSessionHint(sid); navigateToSession(sid);
          onSessionCreated?.(sid); void buddies.refresh();
          window.dispatchEvent(new CustomEvent('forma:chat-history-changed'));
        }
        await onQuiz?.(sid, pending.conceptId, pending.origin, text, pending.sourceTransitionId);
        if (pending.sourceTransitionId) await learningApi.recordTransitionInteraction(pending.sourceTransitionId, 'applied', 'quiz', sid);
      }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not start the quiz.'); }
      return;
    }
    const bypassId = classificationBypass.current;
    classificationBypass.current = null;
    setBusy(true); setError('');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 170000);
    try {
      setProgress(attachments.length ? 'Reading your attachments…' : 'Thinking about that…');
      const currentSession = sessionId ? { id: sessionId } : await learningApi.createSession({ topic: text.slice(0, 200), goal: text.slice(0, 1000), gear, courseId: courseId ?? undefined, buddyId:buddies.active?.id });
      await buddyApi.mode(currentSession.id,chatMode==='ask'&&conversation?'conversation':chatMode);
      if(!sessionId){try{if(draftKey){localStorage.removeItem(draftKey);chatDraftFiles.delete(draftKey);}}catch{/* optional draft */}onSessionCreated?.(currentSession.id);void buddies.refresh();}
      activeSubmissionSessionId.current = currentSession.id;
      if (!sessionId) setSessionId(currentSession.id);
      rememberSessionHint(currentSession.id);
      navigateToSession(currentSession.id, !sessionId);
      if (!sessionId) window.dispatchEvent(new CustomEvent('forma:chat-history-changed'));
      scrollToBottom(true);
      const ready: ChatAttachment[] = [];
      for (const item of attachments) ready.push(await prepareAttachment(item, controller.signal, uploaded => setAttachments(previous => previous.map(existing => existing.id === uploaded.id ? uploaded : existing))));
      const versions = ready.map(item => item.versionId!);
      for (const version of attachedVersions.current.filter(id => !versions.includes(id))) {
        await materialRequest(`/sessions/${currentSession.id}/materials/${version}`, { method: 'DELETE', signal: controller.signal });
        attachedVersions.current = attachedVersions.current.filter(id => id !== version);
      }
      for (const version of versions.filter(id => !attachedVersions.current.includes(id))) {
        await materialRequest(`/sessions/${currentSession.id}/materials`, materialCommand({ materialVersionId: version }, controller.signal));
        attachedVersions.current.push(version);
      }
      if (await browserAssistant.tryStart(text, currentSession.id, ready.map(item=>({versionId:item.versionId!,name:item.name})),chatMode==='ask'&&conversation?'conversation':chatMode)) {
        clearSubmittedDraft(); setProgress(''); return;
      }
      // Learn always owns a Lesson in Notes first. Chat stays the place to go
      // deeper, quiz, and continue — the Lesson is the persistent study doc.
      const isInitialLearnTurn = chatMode === 'learn' && (!sessionId || turns.length === 0 || !autoOpenedSessions.current.has(currentSession.id));
      if (chatMode === 'learn') {
        setProgress('Creating your lesson…');
        try {
          const lessonNote = await learningApi.createStudyNote(currentSession.id);
          if (isInitialLearnTurn) {
            autoOpenedSessions.current.add(currentSession.id);
            openWorkspaceNote(lessonNote.noteId);
          }
        } catch {
          /* Teaching still proceeds; the server also ensures a Lesson exists. */
        }
      }
      const urls = Array.from(new Set(text.match(/https?:\/\/[^\s<>]+/gi) || []));
      for (const link of urls) await materialRequest(`/sessions/${currentSession.id}/url-materials`, materialCommand({ url: link }, controller.signal));
      if (chatMode === 'quiz') {
        const origin = quizOrigin.current;
        clearSubmittedDraft(); setNoteMentions([]);
        await requestQuiz(currentSession.id, undefined, text, undefined, origin);
        return;
      }
      let classifiedSuggestion: ModeTransitionSuggestion | null = null;
      try {
        const classification = await learningApi.classifyMode(currentSession.id, text, chatMode === 'learn' ? 'learn' : 'ask', bypassId || undefined);
        classifiedSuggestion = classification.suggestion || null;
        if (classifiedSuggestion) {
          setActiveModeSuggestion(classifiedSuggestion);
          if (classification.decision === 'request_transition') {
            setWaitingForModeChoice(true);
            setBusy(false);
            setProgress('');
            return;
          }
        } else if (!bypassId) {
          setActiveModeSuggestion(null);
        }
      } catch {
        // Classification is advisory; failures keep the established chat path available.
      }
      // Initial Learn prompts produce a route proposal, then teaching starts in
      // chat. After each turn the Lesson in Notes grows selectively.
      if (chatMode === 'learn' && !journey?.steps.length) {
        setProgress('Planning your learning path…');
        await workflow(`/sessions/${currentSession.id}/journey`, { mode: chatMode, gear, message: text, action: 'message', expectedRevision: journey?.revision || 1, classificationBypassId: classifiedSuggestion?.id || bypassId || undefined, taskId: studyTask?.taskId, canonicalConceptIds: studyTask?.canonicalConceptIds, noteContext }, 'chat');
        const next = await getJourney(currentSession.id);
        applyJourney(next); clearSubmittedDraft(); setNoteMentions([]);
        setBusy(false);
        if (next.status === 'proposed' && next.steps.length) {
          await streamTurn({ action: 'start', message: '', question: 'Start learning' }, currentSession.id);
        }
      } else {
        setBusy(false);
        await streamTurn({ action: 'message', message: text, question: text }, currentSession.id, classifiedSuggestion?.id || bypassId);
      }
      if (!sessionId) void learningApi.regenerateChatTitle(currentSession.id, true).then(() => { window.dispatchEvent(new CustomEvent('forma:chat-title-changed')); window.dispatchEvent(new CustomEvent('forma:chat-history-changed')); }).catch(() => undefined);
    } catch (cause) {
      setError(cause instanceof DOMException && cause.name === 'AbortError' ? 'This model is taking too long to respond. Try a shorter question or try again.' : cause instanceof Error ? cause.message : 'The lesson could not be completed. Please try again.');
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
      activeSubmissionSessionId.current = null;
    }
  }

  const activeConcept = journey?.steps[journey.position];
  const contextConcept = selectedConcept || (activeConcept && activeConcept.conceptId !== dismissedConceptId ? { id: activeConcept.conceptId, title: activeConcept.title } : null);
  const latestTurn = turns.at(-1);
  const latestTurnKey = latestTurn?.generationId || latestTurn?.lesson?.id || latestTurn?.stream?.id || '';
  const latestBodies = latestTurn?.lesson?.blocks.map(block => block.body) || latestTurn?.stream?.blocks.map(block => block.body) || latestTurn?.answer?.blocks.map(block => block.body) || [];
  const unresolvedExercise = latestBodies.flatMap(body => splitTutorContent(body)).some(part => part.kind === 'exercise' && !resolvedExercises.has(`${latestTurnKey}:${part.exercise.id}`));
  function chooseMode(mode: ChatMode, conversational = false) {
    if (activeModeSuggestion?.status === 'accepted') { setError('Continue the saved mode switch before choosing another mode.'); return; }
    if (activeModeSuggestion) {
      const suggestion = activeModeSuggestion;
      const sid = sessionId || suggestion.context.sessionId;
      if (sid) void learningApi.recordTransitionInteraction(suggestion.id, 'dismiss', suggestion.targetMode, sid, suggestion.modeRevision ?? journey?.modeRevision).catch(() => undefined);
      setActiveModeSuggestion(null); setWaitingForModeChoice(false);
    }
    if (mode === 'quiz') quizOrigin.current = chatMode === 'learn' ? 'learn' : 'ask';
    setConversation(conversational); setChatMode(mode);
    if (sessionId) void buddyApi.mode(sessionId, conversational ? 'conversation' : mode).then(()=>buddies.refresh()).catch(()=>setError('Mode changed for this visit, but could not be saved. Please try again.'));
  }
  return <div className={styles.chatShell}>
    <VoiceHistory chatId={sessionId} />
    <div ref={scrollArea} className={styles.chatScroll}>
    <div className={`${styles.page} ${turns.length ? styles.reading : styles.empty}`}>
    {courseName ? (
      <div className={styles.courseBadgeRow}>
        <button
          type="button"
          className={styles.courseBadge}
          onClick={() => courseId && onCourseClick?.(courseId)}
          title={`Part of course: ${courseName}`}
        >
          <GraduationCap size={14} />
        </button>
      </div>
    ) : null}
    <AnimatePresence>
      {originBadge ? (
        <OriginBadge summary={originBadge} onDismiss={() => setOriginBadge(null)} />
      ) : null}
    </AnimatePresence>
    {!turns.length && !busy && !browserAssistant.tasks.length ? <div className="buddy-home">{buddies.active?<><BuddyAvatar buddy={buddies.active}/><h2>What are we figuring out today?</h2><p>{buddies.active.name} · Your study partner{courseName?` for ${courseName}`:''}</p></>:<RotatingGreeting/>}</div> : null}
    {chatMode !== 'quiz' ? <ExecutionPanel sessionId={sessionId} courseId={courseId} onSession={id => { setSessionId(id); rememberSessionHint(id); navigateToSession(id, !sessionId); }} /> : null}
    {browserAssistant.tasks.map(task=><BrowserTaskCard key={task.id} task={task} onCommand={browserAssistant.command}/>)}
    {browserAssistant.notice?<p className={styles.turnStatus} role="status">{browserAssistant.notice}</p>:null}
    {browserAssistant.error?<p className={styles.error} role="alert">{browserAssistant.error}</p>:null}
    {classActionReply ? <div className="buddy-preview" role="status"><p>{classActionReply}</p></div> : null}
    {scheduledMessages.map(message=><article key={message.id} className="buddy-preview"><strong>{message.title}</strong><p>{message.body}</p><a href={message.url}>Open activity</a></article>)}
    {noteDrafts.filter(draft => !turns.some(turn => turn.sessionId === draft.sessionId)).map(draft => <NoteDraftCard key={draft.id} draft={draft} onHandled={updated => setNoteDrafts(current => current.map(item => item.id === updated.id ? updated : item))}/>)}
    {quizClarification ? <div className={styles.turnStatus} role="status"><strong>What topic should I quiz you on?</strong><p>Reply in Ask chat with the topic, then I’ll start your quiz.</p><Button type="button" variant="ghost" size="sm" onClick={() => { if (quizClarification.sourceTransitionId && quizClarification.sessionId) void learningApi.recordTransitionInteraction(quizClarification.sourceTransitionId, 'failed', 'quiz', quizClarification.sessionId).catch(() => undefined); setQuizClarification(null); }}>Cancel</Button></div> : null}
    {!turns.length && busy && !streaming && !activity ? <div className={styles.loading} role="status"><LoaderCircle className={styles.spinner} size={22} /><h2>{progress}</h2><p>{prompt}</p><span>A thoughtful answer takes a little time.</span></div> : null}
    {!turns.length && activity ? <AnimatePresence mode="wait">{activity && <WebResearchActivity activity={activity} />}</AnimatePresence> : null}
    {turns.map((turn, turnIndex) => {
      const filed = turn.lesson?.id ? filedRef.current[turn.lesson.id] : undefined;
      return <motion.div key={turn.generationId || turn.lesson?.id || turn.stream?.id || `material-${turnIndex}`} className={styles.turn} initial={reduceMotion ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: 'easeOut' }}>
      {!SYNTHETIC_QUESTIONS.has(turn.question) ? <div className={styles.userPrompt}><span>You</span><div><p>{turn.question}</p>{turn.files?.map(name => <div className={styles.sentFile} key={name}><FileText size={15} />{name}</div>)}</div></div> : null}
      <article id={`message-${turn.generationId || turn.lesson?.id || turn.stream?.id || `material-${turnIndex}`}`} aria-label="Assistant response" className={styles.lessonArticle}>
        {!turn.lesson && !turn.stream && !turn.answer && turn.status ? <p className={styles.turnStatus} role="status">{turn.status === 'pending' ? 'Preparing a response…' : turn.status === 'cancelled' ? 'Response stopped.' : turn.status === 'interrupted' ? 'Response interrupted. You can ask again.' : 'Response failed. You can ask again.'}</p> : null}
        {filed?.noteId ? <div className={styles.lessonReceipt}><span>Lesson saved in your study workspace</span><strong>{filed.heading}</strong><Button type="button" variant="outline" size="sm" onClick={() => openWorkspaceNote(filed.noteId)}><GraduationCap size={15}/>Open lesson</Button></div> : null}
        {filed?.noteId ? <details className={styles.originalResponse}><summary>Read original response here</summary><LessonReader id={turn.lesson!.id} lessonId={turn.lesson!.id} blocks={turn.lesson!.blocks.filter(block=>block.kind!=='source_note')} onSelect={(block, raw)=>setSelection({blockId:block.id,selectedText:raw.slice(0,1200),lessonId:turn.lesson?.id,sessionId:turn.sessionId})} onConceptSelect={term=>setSelectedConcept({id:term,title:term})}/></details> : (turn.lesson || turn.stream || turn.answer) ? <LessonReader id={turn.lesson?.id || turn.stream?.id || `material-${turnIndex}`}
          lessonId={turn.lesson?.id}
          redundantHeading={turn.question}
          blocks={turn.lesson ? turn.lesson.blocks.filter(block => block.kind !== 'source_note') : turn.stream ? turn.stream.blocks.map((block, index) => ({
            id: block.id, heading: block.heading, body: block.body || '…',
            visualizations: (turn.stream?.visualizations || []).filter(value => parseVisualization(value)?.blockIndex === index),
          })) : (turn.answer?.blocks || []).map((block, index) => ({ ...block, id: `block-${index}` }))}
          visualPending={Boolean(turn.stream?.visualPending)}
          onSelect={(block, raw) => setSelection({ blockId: block.id, selectedText: raw.slice(0, 1200), lessonId: turn.lesson?.id, sessionId: turn.sessionId })} onConceptSelect={term => setSelectedConcept({ id: term, title: term })} onExerciseResolved={exerciseId => { const key = turn.generationId || turn.lesson?.id || turn.stream?.id || ''; setResolvedExercises(current => new Set(current).add(`${key}:${exerciseId}`)); }} /> : null}
        {turn.answer && <><p className={styles.hint}>{turn.answer.message}</p>{turn.answer.sources.length > 0 && <details className={styles.sources}><summary>{turn.answer.sources.length} passages from your materials</summary><p className={styles.hint}>Coverage is limited to these selected passages.</p>{turn.answer.sources.map(source => <button type="button" className={styles.sourceChip} key={source.spanId} onClick={() => openWorkspaceSource(source)}>{source.title} · Page {source.pageIndex + 1}</button>)}</details>}</>}
        {turn.noteContext?.notes.length ? <div className={styles.noteContextReceipt}><span>Learner note context · {turn.noteContext.totalCharacters} characters</span>{turn.noteContext.notes.map(note => <button type="button" key={note.noteId} onClick={() => openWorkspaceNote(note.noteId)}>@{note.title}</button>)}</div> : null}
        {(turn.lesson || turn.answer || turn.stream) && turn.status !== 'pending' && !busy ? <SaveToNote title={turn.question.slice(0, 100)} body={captureReadingBlocks(turn.lesson?.blocks || turn.stream?.blocks || turn.answer?.blocks || [], turn.lesson?.id)} sessionId={turn.sessionId || sessionId} messageId={`message-${turn.generationId || turn.lesson?.id || turn.stream?.id || `material-${turnIndex}`}`}/> : null}
        <VerificationBadge verification={turn.verification}/>
        {noteDrafts.filter(draft => draft.sessionId === turn.sessionId && !turns.slice(turnIndex + 1).some(item => item.sessionId === turn.sessionId)).map(draft => <NoteDraftCard key={draft.id} draft={draft} onHandled={updated => setNoteDrafts(current => current.map(item => item.id === updated.id ? updated : item))} />)}
        {turn.generationId && turn.status !== 'pending' ? <DevContextInspector generationId={turn.generationId} /> : null}
      </article>
    </motion.div>;
    })}
    {turns.length > 0 && busy && !streaming && !activity ? <div className={styles.loading} role="status"><LoaderCircle className={styles.spinner} size={22} /><h2>{progress}</h2><p>{prompt}</p><span>A thoughtful answer takes a little time.</span></div> : null}
    {turns.length > 0 && activity ? <AnimatePresence mode="wait">{activity && <WebResearchActivity activity={activity} />}</AnimatePresence> : null}
    {appliedNote ? <div className={panelStyles.updated} role="status"><Check size={14} /><span>Lesson updated in Notes · {appliedNote.applyKind === 'refined' ? 'Expanded' : 'Added'} “{appliedNote.heading}”</span><button type="button" onClick={() => openWorkspaceNote(appliedNote.noteId)}>Open lesson</button><button type="button" aria-label="Dismiss" onClick={() => setAppliedNote(null)}><X size={14} /></button></div> : null}
    {checking && sessionId && <QuizWorkspace key={`${sessionId}:${journey?.position || 0}`} inline sessionId={sessionId} conceptId={journey?.steps[journey.position]?.conceptId || lesson?.conceptId} onReturn={() => setChecking(false)} onReviewInLearn={suggestion => void handleAcceptTransition(suggestion)} onCreateRepairNote={attemptId => void createQuizFeedbackDraft(attemptId)} />}
    {sessionId && turns.length > 0 && chatMode === 'learn' ? <NextActionCards sessionId={sessionId} enabled={!busy} refreshKey={`${journey?.revision || 0}:${checking ? 'checking' : 'ready'}`}
      onLearn={item => journeyAction(item?.context.journeyAction || 'next')}
      onAsk={item => setPrompt(`Help me understand ${item.conceptTitle || 'this concept'}.`)}
      onQuiz={item => void requestQuiz(sessionId, item?.conceptId || journey?.steps[journey.position]?.conceptId || lesson?.conceptId)}
      onReview={item => onReview?.(sessionId, item?.conceptId || journey?.steps[journey.position]?.conceptId || lesson?.conceptId)}
      onCheck={() => setChecking(true)} /> : null}
    {sessionId && turns.length > 0 && chatMode === 'learn' ? <ConceptProgressWhy conceptId={journey?.steps[journey.position]?.conceptId || lesson?.conceptId} enabled={!busy} /> : null}
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {selection ? <div className={styles.selection}><Button onClick={() => void explainSelection(selection)}>Explain selection</Button><Button variant="outline" onClick={() => { openWorkspaceNoteDraft({ title: 'Lesson note', body: `> ${selection.selectedText.replace(/\n/g, '\n> ')}\n\n`, frontmatter: { lesson_id: selection.lessonId || null, block_id: selection.blockId, session_id: selection.sessionId || null, source: 'lesson_selection' } }); setSelection(null); }}>Save to notes</Button>{(selection.sessionId || sessionId) ? <Button variant="outline" onClick={() => void saveSelectionInsight()}>Save to study note</Button> : null}<Button variant="ghost" onClick={() => setSelection(null)}>Dismiss</Button></div> : null}
    {selectionPanel ? <aside className={styles.studyPanel} aria-label="Selected passage explanation"><div className={styles.panelHeader}><div><span>Selected passage</span><strong>A closer look</strong></div><Button variant="ghost" size="sm" onClick={() => setSelectionPanel(null)}>Close</Button></div><blockquote>{selectionPanel.selection.selectedText}</blockquote>{selectionPanel.blocks.map(block => <section key={block.id}><h3>{block.heading}</h3><RichContent body={block.body || '…'} /></section>)}{selectionPanel.status === 'preparing' ? <p className={styles.hint}>Preparing the explanation…</p> : null}{selectionPanel.error ? <p className={styles.error}>{selectionPanel.error}</p> : null}<form onSubmit={event => { event.preventDefault(); const text = selectionFollowup.trim(); if (text) { setSelectionFollowup(''); void explainSelection(selectionPanel.selection, text); } }}><label htmlFor="selection-followup" className="sr-only">Ask a follow-up about this passage</label><textarea id="selection-followup" rows={3} value={selectionFollowup} disabled={busy} placeholder="Ask a follow-up about this passage…" onChange={event => setSelectionFollowup(event.target.value)} /><div className={styles.lessonActions}>{selectionPanel.status === 'streaming' || selectionPanel.status === 'preparing' ? <Button type="button" variant="outline" onClick={() => void activeGeneration.current?.stop()}>Stop</Button> : <span /> }{selectionPanel.blocks.length > 0 ? <Button type="button" variant="outline" disabled={busy} onClick={() => void proposeInsight(selectionPanel.blocks.map(block => `${block.heading}\n${block.body}`).join('\n\n'), selectionPanel.selection.selectedText.slice(0, 120), selectionPanel.selection.sessionId || sessionId)}>Save insight</Button> : null}<Button type="submit" disabled={busy || !selectionFollowup.trim()}>Ask</Button></div></form></aside> : null}
    </div>
    </div>
    <AnimatePresence>
      {hasNewContentBelow && streaming && (
        <motion.button
          type="button"
          className={styles.newContentIndicator}
          onClick={() => scrollToBottom(true)}
          initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.95 }}
          animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
          exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.95 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          aria-label="Scroll to newest content"
        >
          <ArrowDown size={14} aria-hidden="true" />
          <span>New content</span>
        </motion.button>
      )}
    </AnimatePresence>
    <div className={styles.composerDock}><div className={styles.composerInner}>
      {courseName ? <button type="button" className={styles.composerCourse} onClick={()=>courseId&&onCourseClick?.(courseId)}><GraduationCap size={13}/>{courseName}</button> : null}
      {turns.length > 0 && !busy && !prompt.trim() && (latestTurn?.lesson || latestTurn?.answer || latestTurn?.stream?.status === 'completed') ? <div className={styles.quickActions}><button type="button" onClick={() => void submit('Explain that again a different way, with a different analogy or example.')}>Explain differently</button><button type="button" onClick={() => void submit('Quiz me on what we just covered.')}>Quiz me</button>{unresolvedExercise?<button type="button" onClick={() => void submit('Give me a hint without giving away the answer.')}>Hint</button>:null}</div> : null}
      {activeModeSuggestion && !dismissedSuggestions.has(activeModeSuggestion.id) ? <ModeTransitionCard
        suggestion={activeModeSuggestion}
        disabled={false}
        onAccept={handleAcceptTransition}
        onDismiss={handleDismissTransition}
      /> : null}
      {buddies.active?.archived&&!sessionId?<p role="status">This Buddy is archived. Choose an active Buddy to start a new conversation.</p>:null}
      <ChatComposer onVoice={() => void startVoice()} onInClass={onInClass} conversation={conversation} onConversation={()=>chooseMode('ask',true)} variant="main" contextConcept={contextConcept} onRemoveContext={() => { if (selectedConcept) setSelectedConcept(null); else setDismissedConceptId(activeConcept?.conceptId || null); }} value={prompt} onChange={setPrompt} attachments={attachments} onAttachmentsChange={setAttachments} onSubmit={() => void submit()} onCancel={streaming ? () => void activeGeneration.current?.stop() : undefined} busy={busy} unavailable={!buddies.active?(buddies.error?'Open Learn could not connect. You can keep writing your draft.':'Connecting to your study partner. You can write while we connect.'):buddies.active.archived&&!sessionId?'Choose an active Buddy to send a new message.':undefined} onRetry={()=>void buddies.refresh()} followup={turns.length > 0} gear={gear} onGearChange={setGear} mode={chatMode} onModeChange={mode=>chooseMode(mode)} noteMentions={noteMentions} onAddNoteMention={note => void addNoteMention(note)} onRemoveNoteMention={noteId => setNoteMentions(current => current.filter(note => note.noteId !== noteId))} onOpenNoteMention={openWorkspaceNote} /></div></div>
  </div>;
}
