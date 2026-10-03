"use client";

import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { Button } from '@/components/ui/button';
import { RichContent } from './rich-content';
import type { Attempt, Presentation } from '@/lib/learning-workflows';
import styles from './quiz.module.css';

export function AssessmentCard({ item, attempt, busy, onAnswer, onHint, onChallenge, onCreateRepairNote, onOpenSource }: {
  item: Presentation; attempt?: Attempt; busy: boolean;
  onAnswer: (response: { response: string; selectedIds: string[]; outcome: 'answer' | 'dont_know' | 'skip'; externalHelp?: boolean }) => void;
  onHint: () => void; onChallenge: (reason: string) => void; onCreateRepairNote?: (attemptId: string) => void; onOpenSource?: (source: { spanId: string; versionId?: string; title?: string }) => void;
}) {
  const reduceMotion = useAppReducedMotion();
  const [draft] = useState<{response?: string; selected?: string[]}>(() => { try { return JSON.parse(localStorage.getItem(`quiz-draft:${item.id}`) || '{}'); } catch { return {}; } });
  const [response, setResponse] = useState(draft.response || '');
  const [selected, setSelected] = useState<string[]>(draft.selected || []);
  const [reason, setReason] = useState('');
  const [challenging, setChallenging] = useState(false);
  const [externalHelp, setExternalHelp] = useState(false);
  function save(next: string, choices: string[]) {
    setResponse(next); setSelected(choices);
    try { localStorage.setItem(`quiz-draft:${item.id}`, JSON.stringify({ response: next, selected: choices })); } catch { /* Draft remains in memory. */ }
  }
  return <motion.article className={styles.card} aria-label="Quiz question" initial={reduceMotion ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: 'easeOut' }}>
    <span className={styles.meta}>{item.difficulty} · {item.kind === 'multiple' ? 'Select all correct answers · exact match scoring' : item.kind === 'short' ? 'Explain your reasoning' : 'Select one answer'}</span>
    {item.questionPlan && <p className={styles.meta}>Practice objective: {item.questionPlan.objective.replaceAll('_', ' ')}</p>}
    <RichContent body={item.stem} />
    {item.sources?.length ? <div className={styles.sourceChips} aria-label="Question sources">{item.sources.map(source => <Button key={source.spanId} type="button" size="sm" variant="outline" onClick={() => onOpenSource?.(source)}>{source.spanId.startsWith('quiz-context:') ? source.title : `${source.title} · Page ${source.pageIndex + 1}`}</Button>)}</div> : null}
    <fieldset disabled={busy || !!attempt} className={styles.responses}>
      <legend className="sr-only">Your answer</legend>
      {item.kind === 'short' ? <textarea aria-label="Your reasoning" rows={5} value={response} onChange={e => save(e.target.value, selected)} maxLength={6000} placeholder="Explain how you reached your answer…" /> : item.options.map(option => <label key={option.id} className={styles.option}>
        <input type={item.kind === 'single' ? 'radio' : 'checkbox'} name={`answer-${item.id}`} checked={(attempt?.selectedIds || selected).includes(option.id)} onChange={() => save(response, item.kind === 'single' ? [option.id] : selected.includes(option.id) ? selected.filter(id => id !== option.id) : [...selected, option.id])} />
        <RichContent body={option.label} />
      </label>)}
    </fieldset>
    <AnimatePresence initial={false}>{item.hints.map((hint, i) => <motion.div className={styles.hint} key={i} initial={reduceMotion ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}><strong>Hint {i + 1}</strong><RichContent body={hint} /></motion.div>)}</AnimatePresence>
    {!attempt ? <div className={styles.actions}>
      <label><input type="checkbox" checked={externalHelp} onChange={event => setExternalHelp(event.target.checked)} disabled={busy} /> I used help outside this quiz</label>
      <Button disabled={busy || (item.kind === 'short' ? !response.trim() : !selected.length)} onClick={() => onAnswer({ response, selectedIds: selected, outcome: 'answer', externalHelp })}>Check answer</Button>
      <Button variant="outline" disabled={busy} onClick={() => onAnswer({ response: '', selectedIds: [], outcome: 'dont_know' })}>I don’t know</Button>
      <Button variant="ghost" disabled={busy || item.hints.length >= 3} onClick={onHint}>Hint</Button>
      <Button variant="ghost" disabled={busy} onClick={() => onAnswer({ response: '', selectedIds: [], outcome: 'skip' })}>Skip</Button>
    </div> : <section className={styles.feedback} aria-label="Answer feedback">
      <h3>{attempt.status === 'contested' ? 'Awaiting question review' : attempt.status === 'invalidated' ? 'Question excluded' : attempt.status === 'uncertain' ? 'Needs clarification' : attempt.status === 'skipped' ? 'Skipped' : attempt.score === 1 ? 'Correct' : attempt.score === 0 ? 'Another look' : 'Partly correct'}</h3>
      {attempt.assisted && <p className={styles.meta}>Answered with help</p>}
      <RichContent body={attempt.feedback} />
      <details open><summary>Reasoning</summary><RichContent body={attempt.solution} /></details>
      {attempt.conceptState && <p className={styles.meta}>Concept evidence: {attempt.conceptState.replaceAll('_', ' ')} · Not a calibrated mastery estimate</p>}
      {attempt && onCreateRepairNote ? <Button variant="outline" disabled={busy} onClick={() => onCreateRepairNote(attempt.id)}>Create repair note</Button> : null}<Button variant="ghost" onClick={() => setChallenging(!challenging)}>Flag question or feedback</Button>
      {challenging && <div><textarea aria-label="Why is this question or feedback unclear?" value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} /><Button disabled={busy || reason.trim().length < 5} onClick={() => { onChallenge(reason); setChallenging(false); }}>Submit for review</Button></div>}
    </section>}
  </motion.article>;
}
