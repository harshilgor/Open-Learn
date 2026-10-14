"use client";
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Bookmark, ChevronRight, CircleHelp, FileText, Layers, Lightbulb, ListChecks, MessageCircleQuestion, Pause, Play, Square } from 'lucide-react';
import { Button } from './ui/button';
import { MakeFlashcards } from './flashcard-create';
import { lectureCapture, LECTURE_CAPTURE_EVENT, type CapturePhase } from '@/lib/lecture-capture';
import { addClassMarker, formatClassTime, readClassMarkers, serverClassMarkers, subscribeClassMarkers, type ClassMarker, type ClassMarkerKind } from '@/lib/class-markers';
import { learningApi } from '@/lib/api';
import type { FlashcardSourceRef } from '@/lib/flashcards-client';
import type { ClassAction, ClassSnapshot } from '@/lib/in-class';
import { requestWorkspaceQuiz, WORKSPACE_PASSAGE_MENTION_EVENT, type WorkspacePassageMention } from '@/lib/workspace-events';
import styles from './class-session-tools.module.css';

const SERVER_MARKER_TOLERANCE_MS = 1500;
const MARKER_LABEL: Record<ClassMarkerKind, string> = { moment: 'Marked moment', confused: 'Confusing moment', key_point: 'Key point' };
const MARKER_ICON: Record<ClassMarkerKind, typeof Bookmark> = { moment: Bookmark, confused: CircleHelp, key_point: Lightbulb };

const subscribeCapture = (onChange: () => void) => {
  window.addEventListener(LECTURE_CAPTURE_EVENT, onChange);
  return () => window.removeEventListener(LECTURE_CAPTURE_EVENT, onChange);
};
const subscribeTick = (onChange: () => void) => {
  const timer = window.setInterval(onChange, 500);
  window.addEventListener(LECTURE_CAPTURE_EVENT, onChange);
  return () => { window.clearInterval(timer); window.removeEventListener(LECTURE_CAPTURE_EVENT, onChange); };
};
const subscribeNothing = () => () => undefined;
const capturePhase = () => lectureCapture.phase;
const captureRecordingId = () => lectureCapture.recordingId;
const idlePhase = (): CapturePhase => 'idle';
const noRecording = () => null;
const zero = () => 0;
const elapsedSeconds = () => Math.floor(lectureCapture.elapsedMs / 1000);

/** Capture state for this class when this device is the one recording it. */
function useClassCapture(recordingId: string) {
  const phase = useSyncExternalStore(subscribeCapture, capturePhase, idlePhase);
  const capturingId = useSyncExternalStore(subscribeCapture, captureRecordingId, noRecording);
  const owned = Boolean(recordingId) && capturingId === recordingId;
  const seconds = useSyncExternalStore(!owned ? subscribeNothing : phase === 'recording' ? subscribeTick : subscribeCapture, owned ? elapsedSeconds : zero, zero);
  return { owned, phase: owned ? phase : 'idle' as CapturePhase, elapsedMs: seconds * 1000 };
}

function useClassMarkers(recordingId: string) {
  return useSyncExternalStore(subscribeClassMarkers, () => readClassMarkers(recordingId), serverClassMarkers);
}

/** Typed markers plus any saved recording markers this device has no kind for. */
export function mergeClassMarkers(typed: ClassMarker[], serverMs: number[]): ClassMarker[] {
  const extra = serverMs
    .filter(ms => Number.isFinite(ms) && ms >= 0 && !typed.some(marker => Math.abs(marker.atMs - ms) <= SERVER_MARKER_TOLERANCE_MS))
    .map((ms, index): ClassMarker => ({ id: `recording-marker-${index}-${ms}`, kind: 'moment', atMs: ms, createdAt: 0 }));
  return [...typed, ...extra].sort((a, b) => a.atMs - b.atMs);
}

function latestTranscriptMs(snapshot: ClassSnapshot) {
  const archived = snapshot.transcript[snapshot.transcript.length - 1]?.endMs ?? 0;
  const live = (snapshot.liveTranscript ?? []).reduce((latest, segment) => Math.max(latest, segment.endMs ?? 0), 0);
  return Math.max(archived, live);
}

