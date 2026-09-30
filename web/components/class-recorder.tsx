"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Pause, Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { lectureCapture, LECTURE_CAPTURE_EVENT, type CapturePhase } from '@/lib/lecture-capture';
import { defaultLecturePreferences, discardEmptyLocalLecture, listLocalChunks, listLocalLectures, updateLocalLecture, type LocalLecture, type LecturePreferences } from '@/lib/lecture-local-store';
import { LECTURE_SYNC_EVENT, recoverLocalLectures, startLectureRecovery, syncLecture } from '@/lib/lecture-upload-queue';
import { learningApi, type LectureStatus, type LectureTranscriptSegment } from '@/lib/api';
import styles from './class-recorder.module.css';
import { readSettingsPreferences, SETTINGS_CHANGED_EVENT } from '@/lib/settings-preferences';
import { needsFloatingRecovery, processingStarted } from '@/lib/recording-ui';

function clock(ms: number) { return `${Math.floor(ms / 60000).toString().padStart(2, '0')}:${Math.floor(ms % 60000 / 1000).toString().padStart(2, '0')}`; }

export function ClassRecorder({ setupOpen, onSetupOpenChange, folder, courseId, onNoteCreated }: {
  setupOpen: boolean; onSetupOpenChange: (open: boolean) => void; folder: string | null;
  courseId?: string | null; onNoteCreated: (noteId: string) => void;
}) {
  const [title, setTitle] = useState('');
  const [preferences, setPreferences] = useState<LecturePreferences>(() => {
    const defaults = readSettingsPreferences();
    return { ...defaultLecturePreferences, depth: defaults.lectureDepth, keepAudio: defaults.keepLectureAudio };
  });
  const [phase, setPhase] = useState<CapturePhase>(() => lectureCapture.phase);
  const [elapsed, setElapsed] = useState(0);
  const [sessions, setSessions] = useState<LocalLecture[]>([]);
  const [saved, setSaved] = useState<Record<string, { total: number; uploaded: number }>>({});
  const [serverStatus, setServerStatus] = useState<Record<string, LectureStatus>>({});
  const [error, setError] = useState('');
  const [liveTranscript, setLiveTranscript] = useState<LectureTranscriptSegment[]>([]);
  const [notice, setNotice] = useState('');
  const noticedRecordings = useRef(new Set<string>());
  const noteCreated = useRef(onNoteCreated);
  const openedNotes = useRef(new Set<string>());
  useEffect(() => { noteCreated.current = onNoteCreated; }, [onNoteCreated]);
  useEffect(() => {
    const refreshPreferences = () => {
    const defaults = readSettingsPreferences();
    setPreferences(current => ({ ...current, depth: defaults.lectureDepth, keepAudio: defaults.keepLectureAudio }));
    };
    window.addEventListener(SETTINGS_CHANGED_EVENT, refreshPreferences);
    window.addEventListener('storage', refreshPreferences);
    return () => { window.removeEventListener(SETTINGS_CHANGED_EVENT, refreshPreferences); window.removeEventListener('storage', refreshPreferences); };
  }, []);

  const refresh = useCallback(async () => {
    const all = await listLocalLectures();
    setSessions(all.filter(item => item.phase !== 'completed').sort((a, b) => b.startedAtMs - a.startedAtMs));
    const counts = await Promise.all(all.map(async item => {
      const chunks = await listLocalChunks(item.id);
      return [item.id, { total: chunks.length, uploaded: chunks.filter(chunk => chunk.state === 'server_confirmed').length }] as const;
    }));
    setSaved(Object.fromEntries(counts));
  }, []);

  useEffect(() => {
    const stopRecovery = startLectureRecovery();
    void recoverLocalLectures(lectureCapture.recordingId).then(refresh).catch(cause => setError(cause instanceof Error ? cause.message : 'Saved recordings could not be read.'));
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; phase?: CapturePhase; error?: string; status?: LectureStatus }>).detail;
      if (detail.phase) setPhase(detail.phase);
      if (detail.error) setError(detail.error);
      if (detail.id && detail.status) setServerStatus(current => ({ ...current, [detail.id!]: detail.status! }));
      if (detail.id && detail.status && processingStarted(detail.status) && !noticedRecordings.current.has(detail.id)) {
        noticedRecordings.current.add(detail.id); setNotice('Audio uploaded. Your class notes are being prepared.');
      }
      if (detail.status?.noteId && !openedNotes.current.has(detail.status.noteId)) { openedNotes.current.add(detail.status.noteId); noteCreated.current(detail.status.noteId); }
      void refresh();
    };
    window.addEventListener(LECTURE_CAPTURE_EVENT, changed);
    window.addEventListener(LECTURE_SYNC_EVENT, changed);
    const timer = window.setInterval(() => setElapsed(lectureCapture.elapsedMs), 250);
    return () => { stopRecovery(); window.removeEventListener(LECTURE_CAPTURE_EVENT, changed); window.removeEventListener(LECTURE_SYNC_EVENT, changed); window.clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(''), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (phase !== 'recording' && phase !== 'paused' && phase !== 'finalizing') return;
    const recordingId = lectureCapture.recordingId;
    if (!recordingId) return;
    let live = true;
    const update = () => {
      void learningApi.getLectureTranscript(recordingId).then(result => {
        if (live) setLiveTranscript(result.segments);
      }).catch(() => undefined);
    };
    update();
    const timer = window.setInterval(update, 4000);
    return () => { live = false; window.clearInterval(timer); };
  }, [phase]);

  async function start() {
    setError('');
    setLiveTranscript([]);
    try {
      await lectureCapture.start({ title: title.trim() || `Class recording · ${new Date().toLocaleDateString()}`, courseId, noteFolder: folder, preferences });
      onSetupOpenChange(false);
      void refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Microphone recording could not start.'); }
  }

  async function finishInterrupted(session: LocalLecture) {
    const chunks = await listLocalChunks(session.id);
    if (!chunks.length) { setError('No audio slices were saved for this recording.'); return; }
    await updateLocalLecture(session.id, { phase: 'stop_requested', expectedChunkCount: chunks.length, durationMs: chunks[chunks.length - 1].endMs, captureInterrupted: true });
    void syncLecture(session.id);
    void refresh();
  }

  const recoverySessions = sessions.filter(session => needsFloatingRecovery(session, serverStatus[session.id]));

  return <>
    <Dialog open={setupOpen} onOpenChange={onSetupOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Record a class</DialogTitle><DialogDescription>Audio is saved in short slices on this device and uploaded as your class continues. The selected provider transcribes it after upload, and provider charges may apply. Make sure recording is permitted.</DialogDescription></DialogHeader>
        <label className={styles.titleLabel}>Class title<input autoFocus value={title} onChange={event => setTitle(event.target.value)} placeholder="e.g. Biology · Lecture 4" /></label>
        <label className={styles.titleLabel}>Note detail<select value={preferences.depth} onChange={event => setPreferences(current => ({ ...current, depth: event.target.value as LecturePreferences['depth'] }))}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
        <label className={styles.optionLabel}><input type="checkbox" checked={preferences.keepAudio} onChange={event => setPreferences(current => ({ ...current, keepAudio: event.target.checked }))} /> Keep class audio for playback</label>
        <div className={styles.dialogActions}><Button variant="outline" onClick={() => onSetupOpenChange(false)}>Cancel</Button><Button onClick={() => void start()}><Mic size={16} />Start recording</Button></div>
        {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      </DialogContent>
    </Dialog>
    {phase === 'recording' || phase === 'paused' || phase === 'finalizing' ? <div className={styles.bubble} role="status" aria-label={`Class recording ${phase}, ${clock(elapsed)}`}>
      <span className={`${styles.liveDot} ${phase === 'paused' ? styles.pausedDot : ''}`} />
      <div className={styles.bubbleText}><strong>{phase === 'finalizing' ? 'Saving audio…' : phase === 'paused' ? 'Recording paused' : 'Recording class'}</strong><small>{clock(elapsed)} · {saved[lectureCapture.recordingId || '']?.total || 0} slices saved</small></div>
      <button type="button" disabled={phase === 'finalizing'} title={phase === 'paused' ? 'Resume' : 'Pause'} aria-label={phase === 'paused' ? 'Resume recording' : 'Pause recording'} onClick={() => void (phase === 'paused' ? lectureCapture.resume() : lectureCapture.pause())}>{phase === 'paused' ? <Play size={16} /> : <Pause size={16} />}</button>
      <button type="button" disabled={phase !== 'recording'} title="Mark this moment" aria-label="Mark this moment" onClick={() => lectureCapture.mark()}><Mic size={15} /></button>
      <button type="button" disabled={phase === 'finalizing'} title="Stop and save" aria-label="Stop and save recording" onClick={() => void lectureCapture.stop()}><Square size={15} fill="currentColor" /></button>
      <details className={styles.liveTranscript}><summary>Transcript {liveTranscript.length ? `· ${liveTranscript.length} parts` : '· waiting for audio'}</summary><div>{liveTranscript.length ? liveTranscript.slice(-4).map(segment => <p key={segment.id}>{segment.normalizedText || segment.rawText}</p>) : <p>New words appear here after each audio slice is transcribed.</p>}</div></details>
    </div> : null}
    {recoverySessions.length ? <aside className={styles.recovery} aria-label="Saved class recordings">{recoverySessions.map(session => <div key={session.id}><strong>{session.title}</strong><small>{saved[session.id]?.uploaded || 0}/{saved[session.id]?.total || 0} slices uploaded</small>{session.lastError ? <small>{session.lastError}</small> : null}{session.phase === 'interrupted' && !saved[session.id]?.total ? <Button size="sm" variant="outline" onClick={() => void discardEmptyLocalLecture(session.id).then(refresh).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not discard the empty recording.'))}>Discard empty recording</Button> : session.phase === 'interrupted' ? <Button size="sm" onClick={() => void finishInterrupted(session)}>Finish saved audio</Button> : <Button size="sm" variant="outline" onClick={() => void syncLecture(session.id)}>Resume upload</Button>}</div>)}</aside> : null}
    {notice ? <p role="status" className={styles.notice}>{notice}</p> : null}
    {error && !setupOpen ? <p role="alert" className={styles.errorBubble}>{error}</p> : null}
  </>;
}
