"use client";

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { RichContent } from './rich-content';
import type { Attempt, Presentation } from '@/lib/learning-workflows';
import styles from './quiz.module.css';

type Draft = { response?: string; selected?: string[]; externalHelp?: boolean };
export function AnswerFeedback({ attempt }: { attempt: Attempt }) {
  const saved = attempt.status === 'submitted';
  const title = saved ? 'Answer saved' : attempt.status === 'contested' ? 'Awaiting question review' : attempt.status === 'invalidated' ? 'Question excluded' : attempt.status === 'uncertain' ? 'A closer check' : attempt.status === 'skipped' ? 'Skipped' : attempt.score === 1 ? 'Correct' : attempt.score === 0 ? 'Review the reasoning' : 'Partly correct';
  return <section className={styles.feedback} aria-label="Answer feedback">
    <h3>{title}</h3>
    {attempt.assisted && <p className={styles.meta}>Answered with help</p>}
    <RichContent body={saved ? 'Your answer is saved. Feedback is available when the quiz ends.' : attempt.feedback} />
    {!saved && attempt.uiVersion !== 1 && attempt.status !== 'contested' && attempt.feedbackDetails ? <div className={styles.feedbackGrid}>
      {attempt.feedbackDetails.demonstrated.length > 0 && <div><h4>What you demonstrated</h4><ul>{attempt.feedbackDetails.demonstrated.map(part => <li key={part.criterionId}><RichContent body={part.description} />{part.spans.map((span, index) => <blockquote key={index}>{span.quote}</blockquote>)}</li>)}</ul></div>}
      {attempt.feedbackDetails.gaps.length > 0 && <div><h4>What to work on</h4><ul>{attempt.feedbackDetails.gaps.map(part => <li key={part.criterionId}><RichContent body={part.description} /></li>)}</ul></div>}
    </div> : null}
    {!saved && attempt.solution && <details><summary>See the worked explanation</summary><RichContent body={attempt.solution} /></details>}
    {!saved && attempt.conceptState && <p className={styles.meta}>Your learning evidence has been updated. This practice score is not a calibrated mastery estimate.</p>}
  </section>;
}