function confusingExcerpt(title: string, markers: ClassMarker[], transcript: ClassSnapshot['transcript']) {
  const parts = markers.map(marker => {
    const nearby = transcript.filter(segment => segment.endMs >= marker.atMs - 20_000 && segment.startMs <= marker.atMs + 10_000);
    const text = nearby.map(segment => (segment.normalizedText || segment.rawText).replace(/\s+/g, ' ').trim()).filter(Boolean).join(' ');
    return `At ${formatClassTime(marker.atMs)}${text ? `: "${text.slice(0, 1200)}"` : ' (no transcript loaded for this moment yet)'}`;
  });
  return `I marked these moments in "${title}" as confusing. Please explain each one simply.\n\n${parts.join('\n\n')}`.slice(0, 6000);
}

type Lines = { id: string; text: string; atMs?: number | null; provisional?: boolean }[];

export function ClassSessionTools({ snapshot, courseName, interim, onJump, onShowTranscript, dispatch }: {
  snapshot: ClassSnapshot;
  courseName: string;
  interim?: string;
  onJump: (ms: number, label: string) => void;
  onShowTranscript: () => void;
  dispatch: (action: ClassAction) => boolean;
}) {
  const recordingId = snapshot.session.recordingId;
  const capture = useClassCapture(recordingId);
  const typed = useClassMarkers(recordingId);
  const ended = snapshot.recording.captureComplete || (capture.owned && capture.phase === 'saved');
  if (ended) return <ClassSessionSummary snapshot={snapshot} courseName={courseName} typed={typed} fallbackDurationMs={capture.owned ? capture.elapsedMs : latestTranscriptMs(snapshot)} onJump={onJump} dispatch={dispatch} />;
  return <ClassLiveSession snapshot={snapshot} courseName={courseName} interim={interim} capture={capture} typedCount={typed.length} onShowTranscript={onShowTranscript} />;
}

