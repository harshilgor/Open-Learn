import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CourseIndex } from '@/components/course-index';
import type { CourseSummary } from '@/lib/api';

let container: HTMLDivElement;
let root: Root;
const onAddCourse = vi.fn();
const onCourse = vi.fn();
const courses: CourseSummary[] = [
  { id: 'physics', name: 'Physics', goal: 'Understand mechanics', sessionCount: 3, noteCount: 2, materialCount: 1, dueReviewCount: 0, roadmapProgress: 40, updatedAt: '2026-10-01' },
  { id: 'biology', name: 'Biology', goal: 'Cell structures', sessionCount: 1, noteCount: 0, materialCount: 0, dueReviewCount: 0, roadmapProgress: 0, updatedAt: '2026-10-02' },
];

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
function render(items: CourseSummary[] = courses) { act(() => root.render(<CourseIndex courses={items} buddyForCourse={() => 'Buddy'} onAddCourse={onAddCourse} onCourse={onCourse}/>)); }

describe('CourseIndex', () => {
  it('shows course activity, filters courses, and preserves course navigation', () => {
    render();
    expect(container.textContent).toContain('3 chats');
    expect(container.textContent).toContain('1 material');
    const search = container.querySelector('input[placeholder="Search courses"]') as HTMLInputElement;
    act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(search, 'bio'); search.dispatchEvent(new Event('input', { bubbles: true })); });
    expect(container.textContent).toContain('Biology');
    expect(container.textContent).not.toContain('Physics');
    const biology = [...container.querySelectorAll('button')].find(button => button.textContent?.includes('Biology'))!;
    act(() => biology.click());
    expect(onCourse).toHaveBeenCalledWith('biology');
  });

  it('offers the existing add-course action in the empty state', () => {
    render([]);
    expect(container.textContent).toContain('Make room for your next subject');
    const add = [...container.querySelectorAll('button')].find(button => button.textContent?.includes('Create your first course'))!;
    act(() => add.click());
    expect(onAddCourse).toHaveBeenCalledOnce();
  });
});
