import { act, useState, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExerciseCard } from '@/components/exercise-card';
import { RichContent } from '@/components/rich-content';
import { ChatComposer } from '@/components/chat-composer';
import { MessageActionBar, VerificationBadge } from '@/components/message-action-bar';
import { NextActionCards } from '@/components/next-action-cards';

const { createWorkspaceNote, deleteWorkspaceNote, getRecommendations, recordRecommendationInteraction } = vi.hoisted(() => ({ createWorkspaceNote: vi.fn(async () => ({ id: 'note-1', revision: 1 })), deleteWorkspaceNote: vi.fn(async () => undefined), getRecommendations: vi.fn(), recordRecommendationInteraction: vi.fn(async () => undefined) }));
const allowanceState = vi.hoisted(() => ({ snapshot: null as null | { windowId: string | null; windowState: 'ready' | 'active'; serverTime: number; resetsAt: number | null; grantedMicrocredits: number; usedMicrocredits: number; heldMicrocredits: number; availableMicrocredits: number; revision: number; availability: string; reasonCode: string | null }, error: '' }));
vi.mock('@/lib/api', () => ({ learningApi: { searchWorkspaceNotes: vi.fn(async () => ({ notes: [] })), createWorkspaceNote, deleteWorkspaceNote, getRecommendations, recordRecommendationInteraction } }));
vi.mock('@/lib/usage-allowance', () => ({ refreshAllowance: vi.fn(), useAllowance: () => allowanceState, usagePercent: (snapshot: NonNullable<typeof allowanceState.snapshot>) => ({ used: snapshot.usedMicrocredits / snapshot.grantedMicrocredits * 100, held: snapshot.heldMicrocredits / snapshot.grantedMicrocredits * 100, available: snapshot.availableMicrocredits / snapshot.grantedMicrocredits * 100, label: `${Math.round(snapshot.usedMicrocredits / snapshot.grantedMicrocredits * 100)}%` }) }));
vi.mock('@/lib/use-app-reduced-motion', () => ({ useAppReducedMotion: () => true }));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => { allowanceState.snapshot = { windowId: null, windowState: 'ready', serverTime: 1, resetsAt: null, grantedMicrocredits: 100_000_000, usedMicrocredits: 0, heldMicrocredits: 0, availableMicrocredits: 100_000_000, revision: 0, availability: 'available', reasonCode: null }; allowanceState.error = ''; (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container); vi.clearAllMocks(); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
function render(node: ReactNode) { act(() => root.render(node)); }
function button(label: string) { const result = [...container.querySelectorAll('button')].find(item => item.getAttribute('aria-label') === label || item.textContent?.trim() === label); if (!result) throw new Error(`Missing button: ${label}`); return result; }
function click(element: HTMLElement) { act(() => element.click()); }
function typeInto(input: HTMLInputElement, value: string) { act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); }); }

it('allows text sends during a response while retaining a separate stop control', () => {
  const send=vi.fn(),stop=vi.fn();
  render(<ChatComposer value="One more detail" onChange={vi.fn()} attachments={[]} onAttachmentsChange={vi.fn()} onSubmit={send} onCancel={stop} busy allowSendWhileBusy followup gear="Quick" onGearChange={vi.fn()}/>);
  expect(button('Send message').disabled).toBe(false);
  click(button('Send message'));expect(send).toHaveBeenCalledOnce();
  click(button('Stop generating'));expect(stop).toHaveBeenCalledOnce();
  expect(button('Dictate message').disabled).toBe(true);
  expect(button('Chat options and attachments').disabled).toBe(true);
});

describe('composer preferences', () => {
  it('keeps preferences outside the writing surface and changes all explanation depths', () => {
    function Preferences() {
      const [gear, setGear] = useState<'Quick' | 'Guided' | 'Deep'>('Quick');
      return <ChatComposer value="Draft stays here" onChange={vi.fn()} attachments={[]} onAttachmentsChange={vi.fn()} onSubmit={vi.fn()} busy={false} followup={false} gear={gear} onGearChange={setGear} mode="ask" onModeChange={vi.fn()}/>;
    }
    render(<Preferences/>);
    expect(button('Conversation mode').closest('form')).toBeNull();
    const trigger = button('Explanation depth: Quick');
    expect(trigger.closest('form')).toBeNull();
    click(trigger);
    const find = (name: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === name || item.getAttribute('aria-label') === name)!;
    click(find('Deep'));
    expect(button('Explanation depth: Deep')).toBeTruthy();
    const range = document.querySelector<HTMLInputElement>('input[type="range"]')!;
    act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(range, '1'); range.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(button('Explanation depth: Guided')).toBeTruthy();
    expect(range.getAttribute('aria-valuetext')).toBe('Guided');
    click(find('Reset explanation depth to Quick'));
    expect(button('Explanation depth: Quick')).toBeTruthy();
    expect(container.querySelector('textarea')?.value).toBe('Draft stays here');
  });
});