function ClassLiveSession({ snapshot, courseName, interim, capture, typedCount, onShowTranscript }: {
  snapshot: ClassSnapshot; courseName: string; interim?: string; capture: ReturnType<typeof useClassCapture>; typedCount: number; onShowTranscript: () => void;
}) {
  const [status, setStatus] = useState('');
  const { owned, phase, elapsedMs } = capture;
  const recording = owned && phase === 'recording';
  const paused = owned && phase === 'paused';
  const finalizing = owned && phase === 'finalizing';
  const lines: Lines = useMemo(() => {
    const live = (snapshot.liveTranscript ?? []).slice(-3).map(segment => ({ id: segment.id, text: segment.text, atMs: segment.startMs ?? null, provisional: true }));
    if (live.length) return live;
    return snapshot.transcript.slice(-3).map(segment => ({ id: segment.id, text: segment.normalizedText || segment.rawText, atMs: segment.startMs }));
  }, [snapshot.liveTranscript, snapshot.transcript]);
  const stateLabel = finalizing ? 'Saving audio…' : paused ? 'Paused' : recording ? 'Recording' : 'Live class';
  function mark(kind: ClassMarkerKind) {
    const atMs = owned ? lectureCapture.elapsedMs : latestTranscriptMs(snapshot);
    if (owned) lectureCapture.mark();
    addClassMarker(snapshot.session.recordingId, kind, atMs, !owned);
    const time = `${owned ? '' : '≈'}${formatClassTime(atMs)}`;
    setStatus(kind === 'confused' ? `Confusing moment at ${time} saved. Review it after class.` : kind === 'key_point' ? `Key point marked at ${time}.` : `Moment marked at ${time}.`);
  }
  return <section className={styles.live} aria-label="Live class session">
    <div className={styles.bar}>
      <div className={styles.barStatus}>
        <span className={styles.dot} data-state={recording ? 'recording' : paused || finalizing ? 'paused' : 'remote'} aria-hidden="true" />
        <div className={styles.barCopy}>
          <strong>{stateLabel}{owned ? <> · <time className={styles.timer} aria-label={`Elapsed ${formatClassTime(elapsedMs)}`}>{formatClassTime(elapsedMs)}</time></> : null}</strong>
          <span>{courseName}{owned ? '' : ' · Capture runs on its recording device'}</span>
        </div>
        {owned ? <div className={styles.barControls}>
          <Button type="button" size="icon-sm" variant="ghost" disabled={finalizing} aria-label={paused ? 'Resume recording' : 'Pause recording'} title={paused ? 'Resume' : 'Pause'} onClick={() => void (paused ? lectureCapture.resume() : lectureCapture.pause())}>{paused ? <Play /> : <Pause />}</Button>
          <Button type="button" size="icon-sm" variant="ghost" disabled={finalizing} aria-label="Stop and save recording" title="Stop and save" onClick={() => void lectureCapture.stop()}><Square fill="currentColor" /></Button>
        </div> : null}
      </div>
      <div className={styles.actions} role="group" aria-label="Mark this moment">
        <button type="button" onClick={() => mark('moment')} disabled={finalizing}><Bookmark aria-hidden="true" /><span>Mark moment</span></button>
        <button type="button" data-kind="confused" onClick={() => mark('confused')} disabled={finalizing}><CircleHelp aria-hidden="true" /><span>I’m confused</span></button>
        <button type="button" data-kind="key" onClick={() => mark('key_point')} disabled={finalizing}><Lightbulb aria-hidden="true" /><span>Key point</span></button>
      </div>
      <p className={styles.status} role="status" aria-live="polite">{status || (typedCount ? `${typedCount} ${typedCount === 1 ? 'moment' : 'moments'} marked this class.` : '')}</p>
    </div>
    {lines.length || interim ? <div className={styles.transcript} aria-label="Latest transcript">
      <div className={styles.transcriptHead}><span className="ol-eyebrow">Live transcript{lines.some(line => line.provisional) ? ' · provisional' : ''}</span><button type="button" onClick={onShowTranscript}>Full transcript <ChevronRight aria-hidden="true" /></button></div>
      {lines.map(line => <p key={line.id}>{typeof line.atMs === 'number' ? <time>{formatClassTime(line.atMs)}</time> : null}{line.text}</p>)}
      {interim ? <p className={styles.interim} aria-live="off">{interim}</p> : null}
    </div> : null}
  </section>;
}

