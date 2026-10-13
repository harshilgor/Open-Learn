import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const { request, openChatSession } = vi.hoisted(() => ({ request: vi.fn(), openChatSession: vi.fn() }));
vi.mock('@/lib/api', () => ({ request, learningApi: { listChatSessions: vi.fn() } }));
vi.mock('@/lib/workspace-events', () => ({ openChatSession }));
vi.mock('@/components/source-memory-settings', () => ({ SourceMemorySettings: () => <p>Source tools</p> }));
const { buddies } = vi.hoisted(() => ({ buddies: { snapshot: null as unknown, edit: vi.fn() } }));
vi.mock('@/components/buddies', () => ({ useBuddies: () => buddies }));

import { LearnerMemorySettings } from '@/components/learner-memory-settings';

type Fact = Record<string, unknown>;
const base = { courseId: null, origin: 'user_stated', status: 'active', learnedAt: 1_790_000_000, revision: 1, eventDate: null,
  sensitive: false, sensitiveEnabled: false, needsReview: false, confirmedAt: null, basis: [] as unknown[] };
const goal: Fact = { ...base, id: 'goal', kind: 'goal', statement: 'Wants to pass AP Calculus BC.',
  basis: [{ type: 'turn', sessionId: 'chat-1', turnIndex: 3, quote: 'I want to pass AP calc BC' }] };
const pref: Fact = { ...base, id: 'pref', kind: 'preference', statement: 'Prefers short answers.', courseId: 'calc', origin: 'inferred', status: 'tentative' };
const health: Fact = { ...base, id: 'health', kind: 'constraint', statement: 'Has ADHD.', sensitive: true, basis: [{ type: 'learner' }] };

let state: { active: Fact[]; tentative: Fact[]; archived: Fact[] };
let root: Root, container: HTMLDivElement;

function respond(path: string, init?: { method?: string; body?: string }) {
  const method = init?.method || 'GET';
  if (method === 'GET') {
    const status = /status=(\w+)/.exec(path)?.[1] as keyof typeof state | undefined;
    if (status) return { items: state[status] };
    if (path === '/v1/memory/profile') return { source: 'stored', text: '', items: [goal] };
    if (path === '/v1/memory/changes') return { items: [{ at: 1_790_000_000, source: 'learner', summary: '1 memory edited by you' }] };
    if (path === '/v1/memory/episodes') return { items: [{ id: 'ep1', sessionId: 'chat-1', courseId: null, periodStart: 1, periodEnd: 1_790_000_000, summary: 'Covered limits.', topics: [] }] };
    if (path === '/v1/memory/settings') return { learningEnabled: true, revision: 2, updatedAt: null, extraction: 'on' };
    if (path === '/v1/courses') return [{ id: 'calc', name: 'Calculus' }];
    if (path === '/v1/memory/forget-all') return { facts: 3, episodes: 1, confirmation: 'forget_token' };
    if (path.endsWith('/history')) return { items: [{ ...goal, id: 'old', statement: 'Wants to pass calc.' }, goal] };
  }
  return { status: 'ok' };
}

beforeEach(() => {
  vi.clearAllMocks();
  state = { active: [goal, health], tentative: [pref], archived: [] };
  request.mockImplementation((path: string, init?: { method?: string; body?: string }) => Promise.resolve(respond(path, init)));
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

async function render() {
  await act(async () => { root.render(<LearnerMemorySettings loadChats={() => Promise.resolve({ 'chat-1': 'Calc review' })} />); });
  await act(async () => { await Promise.resolve(); });
}
const within = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLElement;
const button = (scope: Element, label: string) => Array.from(scope.querySelectorAll('button')).find(item => item.textContent === label) as HTMLButtonElement;
const calls = (method: string) => request.mock.calls.filter(([, init]) => (init?.method || 'GET') === method);
async function click(target: HTMLElement) { await act(async () => { target.click(); }); await act(async () => { await Promise.resolve(); }); }
function type(input: HTMLInputElement | HTMLSelectElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')!.set!;
  act(() => { setter.call(input, value); input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true })); });
}

it('groups memories by kind and says where each one came from', async () => {
  await render();
  expect(within('Goals').textContent).toContain('Wants to pass AP Calculus BC.');
  expect(within('Preferences').textContent).toContain('Calculus · ');
  expect(within('Preferences').textContent).toContain('Not confirmed yet');
  const row = within('Wants to pass AP Calculus BC.');
  expect(row.textContent).toContain('in “Calc review”');
  expect(row.textContent).toContain('“I want to pass AP calc BC”');
  await click(button(row, `You said this on ${new Date(1_790_000_000_000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })} in “Calc review”`));
  expect(openChatSession).toHaveBeenCalledWith('chat-1');
  expect(within('What the tutor always knows').textContent).toContain('Wants to pass AP Calculus BC.');
  expect(within('Recently updated').textContent).toContain('1 memory edited by you');
  expect(container.textContent).toContain('Source tools');  // the old source tools, under Advanced
});

it('confirms an inferred memory with its revision', async () => {
  await render();
  await click(button(within('Prefers short answers.'), 'Confirm'));
  expect(request).toHaveBeenCalledWith('/v1/memory/facts/pref/confirm', { method: 'POST', body: JSON.stringify({ expectedRevision: 1 }) });
  expect(container.textContent).toContain('Confirmed.');
});

