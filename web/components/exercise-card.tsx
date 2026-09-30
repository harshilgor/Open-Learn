"use client";

import { useId, useState } from 'react';
import { Check, Lightbulb, RotateCcw } from 'lucide-react';
import { checkExerciseAnswer, type Exercise } from '@/lib/tutor-format';
import styles from './exercise-card.module.css';

export function ExerciseCard({ exercise, onResolved }: { exercise: Exercise; onResolved?: (id: string) => void }) {
  const inputId = useId();
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<'wrong' | 'correct' | 'revealed' | null>(null);
  const [showHint, setShowHint] = useState(false);
  const resolved = result === 'correct' || result === 'revealed';
  return <section className={styles.card} aria-label="Practice question">
    <div className={styles.label}>Practice question</div>
    <p className={styles.prompt}>{exercise.prompt}</p>
    <form onSubmit={event => { event.preventDefault(); if (!answer.trim() || resolved) return; const correct = checkExerciseAnswer(exercise, answer); setResult(correct ? 'correct' : 'wrong'); if (correct) onResolved?.(exercise.id); }}>
      <label htmlFor={inputId}>Your answer</label>
      <div className={styles.answerRow}><input id={inputId} type="text" inputMode={exercise.type === 'numeric' ? 'decimal' : 'text'} value={answer} disabled={resolved} onChange={event => { setAnswer(event.target.value); if (result === 'wrong') setResult(null); }} /><button type="submit" disabled={!answer.trim() || resolved}>Check</button></div>
    </form>
    {result === 'wrong' ? <p className={styles.wrong} role="status">Not quite. Try again or use the hint.</p> : null}
    {showHint && exercise.hint && !resolved ? <p className={styles.hint} role="status"><Lightbulb size={14}/>{exercise.hint}</p> : null}
    {!resolved ? <div className={styles.actions}>{exercise.hint ? <button type="button" onClick={() => setShowHint(true)} disabled={showHint}><Lightbulb size={14}/>Hint</button> : null}<button type="button" onClick={() => { setResult('revealed'); onResolved?.(exercise.id); }}><RotateCcw size={14}/>Reveal answer</button></div> : <div className={styles.solution} role="status"><strong><Check size={15}/>{result === 'correct' ? 'Correct' : `Answer: ${exercise.answer}`}</strong><p>{exercise.explanation}</p></div>}
  </section>;
}
