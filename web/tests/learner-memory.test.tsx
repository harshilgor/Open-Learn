import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({ request }));

import { MemoryFirstRunNotice, MemorySavedChip } from '@/components/memory-saved-chip';
import { clientTimezone, MEMORY_NOTICE_KEY, MEMORY_SETTINGS_OPEN_EVENT, pastedRangesFor } from '@/lib/learner-memory';

let root: Root, container: HTMLDivElement;
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); localStorage.clear();
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers(); });
async function render(node: ReactNode) {
  await act(async () => { root.render(node); });
  await act(async () => { await vi.runOnlyPendingTimersAsync(); });
}
const button = (label: string) => Array.from(container.querySelectorAll('button')).find(item => item.textContent === label)!;
const fact = { id: 'fact_1', kind: 'deadline', statement: 'Has a calculus midterm on 2026-11-03.', courseId: null, origin: 'user_stated', status: 'active', learnedAt: 1, revision: 1 };

it('marks every remaining pasted snippet and ignores edited or missing ones', () => {
  const message = 'Explain: E = mc^2. Also E = mc^2 again, and my exam is Friday';
  expect(pastedRangesFor(message, ['E = mc^2', 'not in the message', '  '])).toEqual([{ start: 9, end: 17 }, { start: 24, end: 32 }]);
  expect(pastedRangesFor('typed only', ['E = mc^2'])).toEqual([]);
  expect(clientTimezone()).toMatch(/^[A-Za-z0-9_+\-/]+$/);
});

it('shows what a turn saved and undoes it, restoring any predecessor', async () => {
  request.mockImplementation((path: string) => Promise.resolve(path.startsWith('/v1/memory/facts?') ? { items: [fact] } : { status: 'deleted', restored: [] }));
  const opened = vi.fn(); window.addEventListener(MEMORY_SETTINGS_OPEN_EVENT, opened);
  await render(<MemorySavedChip generationId="gen 1" delays={[0]} />);
  expect(request).toHaveBeenCalledWith('/v1/memory/facts?generation_id=gen%201');
  expect(container.textContent).toContain('Saved to memory: Has a calculus midterm on 2026-11-03.');
  await act(async () => { button('View').click(); });
  expect(opened).toHaveBeenCalledOnce();
  await act(async () => { button('Undo').click(); });
  expect(request).toHaveBeenCalledWith('/v1/memory/facts/fact_1?undo=true', { method: 'DELETE' });
  expect(container.textContent).toContain('Removed from memory.');
  window.removeEventListener(MEMORY_SETTINGS_OPEN_EVENT, opened);
});

it('stays silent when the turn saved nothing', async () => {
  request.mockResolvedValue({ items: [] });
  await render(<MemorySavedChip generationId="gen-quiet" delays={[0, 0]} />);
  expect(container.innerHTML).toBe('');
});

it('shows the first-run notice once, only when learning from chats is on', async () => {
  const load = vi.fn().mockResolvedValue({ learningEnabled: true, extraction: 'on' });
  await render(<MemoryFirstRunNotice load={load} />);
  expect(container.textContent).toContain('Open Learn now remembers useful things you tell it');
  await act(async () => { button('Got it').click(); });
  expect(container.innerHTML).toBe('');
  expect(localStorage.getItem(MEMORY_NOTICE_KEY)).not.toBeNull();
  act(() => root.unmount()); root = createRoot(container);
  await render(<MemoryFirstRunNotice load={load} />);
  expect(container.innerHTML).toBe('');
  expect(load).toHaveBeenCalledOnce();
});

it('hides the notice when extraction is off or the learner paused learning', async () => {
  await render(<MemoryFirstRunNotice load={() => Promise.resolve({ learningEnabled: true, extraction: 'off' as const })} />);
  expect(container.innerHTML).toBe('');
  await render(<MemoryFirstRunNotice load={() => Promise.resolve({ learningEnabled: false, extraction: 'on' as const })} />);
  expect(container.innerHTML).toBe('');
});
