import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { StudyDashboard } from '@/components/study-dashboard';
import type { CourseSummary } from '@/lib/api';

const mocks = vi.hoisted(() => ({ review: vi.fn(), request: vi.fn(), openQuiz: vi.fn(), openCards: vi.fn() }));
vi.mock('@/lib/api', () => ({ learningApi: { getReviewDashboard: mocks.review }, request: mocks.request }));
vi.mock('@/lib/workspace-events', () => ({ openWorkspaceQuiz: mocks.openQuiz, openWorkspaceFlashcards: mocks.openCards }));
vi.mock('@/components/buddy-today', () => ({ BuddyToday: () => <p>Upcoming schedule</p> }));
// Schedule and routine widgets load their own data; this suite covers the dashboard's actions.
vi.mock('@/components/calendar/calendar-agenda', () => ({ CalendarAgenda: () => <p>Upcoming schedule</p> }));
vi.mock('@/components/routine-controls', () => ({ RoutineControls: () => null }));
let container: HTMLDivElement, root: Root;
const actions = { onReview: vi.fn(), onCourse: vi.fn(), onAddCourse: vi.fn(), onReminders: vi.fn(), onStudy: vi.fn(), onClass: vi.fn(), onPrep: vi.fn() };
beforeEach(() => {
  vi.clearAllMocks(); mocks.review.mockResolvedValue({ dueCount: 3 });
  mocks.request.mockImplementation(async (path: string) => path.startsWith('/v1/quizzes') ? { quizzes: [] } : path.startsWith('/v1/flashcard-due-summary') ? { dueCount: 0, courses: {}, sessions: [] } : { items: [], nextCursor: null, snapshotRevision: '1', generatedAt: 0, partial: false });
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
async function render(courses: CourseSummary[] = []) { await act(async () => root.render(<StudyDashboard courses={courses} {...actions}/>)); }
function click(label: string) { const button = [...container.querySelectorAll('button')].find(item => item.textContent?.includes(label))!; act(() => button.click()); }
it('opens review, reminders, and study through their existing actions', async () => {
  await render(); expect(container.textContent).toContain('3 concepts are ready');
  click('Start review'); click('Open reminders'); click('Continue studying');
  expect(actions.onReview).toHaveBeenCalledOnce(); expect(actions.onReminders).toHaveBeenCalledOnce(); expect(actions.onStudy).toHaveBeenCalledOnce();
});
it('keeps review available with no due concepts and offers a first course', async () => {
  mocks.review.mockResolvedValue({ dueCount: 0 }); await render();
  click('Open review'); click('Add your first course');
  expect(actions.onReview).toHaveBeenCalledOnce(); expect(actions.onAddCourse).toHaveBeenCalledOnce();
});
it('opens active courses and excludes archived courses', async () => {
  await render([{ id: 'physics', name: 'Physics', roadmapProgress: 45 }, { id: 'old', name: 'Archived subject', archivedAt: '2026-10-01' }] as CourseSummary[]);
  expect(container.textContent).not.toContain('Archived subject');
  expect(container.querySelector('progress')?.value).toBe(45);
  click('Physics'); expect(actions.onCourse).toHaveBeenCalledWith('physics');
});
it('reports an unavailable queue without showing a false zero and retries', async () => {
  mocks.review.mockRejectedValueOnce(new Error('offline')); await render();
  expect(container.textContent).toContain('review count is unavailable');
  expect(container.textContent).not.toContain('Nothing due');
  await act(async () => click('Retry review count'));
  expect(container.textContent).toContain('3 concepts are ready');
});

function nextUp() { return container.querySelector('[aria-labelledby="dashboard-next-up"]')!; }
function nextAction() { return nextUp().querySelector('button')!; }
it('puts an unfinished quiz first in Next up and resumes it', async () => {
  mocks.request.mockImplementation(async (path: string) => path.startsWith('/v1/quizzes') ? { quizzes: [
    { id: 'done', title: 'Forces', sessionId: 's1', origin: 'ask', status: 'completed', count: 5, attempted: 5 },
    { id: 'open', title: 'Momentum', sessionId: 's2', lessonNoteId: 'n2', origin: 'learn', status: 'in_progress', count: 5, attempted: 2 },
  ] } : path.startsWith('/v1/flashcard-due-summary') ? { dueCount: 8, courses: {}, sessions: [] } : { items: [] });
  mocks.review.mockResolvedValue({ dueCount: 3, weakCount: 1, streakDays: 4, estimatedMinutes: 6 });
  await render();
  expect(nextUp().textContent).toContain('Finish “Momentum”');
  expect(nextUp().textContent).toContain('4 days streak');
  expect(nextUp().textContent).toContain('About 6 min');
  act(() => nextAction().click());
  expect(mocks.openQuiz).toHaveBeenCalledWith({ sessionId: 's2', quizId: 'open', lessonNoteId: 'n2', origin: 'learn' });
});
it('falls through to due flashcards, then concept review, when other sources fail', async () => {
  mocks.request.mockImplementation(async (path: string) => { if (path.startsWith('/v1/quizzes')) throw new Error('offline'); if (path.startsWith('/v1/flashcard-due-summary')) return { dueCount: 2, courses: {}, sessions: [] }; return { items: [] }; });
  await render();
  expect(nextUp().textContent).toContain('2 flashcards ready');
  act(() => nextAction().click());
  expect(mocks.openCards).toHaveBeenCalledWith({ view: 'library' });
  act(() => root.unmount()); root = createRoot(container);
  mocks.request.mockRejectedValue(new Error('offline'));
  await render();
  expect(nextUp().textContent).toContain('3 concepts to review');
  act(() => nextAction().click());
  expect(actions.onReview).toHaveBeenCalledOnce();
});
it('offers a fresh start when nothing is waiting', async () => {
  mocks.review.mockResolvedValue({ dueCount: 0, weakCount: 0, streakDays: 0, estimatedMinutes: 0 });
  await render();
  expect(nextUp().textContent).toContain('Start a new topic');
  act(() => nextAction().click());
  expect(actions.onStudy).toHaveBeenCalledOnce();
});
it('suggests preparing for the next event today when practice is clear', async () => {
  const start = new Date(Date.now() + 3600000).toISOString(), end = new Date(Date.now() + 7200000).toISOString();
  mocks.review.mockResolvedValue({ dueCount: 0, weakCount: 0, streakDays: 0, estimatedMinutes: 0 });
  mocks.request.mockImplementation(async (path: string) => path.startsWith('/v1/calendar/occurrences') ? { items: [
    { id: 'past', title: 'Earlier lab', type: 'class', courseId: 'physics', temporal: { mode: 'timed', timezone: 'UTC', start: '2000-01-01T09:00:00Z', end: '2000-01-01T10:00:00Z' } },
    { id: 'next', title: 'Physics lecture', type: 'class', courseId: 'physics', temporal: { mode: 'timed', timezone: 'UTC', start, end } },
  ] } : path.startsWith('/v1/quizzes') ? { quizzes: [] } : { dueCount: 0, courses: {}, sessions: [] });
  await render([{ id: 'physics', name: 'Physics', roadmapProgress: 0 }] as CourseSummary[]);
  expect(nextUp().textContent).toContain('Physics lecture');
  act(() => nextAction().click());
  expect(actions.onPrep).toHaveBeenCalledWith('physics', 'Physics lecture');
});
