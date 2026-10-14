import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { workspaceToolFor } from '@/components/workspace-panel';
import { SourcePassageDialog } from '@/components/source-passage-dialog';
import { PracticeOverview } from '@/components/practice-overview';
import { WORKSPACE_QUIZ_OPEN_EVENT, WORKSPACE_SOURCE_OPEN_EVENT } from '@/lib/workspace-events';

const mocks = vi.hoisted(() => ({ request: vi.fn(), summary: vi.fn(), review: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request, learningApi: { getReviewDashboard: mocks.review } }));
vi.mock('@/lib/flashcards-client', () => ({ flashcardsApi: { summary: mocks.summary } }));

let root: Root, container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

it('maps tabs saved by earlier versions onto the four study tools', () => {
  expect(workspaceToolFor('notes')).toBe('notes');
  expect(workspaceToolFor('canvas')).toBe('canvas');
  expect(workspaceToolFor('class')).toBe('class');
  expect(workspaceToolFor('quiz')).toBe('practice');
  expect(workspaceToolFor('flashcards')).toBe('practice');
  expect(workspaceToolFor('sources')).toBeNull();
  expect(workspaceToolFor('reminders')).toBeNull();
});

it('opens the cited passage in a dialog instead of a panel tab', async () => {
  mocks.request.mockImplementation(async (path: string) => {
    if (path.includes('/material-versions/v1/blocks')) return { blocks: [{ id: 'span-2', versionId: 'v1', pageIndex: 3, kind: 'passage', text: 'Mitochondria produce most ATP.' }] };
    throw new Error(`unexpected ${path}`);
  });
  await act(async () => root.render(<SourcePassageDialog />));
  await act(async () => { window.dispatchEvent(new CustomEvent(WORKSPACE_SOURCE_OPEN_EVENT, { detail: { spanId: 'span-2', versionId: 'v1', title: 'Biology textbook' } })); });
  const dialog = document.querySelector('[role="dialog"]');
  expect(dialog?.textContent).toContain('Biology textbook');
  expect(dialog?.textContent).toContain('Page 4');
  expect(dialog?.textContent).toContain('Mitochondria produce most ATP.');
});

it('lists unfinished quizzes under Continue and resumes the exact quiz', async () => {
  mocks.request.mockResolvedValue({ quizzes: [
    { id: 'q-open', title: 'Krebs cycle', sessionId: 's1', origin: 'ask', status: 'ready', count: 8, attempted: 3, score: null, assisted: 0, skipped: 0, dontKnow: 0, contested: 0 },
    { id: 'q-done', title: 'Glycolysis', sessionId: 's1', origin: 'ask', status: 'completed', count: 5, attempted: 5, score: 80, assisted: 0, skipped: 0, dontKnow: 0, contested: 0 },
  ] });
  mocks.summary.mockResolvedValue({ dueCount: 2, courses: {}, sessions: [] });
  mocks.review.mockResolvedValue({ dueCount: 1, weakCount: 0, newCount: 0, totalConcepts: 1, estimatedMinutes: 5, streakDays: 0, preparing: false });
  await act(async () => { root.render(<PracticeOverview />); await new Promise(resolve => setTimeout(resolve, 0)); });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(container.textContent).toContain('Continue');
  expect(container.textContent).toContain('3 of 8 answered');
  expect(container.textContent).toContain('Recent quizzes');
  const opened = vi.fn();
  window.addEventListener(WORKSPACE_QUIZ_OPEN_EVENT, opened);
  const resume = [...container.querySelectorAll('button')].find(button => button.textContent?.includes('Krebs cycle'))!;
  act(() => resume.click());
  window.removeEventListener(WORKSPACE_QUIZ_OPEN_EVENT, opened);
  expect((opened.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ quizId: 'q-open', sessionId: 's1' });
});

it('reopens a panel closed by dragging as a split, not a full-screen chat or panel', async () => {
  const { toggledLayout } = await import('@/components/workspace-split');
  const base = { tabs: ['notes' as const], activeTab: 'notes' as const };
  // Dragged to the right edge: the panel closed at a sliver width.
  expect(toggledLayout({ ...base, width: 20, collapsed: true })).toMatchObject({ collapsed: false, focused: false, width: 50 });
  // Dragged to the left edge: the chat closed and the panel took the screen.
  expect(toggledLayout({ ...base, width: 40, collapsed: false, focused: true })).toMatchObject({ collapsed: false, focused: false, width: 40 });
  // A usable width is kept, and an open split closes normally.
  expect(toggledLayout({ ...base, width: 38, collapsed: true })).toMatchObject({ collapsed: false, width: 38 });
  expect(toggledLayout({ ...base, width: 38, collapsed: false })).toMatchObject({ collapsed: true });
});