it('edits a memory in place and sends the new wording', async () => {
  await render();
  await click(button(within('Wants to pass AP Calculus BC.'), 'Edit'));
  const input = container.querySelector('form input') as HTMLInputElement;
  expect(input.value).toBe('Wants to pass AP Calculus BC.');
  type(input, 'Wants a 5 on AP Calculus BC.');
  await click(button(container, 'Save changes'));
  const [path, init] = calls('PATCH')[0];
  expect(path).toBe('/v1/memory/facts/goal');
  expect(JSON.parse(init.body)).toEqual({ statement: 'Wants a 5 on AP Calculus BC.', kind: 'goal', courseId: null, eventDate: null, expectedRevision: 1 });
});

it('asks before forgetting one memory', async () => {
  await render();
  const row = within('Wants to pass AP Calculus BC.');
  await click(button(row, 'Forget'));
  expect(calls('DELETE')).toHaveLength(0);
  await click(button(row, 'Yes, forget'));
  expect(request).toHaveBeenCalledWith('/v1/memory/facts/goal', { method: 'DELETE' });
});

it('lets the learner allow a sensitive memory into chats', async () => {
  await render();
  const toggle = within('Has ADHD.').querySelector('input[type="checkbox"]') as HTMLInputElement;
  expect(toggle.checked).toBe(false);
  await click(toggle);
  expect(request).toHaveBeenCalledWith('/v1/memory/facts/health/sensitive', { method: 'PUT', body: JSON.stringify({ enabled: true, expectedRevision: 1 }) });
});

it('resolves a review conflict by keeping one side', async () => {
  state.active = [{ ...goal, needsReview: true }];
  state.tentative = [{ ...goal, id: 'goal2', statement: 'Wants to pass AP Calculus AB.', needsReview: true, revision: 4 }];
  await render();
  const review = within('Needs your review');
  expect(review.textContent).toContain('Wants to pass AP Calculus AB.');
  expect(within('Goals')).toBeNull();
  await click(button(within('Wants to pass AP Calculus AB.'), 'Keep this one'));
  expect(request).toHaveBeenCalledWith('/v1/memory/facts/goal2/confirm', { method: 'POST', body: JSON.stringify({ expectedRevision: 4 }) });
});

it('pauses learning with the settings revision', async () => {
  await render();
  const toggle = Array.from(container.querySelectorAll('label')).find(label => label.textContent === 'Pause learning new memories')!.querySelector('input')!;
  await click(toggle);
  expect(request).toHaveBeenCalledWith('/v1/memory/settings', { method: 'PUT', body: JSON.stringify({ learningEnabled: false, expectedRevision: 2 }) });
  expect(container.textContent).toContain('Paused.');
});

it('adds a memory, and a deadline needs a date', async () => {
  await render();
  const form = container.querySelector('details form') as HTMLFormElement;
  type(form.querySelector('input') as HTMLInputElement, 'Final exam');
  type(form.querySelector('select') as HTMLSelectElement, 'deadline');
  expect(button(form, 'Remember this').disabled).toBe(true);
  type(form.querySelector('input[type="date"]') as HTMLInputElement, '2026-12-14');
  await click(button(form, 'Remember this'));
  const [path, init] = calls('POST').find(([target]) => target === '/v1/memory/facts')!;
  expect(path).toBe('/v1/memory/facts');
  expect(JSON.parse(init.body)).toEqual({ statement: 'Final exam', kind: 'deadline', courseId: null, eventDate: '2026-12-14' });
});

it('filters by course', async () => {
  await render();
  type(container.querySelector('select') as HTMLSelectElement, 'calc');
  expect(container.textContent).toContain('Prefers short answers.');
  expect(container.textContent).not.toContain('Wants to pass AP Calculus BC.Calculus');
  expect(within('Goals')).toBeNull();
});

it('shows a server conflict and reloads', async () => {
  await render();
  request.mockImplementationOnce(() => Promise.reject(new Error('This memory changed. Refresh and try again.')));
  const before = calls('GET').length;
  await click(button(within('Prefers short answers.'), 'Confirm'));
  expect(container.textContent).toContain('This memory changed. Refresh and try again.');
  expect(calls('GET').length).toBeGreaterThan(before);
});

it('shows the history of a memory', async () => {
  await render();
  await click(button(within('Wants to pass AP Calculus BC.'), 'History'));
  expect(within('Earlier versions').textContent).toContain('Wants to pass calc.');
});

it('deletes a session summary', async () => {
  await render();
  expect(within('Session summaries').textContent).toContain('Calc review');
  await click(button(within('Session summaries'), 'Delete'));
  expect(request).toHaveBeenCalledWith('/v1/memory/episodes/ep1', { method: 'DELETE' });
});

it('forgets everything only after showing what will be deleted', async () => {
  await render();
  const section = within('Forget everything');
  await click(button(section, 'Forget everything…'));
  expect(section.textContent).toContain('permanently deletes 3 memories and 1 session summary');
  expect(calls('POST')).toHaveLength(0);
  await click(button(section, 'Delete all memories'));
  expect(request).toHaveBeenCalledWith('/v1/memory/forget-all', { method: 'POST', body: JSON.stringify({ confirmation: 'forget_token' }) });
});

it('shows Buddy settings read-only and opens the Buddy editor to change them', async () => {
  const buddy = { id: 'b1', name: 'Sage', style: 'calm', concise: true, examples: false, hintsFirst: true, exampleTheme: 'music', archived: false };
  buddies.snapshot = { profiles: [buddy, { ...buddy, id: 'old', name: 'Retired', archived: true }] };
  await render();
  const section = within('Buddy settings');
  expect(section.textContent).toContain('Sage');
  expect(section.textContent).toContain('calm tone · concise answers · examples only on request · hints before answers · music examples');
  expect(section.textContent).not.toContain('Retired');
  await click(button(section, 'Change in Buddy settings'));
  expect(buddies.edit).toHaveBeenCalledWith(buddy);
  buddies.snapshot = null;
});
