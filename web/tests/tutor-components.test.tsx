import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExerciseCard } from '@/components/exercise-card';
import { RichContent } from '@/components/rich-content';
import { ChatComposer } from '@/components/chat-composer';
import { MessageActionBar, VerificationBadge } from '@/components/message-action-bar';

const { createWorkspaceNote, deleteWorkspaceNote } = vi.hoisted(() => ({ createWorkspaceNote: vi.fn(async () => ({ id: 'note-1', revision: 1 })), deleteWorkspaceNote: vi.fn(async () => undefined) }));
vi.mock('@/lib/api', () => ({ learningApi: { searchWorkspaceNotes: vi.fn(async () => ({ notes: [] })), createWorkspaceNote, deleteWorkspaceNote } }));
vi.mock('@/lib/use-app-reduced-motion', () => ({ useAppReducedMotion: () => true }));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container); vi.clearAllMocks(); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
function render(node: ReactNode) { act(() => root.render(node)); }
function button(label: string) { const result = [...container.querySelectorAll('button')].find(item => item.getAttribute('aria-label') === label || item.textContent?.trim() === label); if (!result) throw new Error(`Missing button: ${label}`); return result; }
function click(element: HTMLElement) { act(() => element.click()); }
function typeInto(input: HTMLInputElement, value: string) { act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); }); }

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
