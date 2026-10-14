import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Attempt, Presentation, Quiz } from '@/lib/learning-workflows';
import type { FlashcardReview } from '@/lib/flashcards-client';
import { REVIEW_OPEN_EVENT, WORKSPACE_QUIZ_OPEN_EVENT } from '@/lib/workspace-events';

const mocks = vi.hoisted(() => ({ request: vi.fn(), getQuiz: vi.fn(), workflow: vi.fn(), review: vi.fn(), summary: vi.fn(), session: vi.fn(), rate: vi.fn(), makeCards: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request, learningApi: { getReviewDashboard: mocks.review, getTransitionGap: vi.fn().mockResolvedValue({}), getStudyNote: vi.fn().mockResolvedValue(null) } }));
vi.mock('@/lib/learning-workflows', () => ({ getQuiz: mocks.getQuiz, workflow: mocks.workflow, waitForJob: vi.fn(), cancelWorkflow: vi.fn() }));
vi.mock('@/lib/flashcards-client', () => ({ flashcardsApi: { summary: mocks.summary, session: mocks.session, rate: mocks.rate, list: vi.fn().mockResolvedValue({ decks: [], nextOffset: null }) } }));
vi.mock('@/lib/voice/client', () => ({ reportVoiceFocus: vi.fn(), VOICE_REFRESH: 'voice-refresh' }));
vi.mock('@/lib/use-app-reduced-motion', () => ({ useAppReducedMotion: () => true }));
vi.mock('@/components/rich-content', () => ({ RichContent: ({ body }: { body: string }) => <div>{body}</div> }));
vi.mock('@/components/hypothesis-panel', () => ({ HypothesisPanel: () => null }));
vi.mock('@/components/mode-transition-card', () => ({ ModeTransitionCard: () => null }));
vi.mock('@/components/flashcard-image', () => ({ FlashcardImage: () => null, NewFlashcard: () => null }));
vi.mock('@/components/flashcard-create', () => ({ MakeFlashcards: (props: { label?: string; sourceRefs?: unknown[] }) => { mocks.makeCards(props); return <button type="button">{props.label}</button>; } }));

const { QuizWorkspace } = await import('@/components/quiz-workspace');
const { FlashcardWorkspace } = await import('@/components/flashcard-workspace');
const { PracticeOverview } = await import('@/components/practice-overview');

const item: Presentation = { id: 'p1', quizId: 'q1', concept_id: 'force', kind: 'single', stem: 'What is the net force at constant velocity?', options: [{ id: 'a', label: 'Zero' }, { id: 'b', label: 'Forward' }, { id: 'c', label: 'Backward' }], hints: [], attemptId: null, difficulty: 'standard' };
const summary: Quiz['summary'] = { score: null, evaluated: 0, attempted: 2, total: 8, assisted: 0, skipped: 0, dontKnow: 0, independentCorrect: 0, retries: 0, contested: 0 };
const quiz: Quiz = { id: 'q1', sessionId: 's1', title: 'Forces', revision: 4, status: 'in_progress', count: 8, mode: 'topic_drill', modeConfig: {}, deadlineAt: null, remainingSeconds: null, current: item, attempts: [], summary };
const attempt = (id: string, score: number | null, extra: Partial<Attempt> = {}): Attempt => ({ id, presentationId: `p-${id}`, conceptId: 'force', response: '', selectedIds: [], score, feedback: '', solution: '', correctIds: [], status: 'evaluated', outcome: 'answer', assisted: false, conceptState: null, question: `Question ${id}`, ...extra });

let root: Root, container: HTMLDivElement;
const press = (key: string, target: EventTarget = document.body, code = key) => act(async () => { target.dispatchEvent(new KeyboardEvent('keydown', { key, code, bubbles: true, cancelable: true })); });
const button = (text: string) => [...container.querySelectorAll('button')].find(node => node.textContent?.includes(text));
const settle = () => act(async () => { for (let i = 0; i < 3; i++) await new Promise(resolve => setTimeout(resolve, 0)); });

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); localStorage.clear();
  mocks.request.mockImplementation(async (path: string) => path.startsWith('/v1/quiz-capabilities') ? { version2: false } : { quizzes: [], nextCursor: null });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

