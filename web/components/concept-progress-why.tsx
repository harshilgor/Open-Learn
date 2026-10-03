"use client";

import { useEffect, useState } from 'react';
import { learningApi, type ConceptStateExplanation, type TimelineEntry } from '@/lib/api';
import styles from './learn-chat.module.css';

/** Compact ordinal Progress / Why surface — never percentages. */
export function ConceptProgressWhy({ conceptId, enabled = true }: { conceptId?: string | null; enabled?: boolean }) {
  const [explanation, setExplanation] = useState<ConceptStateExplanation | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [capabilities, setCapabilities] = useState<Awaited<ReturnType<typeof learningApi.getCapabilityState>> | null>(null);
  const [history, setHistory] = useState<Awaited<ReturnType<typeof learningApi.getEvidenceHistory>> | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!enabled || !conceptId) return;
    let active = true;
    void (async () => {
      try {
        const [why, page, ledger, shared] = await Promise.all([
          learningApi.getConceptExplanation(conceptId),
          learningApi.getLearnerTimeline({ limit: 8 }),
          learningApi.getEvidenceHistory(conceptId),
          learningApi.getCapabilityState(conceptId),
        ]);
        if (!active) return;
        setExplanation(why);
        setHistory(ledger);
        setCapabilities(shared);
        setTimeline(page.entries.filter(entry => !entry.conceptId || entry.conceptId === conceptId).slice(0, 5));
        setError('');
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Progress could not be loaded.');
      }
    })();
    return () => { active = false; };
  }, [conceptId, enabled]);

  if (!conceptId || !enabled) return null;
  if (error) return <p className={styles.hint} role="status">{error}</p>;
  if (!explanation) return null;

  const status = explanation.state.status;
  const dueReason = explanation.review?.dueReason;
  return (
    <details className={styles.sources}>
      <summary>Progress · Why this standing</summary>
      <p className={styles.hint}>
        Current standing: <strong>{status}</strong>
        {dueReason ? ` · Next review: ${dueReason}` : null}
      </p>
      {capabilities?.states.length ? <section aria-label="Measured capabilities">
        <h4>What you have practiced</h4>
        <ul className={styles.hint}>{capabilities.states.map(state => <li key={state.capability}>
          <strong>{state.capability}</strong>: {state.state.replaceAll('_', ' ')} · {state.evidenceStrength.replaceAll('_', ' ')} evidence · {state.retention.replaceAll('_', ' ')}
          <p>{state.reasonCodes.map(reason => reason.replaceAll('_', ' ')).join(' · ')}</p>
        </li>)}</ul>
      </section> : <p className={styles.hint}>A fresh independent check will establish capability evidence.</p>}
      {explanation.admittedEvidence.length ? (
        <ul className={styles.hint}>
          {explanation.admittedEvidence.slice(0, 4).map(item => (
            <li key={item.id}>{item.condition} {item.outcome} · {item.kind}</li>
          ))}
        </ul>
      ) : <p className={styles.hint}>No admitted evidence yet for this concept.</p>}
      {history?.entries.length ? <section aria-label="Evidence history">
        <h4>What this is based on</h4>
        <ul className={styles.hint}>{history.entries.slice(-20).reverse().map(entry => <li key={entry.id}>
          {entry.category.replaceAll('_', ' ')} · {entry.eventType.toLowerCase().replaceAll('_', ' ')} · {new Date(entry.occurredAt).toLocaleDateString()}
          {entry.reasons.length ? ` · ${entry.reasons.join(', ').replaceAll('_', ' ')}` : null}
          {entry.question ? <details><summary>View question</summary><p>{entry.question.stem}</p></details> : null}
        </li>)}</ul>
      </section> : null}
      {timeline.length ? (
        <>
          <p className={styles.hint}>Recent activity</p>
          <ul className={styles.hint}>
            {timeline.map(entry => <li key={entry.id}>{entry.summary}</li>)}
          </ul>
        </>
      ) : null}
    </details>
  );
}
