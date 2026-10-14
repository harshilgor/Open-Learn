import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ page: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), upload: vi.fn(), saveLocal: vi.fn() }));
vi.mock('@/lib/api', async original => ({ ...await original<object>(), learningApi: {
  listWorkspaceNotesPage: mocks.page, searchWorkspaceNotes: vi.fn(async () => ({ notes: [] })), getWorkspaceNote: mocks.get,
  createWorkspaceNote: mocks.create, updateWorkspaceNote: mocks.update, uploadClassRecording: mocks.upload,
  getClassRecording: vi.fn(async () => ({ status: 'queued' })), getClassRecordingAudio: vi.fn(), listCourses: vi.fn(async () => []),
} }));
vi.mock('@/lib/class-recordings', () => ({ saveClassRecording: mocks.saveLocal, getClassRecording: vi.fn(async () => null), deleteClassRecording: vi.fn() }));
vi.mock('@/components/study-note-bar', () => ({ StudyNoteBar: () => null }));
vi.mock('@/components/study-note-panel', () => ({ NoteProposalList: () => null }));
vi.mock('@/components/lecture-notes-view', () => ({ LectureNotesView: () => null }));
vi.mock('@/components/quiz-workspace', () => ({ QuizWorkspace: () => null, LessonPractice: () => null }));

class FakeRecorder {
  static isTypeSupported = () => true;
  state: 'inactive' | 'recording' | 'paused' = 'inactive';
  mimeType = 'audio/webm';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() { this.state = 'recording'; }
  pause() { this.state = 'paused'; }
  resume() { this.state = 'recording'; }
  stop() { this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: 'audio/webm' }) }); this.state = 'inactive'; this.onstop?.(); }
}

let root: Root, container: HTMLDivElement;
const track = { stop: vi.fn() };
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); localStorage.clear();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  Object.assign(globalThis, { MediaRecorder: FakeRecorder });
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) } });
  mocks.page.mockResolvedValue({ notes: [], nextCursor: null });
  mocks.create.mockImplementation(async (input: { title: string; body: string; frontmatter: Record<string, unknown> }) => ({ ...input, id: 'note-1', revision: 1, createdAt: '', updatedAt: new Date().toISOString(), relativePath: 'n.md', learnerId: 'local' }));
  mocks.upload.mockResolvedValue({ id: 'rec_1', status: 'queued' });
  mocks.saveLocal.mockResolvedValue(undefined);
  mocks.get.mockImplementation(async () => ({ id: 'note-1', title: 'Untitled note', body: '', revision: 2, frontmatter: { class_recording_id: 'rec_1', class_recording_status: 'queued' }, createdAt: '', updatedAt: new Date().toISOString(), relativePath: 'n.md', learnerId: 'local' }));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

const settle = async () => { await act(async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setTimeout(resolve, 0)); }); };
const button = (label: string) => [...container.querySelectorAll('button')].find(item => item.getAttribute('aria-label') === label || item.textContent?.trim() === label)!;

it('records into a new note: creates it, uploads the audio and shows the recording', async () => {
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} />));
  await settle();
  act(() => button('New note').click());
  await settle();
  // A blank note offers recording next to the templates.
  expect(button('Record a lecture')).toBeTruthy();
  await act(async () => { button('Record audio into this note').click(); });
  await settle();
  expect(container.querySelector('[aria-label="Recording"]')).not.toBeNull();
  act(() => button('Mark this moment').click());
  await act(async () => { button('Stop & make notes').click(); });
  await settle();
  expect(mocks.create).toHaveBeenCalled();
  expect(mocks.upload).toHaveBeenCalledWith('note-1', expect.any(Blob), expect.any(Number), [expect.any(Number)]);
  expect(mocks.saveLocal).toHaveBeenCalledWith('rec_1', expect.any(Blob));
  expect(track.stop).toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Recording"]')).toBeNull();
  expect(container.textContent).toContain('Recording');
});

it('keeps the audio on the device with retry and download when the upload fails', async () => {
  mocks.upload.mockRejectedValueOnce(new Error('Network unavailable'));
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} />));
  await settle();
  act(() => button('New note').click());
  await settle();
  await act(async () => { button('Record audio into this note').click(); });
  await settle();
  await act(async () => { button('Stop & make notes').click(); });
  await settle();
  expect(container.textContent).toContain('Your recording is still on this device.');
  expect(button('Download audio')).toBeTruthy();
  await act(async () => { button('Retry upload').click(); });
  await settle();
  expect(mocks.upload).toHaveBeenCalledTimes(2);
  expect(container.textContent).not.toContain('Your recording is still on this device.');
});

it('does not leave the note while a recording is running', async () => {
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} />));
  await settle();
  act(() => button('New note').click());
  await settle();
  await act(async () => { button('Record audio into this note').click(); });
  await settle();
  // Starting another note (here through the shared Notes command) is held back.
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} command={{ id: 1, action: 'new-note' }} />));
  await settle();
  expect(container.textContent).toContain('Stop or discard the recording before leaving this note.');
  expect(container.querySelector('[aria-label="Recording"]')).not.toBeNull();
});