describe('quiz keyboard shortcuts', () => {
  async function renderQuiz(value: Quiz) {
    mocks.getQuiz.mockResolvedValue(value);
    await act(async () => root.render(<QuizWorkspace sessionId="s1" quizId={value.id}/>));
    await settle();
  }
  it('shows slim progress and picks options with number keys, then checks with Enter', async () => {
    await renderQuiz(quiz);
    expect(container.textContent).toContain('Question 3 of 8');
    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('2');
    expect(container.textContent).toContain('to choose');
    await press('2');
    const radios = container.querySelectorAll<HTMLInputElement>('input[type="radio"]');
    expect(radios[1].checked).toBe(true);
    await press('9');
    expect(radios[1].checked).toBe(true);
    mocks.workflow.mockResolvedValue({ quizId: 'q1' });
    await press('Enter', radios[1]);
    expect(mocks.workflow).toHaveBeenCalledWith('/quizzes/q1/attempts', expect.objectContaining({ selectedIds: ['b'], outcome: 'answer', presentationId: 'p1', expectedRevision: 4 }), expect.any(String));
  });
  it('leaves typing fields alone', async () => {
    await renderQuiz({ ...quiz, current: { ...item, rationaleRequested: true } });
    const textarea = container.querySelector('textarea')!;
    await press('1', textarea); await press('Enter', textarea);
    expect([...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')].some(input => input.checked)).toBe(false);
    expect(mocks.workflow).not.toHaveBeenCalled();
  });
  it('moves to the next question with Enter once answered', async () => {
    await renderQuiz({ ...quiz, current: { ...item, attemptId: 'a1' }, attempts: [attempt('a1', 1, { presentationId: 'p1', selectedIds: ['a'] })] });
    expect(container.textContent).toContain('Question 2 of 8');
    mocks.workflow.mockResolvedValue({ quizId: 'q1' });
    await press('Enter');
    expect(mocks.workflow).toHaveBeenCalledWith('/quizzes/q1/next', { expectedRevision: 4 }, expect.any(String));
  });
  it('ignores shortcuts with modifier keys', async () => {
    await renderQuiz(quiz);
    await act(async () => { document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '1', ctrlKey: true, bubbles: true, cancelable: true })); });
    expect(container.querySelector<HTMLInputElement>('input[type="radio"]')!.checked).toBe(false);
  });
});

describe('quiz results', () => {
  it('lists missed questions and offers weak-spot practice and flashcards from mistakes', async () => {
    const attempts = [attempt('a1', 1), attempt('a2', 0, { conceptId: 'friction' }), attempt('a3', null, { outcome: 'skip', status: 'skipped', conceptId: 'friction' }), attempt('a4', 0, { status: 'contested' })];
    mocks.getQuiz.mockResolvedValue({ ...quiz, status: 'completed', current: null, attempts, summary: { ...summary, score: 50, evaluated: 2, attempted: 4 } });
    await act(async () => root.render(<QuizWorkspace sessionId="s1" quizId="q1"/>));
    await settle();
    expect(container.textContent).toContain('50%');
    expect(container.textContent).toContain('Questions to revisit');
    const list = container.querySelector('ol')!;
    expect(list.textContent).toContain('Question a2');
    expect(list.textContent).toContain('Skipped');
    expect(list.textContent).not.toContain('Question a1');
    expect(list.textContent).not.toContain('Question a4');
    expect(mocks.makeCards).toHaveBeenCalledWith(expect.objectContaining({ label: 'Make flashcards from mistakes', origin: 'quiz', sourceRefs: [{ kind: 'quiz_attempt', id: 'a2', revision: 1 }, { kind: 'quiz_attempt', id: 'a3', revision: 1 }] }));
    const opened = vi.fn();
    window.addEventListener(REVIEW_OPEN_EVENT, opened);
    act(() => button('Practice weak spots')!.click());
    window.removeEventListener(REVIEW_OPEN_EVENT, opened);
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toEqual({ conceptId: 'friction' });
    expect(button('New quiz')).toBeTruthy();
  });
});

