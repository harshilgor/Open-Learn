import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ClassRecorder } from '@/components/class-recorder';
import { LectureNotesView } from '@/components/lecture-notes-view';
const mocks=vi.hoisted(()=>({status:vi.fn(),retry:vi.fn(),local:vi.fn()}));
vi.mock('@/lib/lecture-capture',()=>({lectureCapture:{phase:'idle',recordingId:null,elapsedMs:0},LECTURE_CAPTURE_EVENT:'test-capture'}));
vi.mock('@/lib/lecture-upload-queue',()=>({LECTURE_SYNC_EVENT:'test-sync',startLectureRecovery:()=>()=>{},recoverLocalLectures:async()=>{},syncLecture:async()=>{}}));
vi.mock('@/lib/lecture-local-store',()=>({defaultLecturePreferences:{},listLocalLectures:async()=>[],listLocalChunks:async()=>[],getLocalLecture:mocks.local}));
vi.mock('@/lib/api',async original=>({...await original<object>(),learningApi:{getLectureRecording:mocks.status,retryLectureFailures:mocks.retry,getLectureNotes:async()=>({blocks:[]}),getLectureSections:async()=>({sections:[]}),getLectureChunks:async()=>({chunks:[]}),getLectureTranscript:async()=>({segments:[]})}}));
let root:Root, container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.useFakeTimers();vi.clearAllMocks();container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);mocks.local.mockResolvedValue(null);});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.useRealTimers();});
it('shows a processing failure only in the note banner and retries from there',async()=>{
  mocks.status.mockResolvedValue({noteId:'n1',recordingStatus:'failed',captureComplete:true,error:'Transcription failed',chunks:{serverConfirmed:1,expected:1,transcribed:0},preferences:{keepAudio:true},counts:{audioRetention:'kept'},stages:[]});mocks.retry.mockResolvedValue({});
  act(()=>root.render(<><ClassRecorder setupOpen={false} onSetupOpenChange={()=>{}} folder={null} onNoteCreated={()=>{}}/><LectureNotesView recordingId="r1"/></>));
  await act(async()=>{await vi.advanceTimersByTimeAsync(1);window.dispatchEvent(new CustomEvent('test-sync',{detail:{id:'r1',status:await mocks.status()}}));});
  expect(container.textContent?.match(/Transcription failed/g)).toHaveLength(1);
  expect(container.textContent).not.toContain('Audio uploaded.');expect(container.querySelector('[aria-label="Saved class recordings"]')).toBeNull();
  const retry=[...container.querySelectorAll('button')].find(b=>b.textContent==='Retry failed work')!;
  await act(async()=>retry.click());expect(mocks.retry).toHaveBeenCalledWith('r1');
});
it('auto-dismisses the upload-start notice and does not repeat it for the same recording',async()=>{
  act(()=>root.render(<ClassRecorder setupOpen={false} onSetupOpenChange={()=>{}} folder={null} onNoteCreated={()=>{}}/>));
  const announce=()=>window.dispatchEvent(new CustomEvent('test-sync',{detail:{id:'r1',status:{noteId:'n1',recordingStatus:'processing',captureComplete:true}}}));
  await act(async()=>{announce();});expect(container.textContent).toContain('Audio uploaded.');
  await act(async()=>{await vi.advanceTimersByTimeAsync(4001);});expect(container.textContent).not.toContain('Audio uploaded.');
  await act(async()=>{announce();});expect(container.textContent).not.toContain('Audio uploaded.');
});
