import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ page: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), upload: vi.fn(), saveLocal: vi.fn(), feed: vi.fn(), session: vi.fn(), recordingStatus: vi.fn() }));
vi.mock('@/lib/calendar-client', async original => ({ ...await original<object>(), calendarApi: { feed: mocks.feed } }));
vi.mock('@/components/flashcard-create', () => ({ MakeFlashcards: ({ label }: { label?: string }) => <button type="button">{label}</button> }));
vi.mock('@/lib/api', async original => ({ ...await original<object>(), learningApi: {
  listWorkspaceNotesPage: mocks.page, searchWorkspaceNotes: vi.fn(async () => ({ notes: [] })), getWorkspaceNote: mocks.get,
  createWorkspaceNote: mocks.create, updateWorkspaceNote: mocks.update, uploadClassRecording: mocks.upload,
  getClassRecording: mocks.recordingStatus, getClassRecordingAudio: vi.fn(async () => new Blob(['a'], { type: 'audio/webm' })), listCourses: vi.fn(async () => []),
  createSession: mocks.session,
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
  mocks.feed.mockResolvedValue({ items: [], nextCursor: null });
  mocks.recordingStatus.mockResolvedValue({ status: 'queued' });
  mocks.session.mockResolvedValue({ id: 'session-quiz' });
  URL.createObjectURL = vi.fn(() => 'blob:audio'); URL.revokeObjectURL = vi.fn();
  HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
  localStorage.setItem('openlearn-live-words-v1', 'off');
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
  expect(container.querySelector('[aria-label="Recording controls"]')).not.toBeNull();
  act(() => button('Mark this moment').click());
  await act(async () => { button('Stop & make notes').click(); });
  await settle();
  expect(mocks.create).toHaveBeenCalled();
  expect(mocks.upload).toHaveBeenCalledWith('note-1', expect.any(Blob), expect.any(Number), [expect.any(Number)]);
  expect(mocks.saveLocal).toHaveBeenCalledWith('rec_1', expect.any(Blob));
  expect(track.stop).toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Recording controls"]')).toBeNull();
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
  expect(container.querySelector('[aria-label="Recording controls"]')).not.toBeNull();
});


it('reads transcript timestamps and picks the class under way from the calendar', async () => {
  const { timestampMs, eventForRecording, recordingTitle } = await import('@/lib/note-recording');
  expect(timestampMs('[03:12]')).toBe(192_000);
  expect(timestampMs('[~1:02:05]')).toBe(3_725_000);
  expect(timestampMs('Bold words')).toBeNull();
  const at = Date.parse('2026-10-14T10:05:00Z');
  const event = (title: string, type: string, start: string, end: string) => ({ id: title, calendarId: 'c', title, type, busy: true, revision: 1, courseId: 'bio', temporal: { mode: 'timed' as const, timezone: 'UTC', start, end } });
  const lunch = event('Lunch', 'personal', '2026-10-14T10:00:00Z', '2026-10-14T11:00:00Z');
  const lecture = event('Biology 101', 'class', '2026-10-14T10:00:00Z', '2026-10-14T11:00:00Z');
  const later = event('Physics', 'class', '2026-10-14T13:00:00Z', '2026-10-14T14:00:00Z');
  expect(eventForRecording([lunch, later, lecture], at)?.title).toBe('Biology 101');
  expect(eventForRecording([later], at)).toBeNull();
  expect(recordingTitle(lecture, new Date(at))).toMatch(/^Biology 101 · Oct 14$/);
});

it('names an untitled note after the class on the calendar and files it under that course', async () => {
  const now = Date.now();
  mocks.feed.mockResolvedValue({ items: [{ id: 'e1', calendarId: 'c', title: 'Biology 101', type: 'class', busy: true, revision: 1, courseId: 'course-bio',
    temporal: { mode: 'timed', timezone: 'UTC', start: new Date(now - 600_000).toISOString(), end: new Date(now + 3_000_000).toISOString() } }], nextCursor: null });
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} />));
  await settle();
  act(() => button('New note').click());
  await settle();
  await act(async () => { button('Record audio into this note').click(); });
  await settle();
  expect(container.querySelector<HTMLInputElement>('[aria-label="Note title"]')?.value).toMatch(/^Biology 101 · /);
  await act(async () => { button('Stop & make notes').click(); });
  await settle();
  expect(mocks.create.mock.calls[0][0].frontmatter.course_id).toBe('course-bio');
});

