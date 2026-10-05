"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { RichContent } from './rich-content';
import { learningApi, type LectureNoteBlock, type LectureSection, type LectureStatus, type LectureTranscriptSegment } from '@/lib/api';
import { getLocalLecture, listLocalChunks, updateLocalLecture, type LocalLecture } from '@/lib/lecture-local-store';
import { syncLecture } from '@/lib/lecture-upload-queue';
import { LectureTranscriptEditor } from '@/components/lecture-transcript-editor';

function timestamp(ms: number) { return `${Math.floor(ms / 60000).toString().padStart(2, '0')}:${Math.floor(ms % 60000 / 1000).toString().padStart(2, '0')}`; }
type AudioChunk = { sequenceNumber: number; startMs: number; endMs: number; mediaType: string };

export function LectureNotesView({ recordingId }: { recordingId: string }) {
  const [status, setStatus] = useState<LectureStatus | null>(null);
  const [blocks, setBlocks] = useState<LectureNoteBlock[]>([]);
  const [sections, setSections] = useState<LectureSection[]>([]);
  const [transcript, setTranscript] = useState<LectureTranscriptSegment[]>([]);
  const [chunks, setChunks] = useState<AudioChunk[]>([]);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [removingAudio, setRemovingAudio] = useState(false);
  const [local, setLocal] = useState<LocalLecture | null>(null);
  const player = useRef<HTMLAudioElement>(null);
  const currentUrl = useRef<string | null>(null);
  const currentSequence = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await learningApi.getLectureRecording(recordingId);
      setStatus(next);
      if (next.stages.audioRetention === 'pending' || next.stages.audioRetention === 'removed' || next.stages.audioRetention === 'failed') {
        player.current?.pause();
        if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
        currentUrl.current = null;
        currentSequence.current = null;
        setAudioUrl(null);
      }
      setLocal(await getLocalLecture(recordingId) || null);
      const [notes, sectionData, chunkData, transcriptData] = await Promise.all([
        learningApi.getLectureNotes(recordingId), learningApi.getLectureSections(recordingId),
        learningApi.getLectureChunks(recordingId), learningApi.getLectureTranscript(recordingId),
      ]);
      setBlocks(notes.blocks); setSections(sectionData.sections); setChunks(chunkData.chunks); setTranscript(transcriptData.segments);
      setError('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Lecture status is unavailable.'); }
  }, [recordingId]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(initial);
  }, [refresh]);
  useEffect(() => {
    if (status?.stages.audioRetention === 'failed' || (status?.recordingStatus === 'completed' && (status.preferences.keepAudio !== false || status.stages.audioRetention === 'removed'))) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh, status?.recordingStatus, status?.preferences.keepAudio, status?.stages.audioRetention]);
  useEffect(() => () => { if (currentUrl.current) URL.revokeObjectURL(currentUrl.current); }, []);

  async function seek(timeMs: number) {
    const chunk = chunks.find(item => item.startMs <= timeMs && item.endMs > timeMs);
    if (!chunk) { setError('Audio for this timestamp has not arrived yet.'); return; }
    try {
      const local = (await listLocalChunks(recordingId)).find(item => item.sequenceNumber === chunk.sequenceNumber);
      const blob = local?.blob || await learningApi.getLectureChunkAudio(recordingId, chunk.sequenceNumber);
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
      const objectUrl = URL.createObjectURL(blob);
      currentUrl.current = objectUrl;
      currentSequence.current = chunk.sequenceNumber;
      setAudioUrl(objectUrl);
      window.setTimeout(() => { if (player.current) { player.current.currentTime = Math.max(0, (timeMs - chunk.startMs) / 1000); void player.current.play().catch(() => undefined); } }, 0);
      setError('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Audio could not be played.'); }
  }

  async function retry() {
    try { await learningApi.retryLectureFailures(recordingId); void syncLecture(recordingId); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Retry could not start.'); }
  }

  async function finishSavedAudio() {
    try {
      const savedChunks = await listLocalChunks(recordingId);
      if (!savedChunks.length) throw new Error('There is no saved audio to finish.');
      await updateLocalLecture(recordingId, { phase: 'stop_requested', expectedChunkCount: savedChunks.length, durationMs: savedChunks[savedChunks.length - 1].endMs, captureInterrupted: true });
      await syncLecture(recordingId); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Saved audio could not be finished.'); }
  }

  async function changeDepth(depth: 'concise' | 'standard' | 'detailed') {
    if (!status) return;
    try { await learningApi.regenerateLectureNotes(recordingId, { ...status.preferences, depth }); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Notes could not be regenerated.'); }
  }

  async function removeSavedAudio() {
    const confirmation = status?.stages.audioRetention === 'failed'
      ? 'Retry deleting the saved audio for this class? Your notes and transcript will remain.'
      : 'Delete the saved audio for this class? Your notes and transcript will remain.';
    if (!window.confirm(confirmation)) return;
    setRemovingAudio(true);
    try {
      await learningApi.deleteLectureAudio(recordingId);
      player.current?.pause();
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
      currentUrl.current = null;
      currentSequence.current = null;
      setAudioUrl(null);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Saved audio could not be removed.'); }
    finally { setRemovingAudio(false); }
  }

  const bySection = new Map(sections.map(section => [section.id, section]));
  const audioRemovalPending = status?.preferences.keepAudio === false && (status.stages.audioRetention === 'pending' || (status.recordingStatus === 'completed' && status.stages.audioRetention !== 'removed' && status.stages.audioRetention !== 'failed'));
  const audioRemovalFailed = status?.preferences.keepAudio === false && status.recordingStatus === 'completed' && status.stages.audioRetention === 'failed';
  const audioRetained = status?.stages.audioRetention !== 'pending' && status?.stages.audioRetention !== 'removed' && status?.stages.audioRetention !== 'failed' && (status?.preferences.keepAudio !== false || status?.recordingStatus !== 'completed');
  const ordered = [...blocks].sort((a, b) => (bySection.get(a.sectionId)?.ordinal ?? 0) - (bySection.get(b.sectionId)?.ordinal ?? 0) || a.ordinal - b.ordinal);
  return <section className="rounded-xl border border-border p-4 space-y-3" aria-label="Lecture notes">
    <div className="flex flex-wrap items-center justify-between gap-2"><strong>Class recording</strong><span className="text-xs text-muted-foreground">{status ? `${status.chunks.serverConfirmed}/${status.chunks.expected ?? '?'} slices uploaded · ${status.chunks.transcribed} transcribed` : 'Loading…'}</span></div>
    {status?.captureInterrupted ? <p className="text-xs text-amber-600">Capture was interrupted. The final moments may be missing.</p> : null}
    {local?.phase === 'interrupted' ? <div><p className="text-sm">Recording was interrupted. The audio saved on this device can still be finished.</p><Button size="sm" onClick={() => void finishSavedAudio()}>Finish saved audio</Button></div> : null}
    {local?.lastError && local.phase !== 'interrupted' && status?.recordingStatus !== 'failed' ? <div><p role="alert" className="text-sm text-destructive">{local.lastError}</p><Button size="sm" variant="outline" onClick={() => void syncLecture(recordingId).then(refresh)}>Resume upload</Button></div> : null}
    {status?.recordingStatus !== 'completed' ? <p role="status" className="text-sm">{status?.recordingStatus === 'failed' ? 'Processing needs attention.' : status?.captureComplete ? 'Processing the lecture…' : 'Recording or uploading audio…'} {status?.error || ''}</p> : null}
    {status?.recordingStatus === 'failed' ? <Button size="sm" variant="outline" onClick={() => void retry()}>Retry failed work</Button> : null}
    {status?.recordingStatus === 'completed' ? <label className="text-xs">Note detail <select className="ml-2 rounded border border-border bg-background p-1" value={String(status.preferences.depth || 'standard')} onChange={event => void changeDepth(event.target.value as 'concise' | 'standard' | 'detailed')}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label> : null}
    {status?.recordingStatus === 'completed' && status.preferences.keepAudio !== false ? <Button size="sm" variant="outline" disabled={removingAudio} onClick={() => void removeSavedAudio()}>{removingAudio ? 'Removing audio…' : 'Delete audio, keep notes'}</Button> : null}
    {audioRemovalFailed ? <div role="alert" className="space-y-2"><p className="text-xs text-muted-foreground">Audio cleanup stopped after a temporary failure. Some audio may already be gone; notes and transcript remain.</p><Button size="sm" variant="outline" disabled={removingAudio} onClick={() => void removeSavedAudio()}>{removingAudio ? 'Retrying…' : 'Retry audio removal'}</Button></div> : null}
    {audioRetained && chunks.length ? <Button size="sm" variant="outline" onClick={() => void seek(chunks[0].startMs)}>Play class from start</Button> : null}
    {audioRemovalPending ? <p role="status" className="text-xs text-muted-foreground">Removing the server audio copy in the background. Playback is paused during removal; notes and transcript stay available.</p> : null}
    {!audioRetained ? <p className="text-xs text-muted-foreground">Audio was removed after processing, as requested when recording began. Notes and transcript remain available.</p> : null}
    {audioUrl ? <audio ref={player} controls src={audioUrl} aria-label="Lecture audio" onEnded={() => { const next = chunks.find(item => item.sequenceNumber === (currentSequence.current ?? -1) + 1); if (next) void seek(next.startMs); }} /> : null}
    {ordered.map((block, index) => {
      const section = bySection.get(block.sectionId);
      const showHeading = section && ordered[index - 1]?.sectionId !== section.id;
      return <div key={block.id}>{showHeading ? <h3 className="mt-4 font-semibold">{section.title}</h3> : null}<article className="mt-2"><h4 className="text-sm font-medium">{block.title}</h4><RichContent body={block.content} /><div className="flex flex-wrap gap-2 text-xs">{block.evidence.map((ref, index) => audioRetained ? <button type="button" className="text-primary underline" key={`${ref.segmentId}-${index}`} onClick={() => void seek(ref.startMs)} title="Play cited audio" aria-label={`Play cited audio at ${timestamp(ref.startMs)}`}>▶ {timestamp(ref.startMs)}</button> : <span key={`${ref.segmentId}-${index}`}>{timestamp(ref.startMs)}</span>)}{block.sourceKind === 'ai_enrichment' ? <span>AI explanation</span> : null}{block.verificationStatus === 'uncertain' ? <span>Audio unclear</span> : null}</div></article></div>;
    })}
    {!ordered.length && transcript.length ? <details><summary>{status?.recordingStatus === 'completed' ? 'No verified note blocks; view the transcript' : 'Transcript available while notes process'}</summary>{transcript.map(segment => <p key={segment.id} className="my-2 text-sm">{audioRetained ? <button type="button" className="text-primary underline" onClick={() => void seek(segment.startMs)}>{timestamp(segment.startMs)}</button> : <span>{timestamp(segment.startMs)}</span>} {segment.normalizedText || segment.rawText}</p>)}</details> : null}
    <LectureTranscriptEditor recordingId={recordingId} segments={transcript} onChanged={refresh} />
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
  </section>;
}
