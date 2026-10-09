import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AssessmentCard } from '@/components/assessment-card';
import type { Attempt, Presentation } from '@/lib/learning-workflows';
import '@/app/globals.css';

const params = new URLSearchParams(window.location.search);
document.documentElement.dataset.theme = params.get('theme') || 'dark';
document.documentElement.classList.toggle('dark', document.documentElement.dataset.theme === 'dark');
const item: Presentation = { id: 'synthetic-visual-question', quizId: 'visual', concept_id: 'newton',
  kind: params.get('kind') === 'short' ? 'short' : params.get('kind') === 'multiple' ? 'multiple' : 'single',
  stem: params.get('math') === 'long' ? 'Explain which terms determine the net force.\n\n$$F_{net}=m(a_1+a_2+a_3+a_4+a_5+a_6+a_7+a_8+a_9+a_{10}+a_{11}+a_{12})$$' : 'A cart is moving to the right at a **constant velocity**. A student says: “The net force must point to the right because that is the direction of motion.”\n\nWhich explanation best evaluates this claim?',
  options: [{ id: 'a', label: 'The claim is correct: motion requires a continuous net force in the same direction.' },
    { id: 'b', label: 'The claim is incorrect: constant velocity means zero acceleration, so the net force is zero.' },
    { id: 'c', label: 'The net force points left because forces always oppose an object’s motion.' }],
  hints: [], attemptId: null, difficulty: 'stretch', hintCount: 2, rationaleRequested: true,
  feedbackDeferred: params.get('state') === 'exam',
  questionPlan: { objective: 'predict', capability: 'explain', reason_codes: [], public_objective: 'Connect velocity, acceleration, and net force.' },
  sources: [{ spanId: 'synthetic-physics', title: 'Newton’s laws · synthetic reference', pageIndex: 2, text: 'Net force is mass times acceleration.' }] };
function Preview() {
  const [attempt, setAttempt] = useState<Attempt | undefined>(params.get('state') === 'feedback' ? {
    id: 'synthetic-response', presentationId: item.id, conceptId: 'newton', response: 'Velocity is constant, so acceleration is zero.', selectedIds: ['b'], score: 1, feedback: 'You connected constant velocity to zero acceleration.', solution: 'Newton’s second law gives $F_{net}=ma$. With zero acceleration, the net force is zero. Individual forces can still act and balance.', correctIds: ['b'], status: 'evaluated', outcome: 'answer', assisted: false, conceptState: null,
    feedbackDetails: { demonstrated: [{ criterionId: 'principle', description: 'Connected constant velocity to acceleration.', spans: [{ start: 0, end: 47, quote: 'Velocity is constant, so acceleration is zero.' }] }], gaps: [], explanation: 'Your reasoning identifies the governing principle.', nextAction: 'continue' },
  } : undefined);
  return <main style={{ maxWidth: 820, margin: 'auto', padding: '24px 12px 48px' }}><p style={{ color: 'var(--muted-foreground)', fontSize: 14 }}>Physics · Question 2 of 5</p><AssessmentCard item={item} attempt={attempt} busy={params.get('state') === 'checking'}
    onAnswer={answer => setAttempt({ id: 'synthetic-response', presentationId: item.id, conceptId: 'newton', response: answer.response, selectedIds: answer.selectedIds, score: null, feedback: 'Synthetic preview answer saved.', solution: '', correctIds: [], status: 'submitted', outcome: answer.outcome, assisted: Boolean(answer.externalHelp), conceptState: null })}
    onHint={() => undefined} onChallenge={() => undefined}/></main>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