describe('flashcard review shortcuts', () => {
  const review: FlashcardReview = { id: 'r1', revision: 1, status: 'active', cursor: 1, total: 4, practice: false, current: { cardId: 'c1', deckId: 'd1', versionId: 'v1', attemptId: 'at1', type: 'qa', prompt: 'What encloses a cell?', revealed: false } };
  it('flips with Space and rates with number keys shown on the buttons', async () => {
    mocks.session.mockResolvedValue(review);
    mocks.summary.mockResolvedValue({ dueCount: 0, courses: {}, sessions: [] });
    await act(async () => root.render(<FlashcardWorkspace launch={{ reviewSessionId: 'r1', view: 'review' }}/>));
    await settle();
    expect(container.textContent).toContain('Card 2 of 4');
    expect(container.textContent).toContain('to show the answer');
    mocks.rate.mockResolvedValueOnce({ ...review, revision: 2, current: { ...review.current!, revealed: true, answer: 'Membrane' } });
    await press(' ', document.body, 'Space');
    expect(mocks.rate).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'r1' }), expect.objectContaining({ action: 'reveal' }));
    expect(container.textContent).toContain('Membrane');
    const good = button('Good')!;
    expect(good.getAttribute('aria-keyshortcuts')).toBe('3');
    expect(good.querySelector('kbd')?.textContent).toBe('3');
    mocks.rate.mockResolvedValueOnce({ ...review, revision: 3, cursor: 2, current: null, status: 'completed' });
    await press('3');
    expect(mocks.rate).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ action: 'rate', rating: 'good' }));
  });
});

describe('practice overview', () => {
  it('shows class quizzes not already under Continue and a weak-spots row', async () => {
    mocks.request.mockResolvedValue({ quizzes: [
      { id: 'q-open', title: 'Krebs cycle', sessionId: 's1', origin: 'in_class', status: 'ready', count: 8, attempted: 3, score: null, assisted: 0, skipped: 0, dontKnow: 0, contested: 0 },
      { id: 'q-class', title: 'Lecture 4 check', sessionId: 's2', origin: 'in_class', status: 'completed', count: 5, attempted: 5, score: 60, assisted: 0, skipped: 0, dontKnow: 0, contested: 0 },
      { id: 'q-done', title: 'Glycolysis', sessionId: 's1', origin: 'ask', status: 'completed', count: 5, attempted: 5, score: 80, assisted: 0, skipped: 0, dontKnow: 0, contested: 0 },
    ] });
    mocks.summary.mockResolvedValue({ dueCount: 0, courses: {}, sessions: [] });
    mocks.review.mockResolvedValue({ dueCount: 0, weakCount: 2, newCount: 0, totalConcepts: 4, estimatedMinutes: 5, streakDays: 0, preparing: false });
    await act(async () => root.render(<PracticeOverview/>));
    await settle();
    const classes = container.querySelector('[aria-labelledby="practice-class"]')!;
    expect(classes.textContent).toContain('From your classes');
    expect(classes.textContent).toContain('Lecture 4 check');
    expect(classes.textContent).toContain('Score 60%');
    expect(classes.textContent).not.toContain('Krebs cycle');
    expect(container.querySelector('[aria-labelledby="practice-continue"]')!.textContent).toContain('Krebs cycle');
    const opened = vi.fn();
    window.addEventListener(WORKSPACE_QUIZ_OPEN_EVENT, opened);
    act(() => [...classes.querySelectorAll('button')].find(node => node.textContent?.includes('Lecture 4 check'))!.click());
    window.removeEventListener(WORKSPACE_QUIZ_OPEN_EVENT, opened);
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toMatchObject({ quizId: 'q-class', sessionId: 's2' });
    const reviewOpened = vi.fn();
    window.addEventListener(REVIEW_OPEN_EVENT, reviewOpened);
    act(() => button('2 concepts need another look')!.click());
    window.removeEventListener(REVIEW_OPEN_EVENT, reviewOpened);
    expect(reviewOpened).toHaveBeenCalledTimes(1);
  });
  it('hides both additions when there is nothing to show', async () => {
    mocks.request.mockResolvedValue({ quizzes: [] });
    mocks.summary.mockResolvedValue({ dueCount: 0, courses: {}, sessions: [] });
    mocks.review.mockResolvedValue({ dueCount: 0, weakCount: 0, newCount: 0, totalConcepts: 0, estimatedMinutes: 0, streakDays: 0, preparing: false });
    await act(async () => root.render(<PracticeOverview/>));
    await settle();
    expect(container.textContent).not.toContain('From your classes');
    expect(container.textContent).not.toContain('Weak spots');
  });
});