function ClassSessionSummary({ snapshot, courseName, typed, fallbackDurationMs, onJump, dispatch }: {
  snapshot: ClassSnapshot; courseName: string; typed: ClassMarker[]; fallbackDurationMs: number; onJump: (ms: number, label: string) => void; dispatch: (action: ClassAction) => boolean;
}) {
  const { session, recording, outputs } = snapshot;
  const [status, setStatus] = useState('');
  const [noteRevision, setNoteRevision] = useState<{ noteId: string; revision: number } | null>(null);
  const markers = useMemo(() => mergeClassMarkers(typed, recording.markersMs ?? []), [typed, recording.markersMs]);
  const confused = markers.filter(marker => marker.kind === 'confused');
  const keyPoints = markers.filter(marker => marker.kind === 'key_point');
  const moments = markers.filter(marker => marker.kind === 'moment');
  const durationMs = recording.durationMs || fallbackDurationMs;
  const quizId = (outputs.find(output => output.kind === 'revision_quiz' && output.status === 'ready' && output.result?.quizId) ?? outputs.find(output => output.kind === 'practice' && output.status === 'ready' && output.result?.quizId))?.result?.quizId;
  const deckId = outputs.find(output => output.kind === 'flashcards' && output.status === 'ready' && output.result?.deckId)?.result?.deckId;
  const noteId = session.noteId || recording.noteId || '';
  const processing = !recording.captureComplete || ['processing', 'queued'].includes(recording.recordingStatus);
  useEffect(() => {
    if (!noteId || deckId || !recording.captureComplete) return;
    let live = true;
    void learningApi.getWorkspaceNote(noteId).then(note => { if (live && typeof note.revision === 'number') setNoteRevision({ noteId, revision: note.revision }); }).catch(() => undefined);
    return () => { live = false; };
  }, [noteId, deckId, recording.captureComplete]);
  const flashcardRefs = useMemo<FlashcardSourceRef[] | undefined>(() => noteRevision && noteRevision.noteId === noteId ? [{ kind: 'note', id: noteId, revision: noteRevision.revision }] : undefined, [noteRevision, noteId]);
  function quiz() {
    if (quizId && dispatch({ type: 'open-quiz', sessionId: session.sessionId, quizId })) return;
    requestWorkspaceQuiz({ requestedTopic: session.title, sessionId: session.sessionId, origin: 'ask' });
    setStatus('Quiz requested in chat.');
  }
  function reviewConfusing() {
    const detail: WorkspacePassageMention = { title: `${session.title} · confusing moments`, excerpt: confusingExcerpt(session.title, confused, snapshot.transcript), submit: true };
    window.dispatchEvent(new CustomEvent<WorkspacePassageMention>(WORKSPACE_PASSAGE_MENTION_EVENT, { detail }));
    setStatus(`Sent ${confused.length} confusing ${confused.length === 1 ? 'moment' : 'moments'} to chat for an explanation.`);
  }
  const stats: [string, number, ClassMarkerKind][] = [['Moments', moments.length, 'moment'], ['Confusing', confused.length, 'confused'], ['Key points', keyPoints.length, 'key_point']];
  return <section className={`ol-card ${styles.summary}`} aria-labelledby="class-summary-title">
    <div className={styles.summaryHead}>
      <span className="ol-eyebrow">Class summary</span>
      <h2 id="class-summary-title">{session.title}</h2>
      <p>{courseName} · <span aria-label={`Duration ${formatClassTime(durationMs)}`}>{durationMs ? formatClassTime(durationMs) : '—'}</span>{processing ? ' · Notes are being prepared' : ''}</p>
    </div>
    <dl className={styles.stats}>
      {stats.map(([label, count, kind]) => {const Icon = MARKER_ICON[kind]; return <div key={kind} data-kind={kind}><dt><Icon aria-hidden="true" />{label}</dt><dd>{count}</dd></div>;})}
    </dl>
    {markers.length ? <ol className={`ol-list ${styles.timeline}`} aria-label="Marked moments">
      {markers.map(marker => {const Icon = MARKER_ICON[marker.kind]; const time = `${marker.approximate ? '≈' : ''}${formatClassTime(marker.atMs)}`; return <li key={marker.id} className="ol-row">
        <button type="button" data-kind={marker.kind} onClick={() => onJump(marker.atMs, `${MARKER_LABEL[marker.kind]} at ${time}.`)} aria-label={`${MARKER_LABEL[marker.kind]} at ${time}; show nearest transcript passage`}>
          <Icon aria-hidden="true" /><span>{MARKER_LABEL[marker.kind]}</span><time>{time}</time>
        </button>
      </li>;})}
    </ol> : <p className={styles.muted}>No moments were marked during this class.</p>}
    <div className={styles.summaryActions}>
      {noteId ? <Button type="button" variant="outline" size="sm" onClick={() => dispatch({ type: 'open-note', noteId })}><FileText />Open class note</Button> : null}
      <Button type="button" size="sm" onClick={quiz}><ListChecks />Quiz me on this class</Button>
      {deckId ? <Button type="button" variant="outline" size="sm" onClick={() => dispatch({ type: 'open-flashcards', deckId })}><Layers />Open class flashcards</Button> : <div className={styles.flashcards}><MakeFlashcards sessionId={session.sessionId} courseId={session.courseId} origin="in_class" sourceRefs={flashcardRefs} label="Make flashcards" /></div>}
      {confused.length ? <Button type="button" variant="outline" size="sm" onClick={reviewConfusing}><MessageCircleQuestion />Review confusing moments</Button> : null}
    </div>
    <p className={styles.status} role="status" aria-live="polite">{status}</p>
  </section>;
}