describe('suggested next step', () => {
  it('shows only the current primary action and runs its learning action', async () => {
    getRecommendations.mockResolvedValue({
      id: 'set-1', sessionId: 'session-1', policyVersion: 'immediate-adaptation-v1', status: 'current',
      createdAt: '2026-10-07T00:00:00Z', recommendations: [
        { id: 'rec-primary', actionKind: 'quiz', title: 'Quiz Chain rule', rationale: 'A fresh check will show what to do next.', conceptId: 'chain-rule', conceptTitle: 'Chain rule', effortMinutes: 6, context: { sessionId: 'session-1', conceptId: 'chain-rule' }, score: 100, pedagogicalAction: 'check', whyCode: 'taught_without_check', evidenceIds: [], isPrimary: true },
        { id: 'rec-alternate', actionKind: 'review', title: 'Review Chain rule', rationale: 'An alternate action.', conceptId: 'chain-rule', conceptTitle: 'Chain rule', effortMinutes: 6, context: { sessionId: 'session-1', conceptId: 'chain-rule' }, score: 70, evidenceIds: [], isPrimary: false },
      ],
    });
    const onCheck = vi.fn();
    render(<NextActionCards sessionId="session-1" enabled onLearn={vi.fn()} onAsk={vi.fn()} onQuiz={vi.fn()} onReview={vi.fn()} onCheck={onCheck}/>);
    await act(async () => { await Promise.resolve(); });

    expect(container.textContent).toContain('Check Chain rule');
    expect(container.textContent).not.toContain('Review Chain rule');
    expect(container.querySelectorAll('[aria-label="Suggested next step"] button')).toHaveLength(2);
    click(button('Check Chain rule'));
    expect(onCheck).toHaveBeenCalledOnce();
    expect(recordRecommendationInteraction).toHaveBeenCalledWith('rec-primary', 'selection');
  });
});

describe('tutor response', () => {
  it('renders a heading, keyboard concept control, and exercise from a sample response', () => {
    render(<RichContent body={'## Chain rule\n\n[[Derivative|Rate of change]] links outputs.\n\n```exercise\n{"id":"e-1","type":"numeric","prompt":"2+2?","answer":"4","explanation":"Two plus two is four."}\n```'}/>);
    expect(container.querySelector('h2')?.textContent).toBe('Chain rule');
    click(button('Derivative'));
    expect(container.textContent).toContain('Rate of change');
    expect(container.querySelector('[aria-label="Practice question"]')).not.toBeNull();
  });

  it('keeps existing math and code rendering available', () => {
    render(<RichContent body={'## Example\n\nThe result is $x^2$.\n\n```python\nprint(2 + 2)\n```'}/>);
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.querySelector('pre code')?.textContent).toContain('print(2 + 2)');
  });

  it('supports attempt, wrong answer, hint, correct answer, and reveal', () => {
    const exercise = { id: 'e-2', type: 'numeric' as const, prompt: '2+2?', answer: '4', explanation: 'Two plus two is four.', hint: 'Add two twice.' };
    render(<ExerciseCard exercise={exercise}/>);
    const input = container.querySelector('input')!;
    typeInto(input, '5');
    click(button('Check'));
    expect(container.textContent).toContain('Not quite');
    click(button('Hint'));
    expect(container.textContent).toContain('Add two twice.');
    typeInto(input, '4');
    click(button('Check'));
    expect(container.textContent).toContain('Correct');
    render(<ExerciseCard key="fresh" exercise={exercise}/>);
    click(button('Reveal answer'));
    expect(container.textContent).toContain('Answer: 4');
  });
});