it('turns an uploaded audio file into a recording the server accepts', async () => {
  vi.useFakeTimers();
  const { recordingFromFile } = await import('@/components/note-recorder');
  const memo = recordingFromFile(new File(['voice'], 'Lecture.m4a', { type: 'audio/x-m4a' }));
  await vi.advanceTimersByTimeAsync(4100);
  const recording = await memo;
  vi.useRealTimers();
  expect(recording.blob.type).toBe('audio/mp4');
  await expect(recordingFromFile(new File(['x'], 'notes.pdf', { type: 'application/pdf' }))).rejects.toThrow('Choose an audio file');
  const big = new File(['x'], 'long.mp3', { type: 'audio/mpeg' });
  Object.defineProperty(big, 'size', { value: 25 * 1024 * 1024 });
  await expect(recordingFromFile(big)).rejects.toThrow('larger than 24 MB');
});

it('asks once about live words, then shows words from the browser while recording', async () => {
  localStorage.removeItem('openlearn-live-words-v1');
  const instances: { onresult: ((event: unknown) => void) | null }[] = [];
  class FakeSpeech { continuous = false; interimResults = false; lang = ''; onresult: ((event: unknown) => void) | null = null; onerror = null; onend = null;
    constructor() { instances.push(this); } start() {} stop() {} abort() {} }
  Object.assign(window, { webkitSpeechRecognition: FakeSpeech });
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen={null} onNoteOpenConsumed={() => undefined} />));
  await settle();
  act(() => button('New note').click());
  await settle();
  await act(async () => { button('Record audio into this note').click(); });
  await settle();
  expect(container.textContent).toContain('Show your words live while you record?');
  expect(instances).toHaveLength(0);
  act(() => button('Show live words').click());
  await settle();
  expect(localStorage.getItem('openlearn-live-words-v1')).toBe('on');
  act(() => instances[0].onresult?.({ resultIndex: 0, results: { length: 2, 0: { isFinal: true, 0: { transcript: 'Mitochondria make ATP.' } }, 1: { isFinal: false, 0: { transcript: 'and then' } } } }));
  expect(container.querySelector('[aria-label="Live words"]')?.textContent).toContain('Mitochondria make ATP. and then');
  expect(button('Hide live words')).toBeTruthy();
  delete (window as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
});

it('plays from tapped timestamps and key moments, and starts a quiz grounded in the lecture note', async () => {
  const lecture = { id: 'note-9', title: 'Biology 101 · Oct 14', revision: 4, createdAt: '', updatedAt: new Date().toISOString(), relativePath: 'n.md', learnerId: 'local',
    body: 'My notes.\n\n---\n\n## Study guide\n\nATP.\n\n## Transcript\n\n**[~02:00]** Mitochondria make ATP.',
    frontmatter: { class_recording_id: 'rec_9', class_recording_status: 'completed', class_recording_markers_ms: [65_000], course_id: 'course-bio' } };
  mocks.get.mockResolvedValue(lecture);
  mocks.recordingStatus.mockResolvedValue({ status: 'completed' });
  const opened = vi.fn();
  window.addEventListener('forma:workspace-quiz-open', opened);
  const { NotesWorkspace } = await import('@/components/workspace-panel');
  await act(async () => root.render(<NotesWorkspace noteToOpen="note-9" onNoteOpenConsumed={() => undefined} />));
  await settle(); await settle();
  const player = container.querySelector<HTMLAudioElement>('audio[aria-label="Recording"]')!;
  expect(player).not.toBeNull();
  act(() => button('1:05').click());
  expect(player.currentTime).toBe(65);
  const stamp = container.querySelector<HTMLElement>('[data-seek-ms]')!;
  expect(stamp.textContent).toBe('[~02:00]');
  act(() => stamp.click());
  expect(player.currentTime).toBe(120);
  expect(button('Make flashcards')).toBeTruthy();
  await act(async () => { button('Quiz me on this lecture').click(); });
  await settle();
  expect(mocks.session).toHaveBeenCalledWith(expect.objectContaining({ courseId: 'course-bio' }));
  expect((opened.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ sessionId: 'session-quiz', lessonNoteId: 'note-9' });
  window.removeEventListener('forma:workspace-quiz-open', opened);
});