export function AssessmentCard({ item, attempt, busy, onAnswer, onHint, onChallenge, onCreateRepairNote, onOpenSource }: {
  item: Presentation; attempt?: Attempt; busy: boolean;
  onAnswer: (response: { response: string; selectedIds: string[]; outcome: 'answer' | 'dont_know' | 'skip'; externalHelp?: boolean }) => void;
  onHint: () => void; onChallenge: (reason: string) => void; onCreateRepairNote?: (attemptId: string) => void; onOpenSource?: (source: { spanId: string; versionId?: string; title?: string }) => void;
}) {
  const [draft] = useState<Draft>(() => { try { return JSON.parse(localStorage.getItem(`quiz-draft:${item.id}`) || '{}'); } catch { return {}; } });
  const [response, setResponse] = useState(draft.response || '');
  const [selected, setSelected] = useState<string[]>(draft.selected || []);
  const [externalHelp, setExternalHelp] = useState(draft.externalHelp || false);
  const [reason, setReason] = useState('');
  const [challenging, setChallenging] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [item.id]);
  function save(next: string, choices: string[], help = externalHelp) {
    setResponse(next); setSelected(choices); setExternalHelp(help);
    try { localStorage.setItem(`quiz-draft:${item.id}`, JSON.stringify({ response: next, selected: choices, externalHelp: help })); } catch { /* In-memory draft remains available. */ }
  }
  const answered = Boolean(attempt);
  return <article className={`${styles.card} ${styles.questionCard}`} aria-label="Quiz question" aria-busy={busy}>
    <div className={styles.questionHeading}><span className={styles.meta}>{item.kind === 'multiple' ? 'Select every correct answer · exact match' : item.kind === 'short' ? 'Explain your reasoning' : 'Choose one answer'}</span>{item.questionPlan?.parent_attempt_id && <span className={styles.followup}>A focused follow-up</span>}</div>
    <h2 ref={heading} tabIndex={-1} className={styles.srOnly}>Question</h2>
    <div className={styles.questionStem}><RichContent body={item.stem} /></div>
    {item.uiVersion !== 1 && item.questionPlan?.public_objective && <p className={styles.questionPurpose}>{item.questionPlan.public_objective}</p>}
    <fieldset disabled={busy || answered} className={styles.responses}>
      <legend className={styles.srOnly}>Your answer</legend>
      {item.kind === 'short' ? <label className={styles.writtenLabel}>Your reasoning<textarea rows={5} value={attempt?.response ?? response} onChange={e => save(e.target.value, selected)} maxLength={6000} placeholder="Connect the principle to this situation…" /></label> : item.options.map((option, index) => <label key={option.id} className={styles.option}>
        <input type={item.kind === 'single' ? 'radio' : 'checkbox'} name={`answer-${item.id}`} checked={(attempt?.selectedIds || selected).includes(option.id)} onChange={() => save(response, item.kind === 'single' ? [option.id] : selected.includes(option.id) ? selected.filter(id => id !== option.id) : [...selected, option.id])} />
        <span className={styles.optionLetter} aria-hidden="true">{String.fromCharCode(65 + index)}</span><RichContent body={option.label} />
      </label>)}
      {item.kind !== 'short' && item.rationaleRequested && <label className={styles.writtenLabel}>Explain your choice <span className={styles.meta}>(optional; used for a focused follow-up)</span><textarea rows={3} value={attempt?.response ?? response} onChange={e => save(e.target.value, selected)} maxLength={6000} placeholder="Which principle led you to this answer?" /></label>}
    </fieldset>
    {item.hints.map((hint, index) => <div className={styles.hint} key={index}><strong>Hint {index + 1}</strong><RichContent body={hint} /></div>)}
    {!attempt ? <>
      <label className={styles.helpLabel}><input type="checkbox" checked={externalHelp} onChange={e => save(response, selected, e.target.checked)} disabled={busy} /> I used help outside this quiz</label>
      <div className={styles.answerActions}><Button disabled={busy || (item.kind === 'short' ? !response.trim() : !selected.length)} onClick={() => onAnswer({ response, selectedIds: selected, outcome: 'answer', externalHelp })}>{busy ? 'Checking your answer…' : item.feedbackDeferred ? 'Submit answer' : 'Check answer'}</Button><div className={styles.secondaryActions}>
        {!item.feedbackDeferred && <Button variant="outline" disabled={busy || item.hints.length >= (item.hintCount ?? 3)} onClick={onHint}>Hint</Button>}
        <Button variant="ghost" disabled={busy} onClick={() => onAnswer({ response: '', selectedIds: [], outcome: 'dont_know' })}>I don’t know</Button>
        <Button variant="ghost" disabled={busy} onClick={() => onAnswer({ response: '', selectedIds: [], outcome: 'skip' })}>Skip</Button>
      </div></div>
    </> : <><AnswerFeedback attempt={attempt}/><div className={styles.secondaryActions}>{attempt.status !== 'submitted' && onCreateRepairNote && <Button variant="outline" disabled={busy} onClick={() => onCreateRepairNote(attempt.id)}>Create repair note</Button>}<Button variant="ghost" onClick={() => setChallenging(value => !value)} aria-expanded={challenging}>Flag question or feedback</Button></div></>}
    {challenging && <div className={styles.challengeBox}><label>What seems unclear or incorrect?<textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={2000}/></label><Button disabled={busy || reason.trim().length < 5} onClick={() => { onChallenge(reason); setChallenging(false); }}>Submit for review</Button></div>}
    {item.sources?.length ? <details className={styles.sourcesDisclosure}><summary>Reference material · {item.sources.length}</summary><div className={styles.sourceChips}>{item.sources.map(source => <Button key={source.spanId} type="button" size="sm" variant="outline" onClick={() => onOpenSource?.(source)}>{source.spanId.startsWith('quiz-context:') ? source.title : `${source.title} · Page ${source.pageIndex + 1}`}</Button>)}</div></details> : null}
  </article>;
}