describe('composer and message actions', () => {
  const composer = (value: string, busy = false, onSubmit = vi.fn(), onCancel = vi.fn()) => <ChatComposer value={value} onChange={vi.fn()} attachments={[]} onAttachmentsChange={vi.fn()} onSubmit={onSubmit} onCancel={busy ? onCancel : undefined} busy={busy} followup={false} gear="Quick" onGearChange={vi.fn()} mode="ask" onModeChange={vi.fn()}/>;
  it('switches from empty to typing to streaming and keeps Enter/Shift+Enter behavior', () => {
    const submit = vi.fn();
    render(composer('', false, submit));
    expect(button('Send message').hasAttribute('disabled')).toBe(true);
    render(composer('Hello', false, submit));
    expect(button('Send message').hasAttribute('disabled')).toBe(false);
    const area = container.querySelector('textarea')!;
    act(() => area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true })));
    expect(submit).not.toHaveBeenCalled();
    act(() => area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(submit).toHaveBeenCalledOnce();
    render(composer('Hello', true, submit));
    expect(button('Stop generating')).not.toBeNull();
  });

  it('keeps a draft editable during an outage and blocks submit until reconnect', () => {
    const submit=vi.fn(),retry=vi.fn();
    render(<ChatComposer value="My retained draft" onChange={vi.fn()} attachments={[]} onAttachmentsChange={vi.fn()} onSubmit={submit} busy={false} followup={false} gear="Quick" onGearChange={vi.fn()} unavailable="Connection interrupted" onRetry={retry}/>);
    const area=container.querySelector('textarea')!;
    expect(area.disabled).toBe(false);
    expect(button('Send message').hasAttribute('disabled')).toBe(true);
    act(()=>area.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
    expect(submit).not.toHaveBeenCalled();
    click(button('Retry connection'));expect(retry).toHaveBeenCalledOnce();
    render(composer('My retained draft',true));
    expect(container.querySelector('textarea')!.disabled).toBe(false);
  });

  it('hides the generic connection and usage-check notices while preserving the draft and send safeguards', () => {
    render(<ChatComposer value="My retained draft" onChange={vi.fn()} attachments={[]} onAttachmentsChange={vi.fn()} onSubmit={vi.fn()} busy={false} followup={false} gear="Quick" onGearChange={vi.fn()} unavailable="Open Learn could not connect. You can keep writing your draft." onRetry={vi.fn()}/>);
    expect(container.textContent).not.toContain('Open Learn could not connect. You can keep writing your draft.');
    expect(container.querySelector('[aria-label="Retry connection"]')).toBeNull();
    expect(container.querySelector('textarea')?.value).toBe('My retained draft');
    expect(button('Send message').disabled).toBe(true);

    allowanceState.snapshot = null;
    allowanceState.error = 'Usage could not be checked';
    render(composer('My retained draft'));
    expect(container.textContent).not.toContain('AI work is paused while usage is checked. Your draft stays here.');
    expect(container.querySelector('textarea')?.value).toBe('My retained draft');
    expect(button('Send message').disabled).toBe(true);
  });

  it('keeps a draft editable but blocks new work until allowance is loaded', () => {
    allowanceState.snapshot = null;
    const submit = vi.fn();
    render(composer('Saved draft', false, submit));
    expect(button('Send message').hasAttribute('disabled')).toBe(true);
    expect(container.querySelector('textarea')?.value).toBe('Saved draft');
    expect(submit).not.toHaveBeenCalled();
  });

  it('offers message actions and a data-driven verification badge', async () => {
    const lost = vi.fn();
    render(<><MessageActionBar messageId="lesson-1" markdown="## Chain rule" title="Chain rule" isLatest onLost={lost}/><VerificationBadge verification={{ status: 'verified', agents: 2, sources: [{ title: 'Paper', url: 'https://example.com' }] }}/></>);
    click(button("I'm lost"));
    expect(lost).toHaveBeenCalledOnce();
    await act(async () => button('Save to Notes').click());
    expect(createWorkspaceNote).toHaveBeenCalledOnce();
    expect(container.textContent).toContain('Saved to Notes.');
    await act(async () => button('Undo').click());
    expect(deleteWorkspaceNote).toHaveBeenCalledWith('note-1', 1);
    click(button('Helpful'));
    expect(button('Helpful').getAttribute('aria-pressed')).toBe('true');
    expect(container.textContent).toContain('Verified · 1 source');
  });
});
