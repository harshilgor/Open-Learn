"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Pause, Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { lectureCapture, LECTURE_CAPTURE_EVENT, type CapturePhase } from '@/lib/lecture-capture';
import { getLocalLecture, defaultLecturePreferences, discardEmptyLocalLecture, exportLocalLecture, listLocalChunks, listLocalLectures, updateLocalLecture, type LocalLecture, type LecturePreferences } from '@/lib/lecture-local-store';
import { LECTURE_SYNC_EVENT, recoverLocalLectures, startLectureRecovery, syncLecture } from '@/lib/lecture-upload-queue';
import { learningApi, request, type LectureStatus, type LectureTranscriptSegment,type CourseMaterial,type CourseSummary } from '@/lib/api';
import { openClassWorkspace,type ClassPolicy } from '@/lib/in-class';
import styles from './class-recorder.module.css';
import { readSettingsPreferences, SETTINGS_CHANGED_EVENT } from '@/lib/settings-preferences';
import { needsFloatingRecovery, processingStarted } from '@/lib/recording-ui';
import { useBuddies } from './buddies';

function clock(ms: number) { return `${Math.floor(ms / 60000).toString().padStart(2, '0')}:${Math.floor(ms % 60000 / 1000).toString().padStart(2, '0')}`; }

export function ClassRecorder({ setupOpen, onSetupOpenChange, folder, courseId, courseName, onNoteCreated }: {
  setupOpen: boolean; onSetupOpenChange: (open: boolean) => void; folder: string | null;
  courseId?: string | null; courseName?:string; onNoteCreated: (noteId: string) => void;
}) {
  const [title, setTitle] = useState('');
  const [pickedCourse,setPickedCourse]=useState('');
  const effectiveCourse=courseId||pickedCourse||null;
  const [courses,setCourses]=useState<CourseSummary[]>([]);
  const [materials,setMaterials]=useState<CourseMaterial[]>([]);
  const [selectedMaterials,setSelectedMaterials]=useState<string[]>([]);
  const [policy,setPolicy]=useState<ClassPolicy>({notes:true,materials:true,practice:true,flashcards:false});
  const [consent,setConsent]=useState(false);
  const [owner,setOwner]=useState<string|null>(null);
  const [microphones,setMicrophones]=useState<MediaDeviceInfo[]>([]);
  const [microphoneId,setMicrophoneId]=useState('');
  const [starting,setStarting]=useState(false);
  useEffect(()=>{let live=true;void request<{ownerId:string}>('/v1/account').then(value=>{if(live)setOwner(value.ownerId);}).catch(()=>undefined);if(setupOpen){void learningApi.listCourses().then(value=>{if(live)setCourses(value);}).catch(()=>undefined);void navigator.mediaDevices?.enumerateDevices().then(value=>{if(live)setMicrophones(value.filter(device=>device.kind==='audioinput'));}).catch(()=>undefined);}return()=>{live=false;};},[setupOpen]);
  useEffect(()=>{let live=true;if(!setupOpen||!effectiveCourse)return;void learningApi.listCourseMaterials(effectiveCourse).then(value=>{if(live)setMaterials(value.materials.filter(material=>['ready','partially_ready'].includes(material.status)&&!['answer_key','sample_paper'].includes(material.role)));}).catch(()=>{if(live)setMaterials([]);});return()=>{live=false;};},[setupOpen,effectiveCourse]);
  const buddies=useBuddies();
  const refreshBuddies=buddies.refresh;
  const [buddyOverride,setBuddyOverride]=useState<{course:string|null|undefined;id:string}>({course:courseId,id:''});
  const effectiveOverride=buddyOverride.course===effectiveCourse?buddyOverride.id:'';
  const resolvedBuddy=effectiveOverride|| (effectiveCourse?buddies.snapshot?.courses[effectiveCourse]:null)||buddies.snapshot?.defaultBuddyId;
  const [preferences, setPreferences] = useState<LecturePreferences>(() => {
    const defaults = readSettingsPreferences();
    return { ...defaultLecturePreferences, depth: defaults.lectureDepth, keepAudio: defaults.keepLectureAudio };
  });
  const [phase, setPhase] = useState<CapturePhase>(() => lectureCapture.phase);
  const [elapsed, setElapsed] = useState(0);
  const [audioLevel,setAudioLevel]=useState(0);
  useEffect(()=>{
    const stream=lectureCapture.mediaStream;
    if(phase!=='recording'||!stream||typeof AudioContext==='undefined')return;
    let context:AudioContext|undefined,timer:ReturnType<typeof setInterval>|undefined;
    try{
      context=new AudioContext();const analyser=context.createAnalyser();analyser.fftSize=256;
      context.createMediaStreamSource(stream).connect(analyser);
      const values=new Uint8Array(analyser.fftSize);
      timer=setInterval(()=>{analyser.getByteTimeDomainData(values);const rms=Math.sqrt(values.reduce((sum,value)=>sum+((value-128)/128)**2,0)/values.length);setAudioLevel(Math.min(1,rms*8));},120);
    }catch{/* Recording remains available if metering is unsupported. */}
    return()=>{if(timer)clearInterval(timer);void context?.close().catch(()=>undefined);};
  },[phase]);
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
    setSessions(all.filter(item => item.phase !== 'completed' && (item.ownerId||'local')===owner).sort((a, b) => b.startedAtMs - a.startedAtMs));
    const counts = await Promise.all(all.map(async item => {
      const chunks = await listLocalChunks(item.id);
      return [item.id, { total: chunks.length, uploaded: chunks.filter(chunk => chunk.state === 'server_confirmed').length }] as const;
    }));
    setSaved(Object.fromEntries(counts));
  }, [owner]);

  useEffect(() => {
    const stopRecovery = startLectureRecovery();
    if(owner)void recoverLocalLectures(lectureCapture.recordingId,owner).then(refresh).catch(cause => setError(cause instanceof Error ? cause.message : 'Saved recordings could not be read.'));
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; phase?: CapturePhase; error?: string; status?: LectureStatus }>).detail;
      if (detail.phase) setPhase(detail.phase);
      if (detail.error) setError(detail.error);
      if (detail.id && detail.status) setServerStatus(current => ({ ...current, [detail.id!]: detail.status! }));
      if (detail.id && detail.status && processingStarted(detail.status) && !noticedRecordings.current.has(detail.id)) {
        noticedRecordings.current.add(detail.id); setNotice('Audio uploaded. Your class notes are being prepared.');
      }
      if (detail.status?.noteId && !openedNotes.current.has(detail.status.noteId)) { void refreshBuddies(); openedNotes.current.add(detail.status.noteId);const noteId=detail.status.noteId;if(detail.id)void getLocalLecture(detail.id).then(local=>{if(local&&!local.classSetup)noteCreated.current(noteId);}); }
      void refresh();
    };
    window.addEventListener(LECTURE_CAPTURE_EVENT, changed);
    window.addEventListener(LECTURE_SYNC_EVENT, changed);
    const timer = window.setInterval(() => setElapsed(lectureCapture.elapsedMs), 250);
    return () => { stopRecovery(); window.removeEventListener(LECTURE_CAPTURE_EVENT, changed); window.removeEventListener(LECTURE_SYNC_EVENT, changed); window.clearInterval(timer); };
  }, [refresh,refreshBuddies,owner]);
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
    if(!consent||!owner||!effectiveCourse||starting)return;
    setStarting(true);
    setError('');
    setLiveTranscript([]);
    try {
      let deviceId=localStorage.getItem('openlearn-capture-device');if(!deviceId){deviceId=crypto.randomUUID();localStorage.setItem('openlearn-capture-device',deviceId);}
      const id=await lectureCapture.start({ title: title.trim() || `Class recording · ${new Date().toLocaleDateString()}`, courseId:effectiveCourse, buddyId:resolvedBuddy, noteFolder: folder, preferences,ownerId:owner,microphoneId,classSetup:{deviceId,materialVersionIds:selectedMaterials.filter(vid=>materials.some(m=>m.versionId===vid)),policy} });
      openClassWorkspace('class_'+id);
      setConsent(false);onSetupOpenChange(false);
      void refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Microphone recording could not start.'); }
    finally{setStarting(false);}
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
    <Dialog open={setupOpen} onOpenChange={open=>{if(!open)setConsent(false);onSetupOpenChange(open);}}>
      <DialogContent className={styles.setup}>
        <DialogHeader><DialogTitle>Start an In-Class session</DialogTitle><DialogDescription>Audio is saved on this device first. Connected providers prepare live notes and study material after upload; charges may apply. Capture stays on this device, and reopening a class never restarts the microphone.</DialogDescription></DialogHeader>
        {!courseId?<label className={styles.titleLabel}>Course<select value={pickedCourse} onChange={e=>{setPickedCourse(e.target.value);setSelectedMaterials([]);}}><option value="">Choose a course</option>{courses.map(course=><option key={course.id} value={course.id}>{course.name}</option>)}</select></label>:null}
        <p>{courseName||'General class session'} · {buddies.snapshot?.profiles.find(p=>p.id===resolvedBuddy)?.name||'Buddy'}</p><label className={styles.titleLabel}>Class title<input autoFocus value={title} onChange={event => setTitle(event.target.value)} placeholder="e.g. Biology · Lecture 4" /></label>
        <label className={styles.titleLabel}>Buddy for this session<select value={effectiveOverride} onChange={e=>{setBuddyOverride({course:effectiveCourse,id:e.target.value});}}><option value="">Course/default Buddy ({buddies.snapshot?.profiles.find(p=>p.id===resolvedBuddy)?.name||'Buddy'})</option>{buddies.snapshot?.profiles.filter(p=>!p.archived).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className={styles.titleLabel}>Note detail<select value={preferences.depth} onChange={event => setPreferences(current => ({ ...current, depth: event.target.value as LecturePreferences['depth'] }))}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
        <label className={styles.optionLabel}><input type="checkbox" checked={preferences.keepAudio} onChange={event => setPreferences(current => ({ ...current, keepAudio: event.target.checked }))} /> Keep class audio for playback</label>
        {microphones.length>1?<label className={styles.titleLabel}>Microphone<select value={microphoneId} onChange={e=>setMicrophoneId(e.target.value)}><option value="">System default</option>{microphones.map((device,index)=><option key={device.deviceId||index} value={device.deviceId}>{device.label||`Microphone ${index+1}`}</option>)}</select></label>:null}
        <fieldset><legend>Prepare quietly during class</legend>{(['notes','materials','practice','flashcards'] as const).map(key=><label className={styles.optionLabel} key={key}><input type="checkbox" checked={policy[key]} onChange={e=>setPolicy(value=>({...value,[key]:e.target.checked}))}/>{key==='notes'?'Live notes':key==='materials'?'Supporting materials':key==='practice'?'Practice quizzes':'Draft flashcards'}</label>)}</fieldset>
        {materials.length?<fieldset><legend>Available course materials</legend>{materials.map(material=><label className={styles.optionLabel} key={material.versionId}><input type="checkbox" checked={selectedMaterials.includes(material.versionId)} onChange={e=>setSelectedMaterials(current=>e.target.checked?[...current,material.versionId]:current.filter(vid=>vid!==material.versionId))}/>{material.title}</label>)}</fieldset>:<p>No ready course materials selected. Lecture notes can still be prepared.</p>}
        <label className={styles.optionLabel}><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>I have permission to record this class.</label>
        {!owner?<p role="status">Connect to verify your account before starting; saved capture can continue locally if the connection later drops.</p>:null}
        <div className={styles.dialogActions}><Button variant="outline" onClick={() => {setConsent(false);onSetupOpenChange(false);}}>Cancel</Button><Button disabled={!consent||!owner||!effectiveCourse||starting} onClick={() => void start()}><Mic size={16} />{starting?'Starting…':'Start listening'}</Button></div>
        {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      </DialogContent>
    </Dialog>
    {phase === 'recording' || phase === 'paused' || phase === 'finalizing' ? <div className={styles.bubble} role="status" aria-label={`Class recording ${phase}, ${clock(elapsed)}`}>
      <div className={styles.wave} aria-label="Microphone audio level" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={phase==='recording'?Math.round(audioLevel*100):0}>{[.45,.8,1,.8,.45].map((scale,index)=><i key={index} style={{height:4+(phase==='recording'?audioLevel*22*scale:0)}}/>)}</div>
      <span className={`${styles.liveDot} ${phase === 'paused' ? styles.pausedDot : ''}`} />
      <button type="button" onClick={()=>{if(lectureCapture.recordingId)openClassWorkspace('class_'+lectureCapture.recordingId);}} aria-label="Open live class workspace">Class</button>
      <div className={styles.bubbleText}><strong>{phase === 'finalizing' ? 'Saving audio…' : phase === 'paused' ? 'Recording paused' : 'Recording class'}</strong><small>{clock(elapsed)} · {saved[lectureCapture.recordingId || '']?.total || 0} slices saved · {serverStatus[lectureCapture.recordingId||'']?'Connected processing':'Saved locally; connecting'}</small></div>
      <button type="button" disabled={phase === 'finalizing'} title={phase === 'paused' ? 'Resume' : 'Pause'} aria-label={phase === 'paused' ? 'Resume recording' : 'Pause recording'} onClick={() => void (phase === 'paused' ? lectureCapture.resume() : lectureCapture.pause())}>{phase === 'paused' ? <Play size={16} /> : <Pause size={16} />}</button>
      <button type="button" disabled={phase !== 'recording'} title="Mark this moment" aria-label="Mark this moment" onClick={() => lectureCapture.mark()}><Mic size={15} /></button>
      <button type="button" disabled={phase === 'finalizing'} title="Stop and save" aria-label="Stop and save recording" onClick={() => void lectureCapture.stop()}><Square size={15} fill="currentColor" /></button>
      <details className={styles.liveTranscript}><summary>Transcript {liveTranscript.length ? `· ${liveTranscript.length} parts` : '· waiting for audio'}</summary><div>{liveTranscript.length ? liveTranscript.slice(-4).map(segment => <p key={segment.id}>{segment.normalizedText || segment.rawText}</p>) : <p>New words appear here after each audio slice is transcribed.</p>}</div></details>
    </div> : null}
    {recoverySessions.length ? <aside className={styles.recovery} aria-label="Saved class recordings">{recoverySessions.map(session => <div key={session.id}><strong>{session.title}</strong><Button size="sm" variant="outline" onClick={() => void exportLocalLecture(session.id).catch(cause => setError(cause instanceof Error ? cause.message : 'Export failed.'))}>Export recovered audio</Button><small>{saved[session.id]?.uploaded || 0}/{saved[session.id]?.total || 0} slices uploaded</small>{session.lastError ? <small>{session.lastError}</small> : null}{session.phase === 'interrupted' && !saved[session.id]?.total ? <Button size="sm" variant="outline" onClick={() => void discardEmptyLocalLecture(session.id).then(refresh).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not discard the empty recording.'))}>Discard empty recording</Button> : session.phase === 'interrupted' ? <Button size="sm" onClick={() => void finishInterrupted(session)}>Finish saved audio</Button> : <Button size="sm" variant="outline" onClick={() => void syncLecture(session.id)}>Resume upload</Button>}</div>)}</aside> : null}
    {notice ? <p role="status" className={styles.notice}>{notice}</p> : null}
    {error && !setupOpen ? <p role="alert" className={styles.errorBubble}>{error}</p> : null}
  </>;
}
