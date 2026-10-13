import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { StudyDashboard } from '@/components/study-dashboard';
import type { CourseSummary } from '@/lib/api';

const mocks = vi.hoisted(() => ({ review: vi.fn() }));
vi.mock('@/lib/api', () => ({ learningApi: { getReviewDashboard: mocks.review } }));
vi.mock('@/components/buddy-today', () => ({ BuddyToday: () => <p>Upcoming schedule</p> }));
let container: HTMLDivElement, root: Root;
const actions = { onReview: vi.fn(), onCourse: vi.fn(), onAddCourse: vi.fn(), onReminders: vi.fn(), onStudy: vi.fn(), onClass: vi.fn(), onPrep: vi.fn() };
beforeEach(() => {
  vi.clearAllMocks(); mocks.review.mockResolvedValue({ dueCount: 3 });
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
