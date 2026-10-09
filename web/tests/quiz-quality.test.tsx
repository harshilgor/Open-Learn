import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AssessmentCard, AnswerFeedback } from '@/components/assessment-card';
import type { Attempt, Presentation } from '@/lib/learning-workflows';

vi.mock('@/components/rich-content', () => ({ RichContent: ({ body }: { body: string }) => <div>{body}</div> }));
let root: Root;
let container: HTMLDivElement;
const item: Presentation = { id: 'question', quizId: 'quiz', concept_id: 'force', kind: 'single', stem: 'A cart moves at constant speed. What is its net force?', options: [{ id: 'a', label: 'Zero' }, { id: 'b', label: 'Rightward' }], hints: [], attemptId: null, difficulty: 'standard', hintCount: 1, questionPlan: { objective: 'transfer_check', capability: 'explain', reason_codes: [], public_objective: 'Explain why the idea works.' } };
const attempt: Attempt = { id: 'attempt', presentationId: item.id, conceptId: 'force', response: '', selectedIds: ['a'], score: 1, feedback: 'The forces balance.', solution: 'Constant velocity implies zero net force.', correctIds: ['a'], status: 'evaluated', outcome: 'answer', assisted: false, conceptState: null };
beforeEach(() => { localStorage.clear(); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
function render(overrides: Partial<Presentation> = {}, result?: Attempt) {
  const onAnswer = vi.fn();
  act(() => root.render(<AssessmentCard item={{ ...item, ...overrides }} attempt={result} busy={false} onAnswer={onAnswer} onHint={vi.fn()} onChallenge={vi.fn()}/>));
  return onAnswer;
}
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>('button')].find(node => node.textContent === text)!; }

describe('quiz question experience', () => {
  it('shows the public purpose and focuses the question without policy jargon', () => {
    render();
    expect(container.textContent).toContain('Explain why the idea works.');
    expect(container.textContent).not.toContain('transfer_check');
    expect(document.activeElement?.textContent).toBe('Question');
  });
  it('keeps single-choice semantics and submits the selection', () => {
    const answer = render();
    act(() => container.querySelector<HTMLInputElement>('input[type="radio"]')!.click());
    act(() => button('Check answer').click());
    expect(answer).toHaveBeenCalledWith({ response: '', selectedIds: ['a'], outcome: 'answer', externalHelp: false });
  });
  it('restores selected options, reasoning and outside-help disclosure', () => {
    localStorage.setItem('quiz-draft:question', JSON.stringify({ response: 'The acceleration is zero.', selected: ['a'], externalHelp: true }));
    render({ rationaleRequested: true });
    expect(container.querySelector('textarea')?.value).toBe('The acceleration is zero.');
    expect(container.querySelector<HTMLInputElement>('input[type="radio"]')?.checked).toBe(true);
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
  });
  it('withholds exam hints and feedback even when sensitive fields are accidentally passed', () => {
    render({ feedbackDeferred: true }, { ...attempt, status: 'submitted' });
    expect(container.textContent).not.toContain(attempt.solution);
    expect(container.textContent).not.toContain('See the worked explanation');
    expect(container.textContent).toContain('Answer saved');
  });
  it('uses written and multiple-choice controls appropriately', () => {
    render({ kind: 'multiple' });
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);
    act(() => root.render(<AssessmentCard item={{ ...item, kind: 'short', options: [] }} busy={false} onAnswer={vi.fn()} onHint={vi.fn()} onChallenge={vi.fn()}/>));
    expect(container.querySelector('textarea')).toBeTruthy();
    expect(container.querySelector('input[type="radio"]')).toBeNull();
  });
  it('renders criterion feedback and keeps the full solution expandable', () => {
    act(() => root.render(<AnswerFeedback attempt={{ ...attempt, feedbackDetails: { demonstrated: [{ criterionId: 'force', description: 'Connected velocity to acceleration.', spans: [{ start: 0, end: 4, quote: 'zero' }] }], gaps: [], explanation: attempt.feedback, nextAction: 'continue' } }}/>));
    expect(container.textContent).toContain('What you demonstrated');
    expect(container.querySelector('details')?.open).toBe(false);
  });
});
