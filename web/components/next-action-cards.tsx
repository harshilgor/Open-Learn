"use client";

import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Sparkles, X } from 'lucide-react';
import { learningApi, type NextActionRecommendation, type RecommendationSet } from '@/lib/api';
import styles from './next-action-cards.module.css';

function suggestionLabel(item: NextActionRecommendation): string {
  const concept = item.conceptTitle?.trim();
  if (item.pedagogicalAction === 'repair') return concept ? `Try a different approach to ${concept}` : 'Try a different explanation';
  if (item.pedagogicalAction === 'check') return concept ? `Check ${concept}` : 'Check your understanding';
  if (item.actionKind === 'learn') return concept ? `Continue with ${concept}` : (item.title || 'Continue learning');
  if (item.actionKind === 'ask') return concept ? `Ask about ${concept}` : (item.title || 'Ask a follow-up');
  if (item.actionKind === 'quiz') return concept ? `Quiz yourself on ${concept}` : (item.title || 'Quiz this concept');
  if (item.actionKind === 'review') return concept ? `Review ${concept}` : (item.title || 'Review concepts');
  return item.title || 'Continue';
}

function recommendationFingerprint(sessionId: string, item: NextActionRecommendation): string {
  return [
    sessionId,
    item.conceptId || '',
    item.actionKind,
    item.pedagogicalAction || '',
    item.whyCode || '',
    item.context.journeyAction || '',
    [...item.evidenceIds].sort().join(','),
  ].join('|');
}

export function NextActionCards({ sessionId, enabled, refreshKey, onLearn, onAsk, onQuiz, onReview, onCheck }: {
  sessionId: string; enabled: boolean; refreshKey?: string | number;
  onLearn: (item?: NextActionRecommendation) => void | Promise<void>;
  onAsk: (item: NextActionRecommendation) => void | Promise<void>;
  onQuiz: (item?: NextActionRecommendation) => void | Promise<void>;
  onReview: (item?: NextActionRecommendation) => void | Promise<void>;
  onCheck: () => void;
}) {
  const [result, setResult] = useState<{ requestKey: string; set: RecommendationSet | null; repeated: boolean } | null>(null);
  const [dismissedFingerprint, setDismissedFingerprint] = useState<string | null>(null);
  const loaded = useRef<string | null>(null);
  const lastPresented = useRef<{ fingerprint: string; refreshKey: string } | null>(null);
  const requestKey = `${sessionId}:${refreshKey ?? ''}`;
  const refreshKeyValue = String(refreshKey ?? '');
  const currentSet = result?.requestKey === requestKey ? result.set : null;
  const primary = currentSet?.recommendations.find(item => item.isPrimary) ?? null;
  const fingerprint = primary ? recommendationFingerprint(sessionId, primary) : null;
  const recommendationSetId = currentSet?.id ?? null;
  const primaryId = primary?.id ?? null;
  const repeated = result?.requestKey === requestKey && result.repeated;
  const canSuggest = Boolean(enabled && currentSet && primary && primary.whyCode !== 'new_concept' && fingerprint !== dismissedFingerprint && !repeated);

  useEffect(() => {
    if (!enabled || loaded.current === requestKey) return;
    let active = true;
    void learningApi.getRecommendations(sessionId).then(next => {
      if (active) {
        const current = next.status === 'current' ? next : null;
        const nextPrimary = current?.recommendations.find(item => item.isPrimary) ?? null;
        const nextFingerprint = nextPrimary ? recommendationFingerprint(sessionId, nextPrimary) : null;
        const previous = lastPresented.current;
        const isRepeated = Boolean(nextFingerprint && previous?.fingerprint === nextFingerprint && previous.refreshKey !== refreshKeyValue);
        setResult({ requestKey, set: current, repeated: isRepeated });
        loaded.current = requestKey;
      }
    }).catch(() => {
      if (active) {
        setResult({ requestKey, set: null, repeated: false });
        loaded.current = requestKey;
      }
    });
    return () => { active = false; };
  }, [enabled, refreshKeyValue, requestKey, sessionId]);

  useEffect(() => {
    if (!canSuggest || !fingerprint || !recommendationSetId || !primaryId) return;
    lastPresented.current = { fingerprint, refreshKey: refreshKeyValue };
    void learningApi.recordRecommendationInteraction(
      primaryId,
      'impression',
      'local',
      `${recommendationSetId}:${primaryId}:impression`,
    ).catch(() => undefined);
  }, [canSuggest, fingerprint, primaryId, recommendationSetId, refreshKeyValue]);

  if (!canSuggest || !currentSet || !primary || !fingerprint) return null;
  const recommendation = primary;
  const recommendationKey = fingerprint;

  async function select() {
    setDismissedFingerprint(recommendationKey);
    void learningApi.recordRecommendationInteraction(recommendation.id, 'selection').catch(() => undefined);
    const kind = recommendation.pedagogicalAction === 'check' ? 'check' : recommendation.actionKind;
    try {
      if (kind === 'check') { onCheck(); return; }
      if (kind === 'learn') { await onLearn(recommendation); return; }
      if (kind === 'ask') { await onAsk(recommendation); return; }
      if (kind === 'quiz') { await onQuiz(recommendation); return; }
      if (kind === 'review') { await onReview(recommendation); }
    } catch {
      void learningApi.recordRecommendationInteraction(recommendation.id, 'failure').catch(() => undefined);
    }
  }

  function dismiss() {
    setDismissedFingerprint(recommendationKey);
    void learningApi.recordRecommendationInteraction(recommendation.id, 'dismissal').catch(() => undefined);
  }

  return (
    <div className={styles.suggestion} role="group" aria-label="Suggested next step">
      <span className={styles.label}><Sparkles size={13} aria-hidden="true" /> Suggested</span>
      <button type="button" className={styles.action} onClick={() => void select()}>
        <span>{suggestionLabel(recommendation)}</span>
        <ArrowRight size={14} aria-hidden="true" />
      </button>
      {recommendation.rationale ? <details className={styles.why}>
        <summary>Why?</summary>
        <p>{recommendation.rationale}</p>
      </details> : null}
      <button type="button" className={styles.dismiss} aria-label="Dismiss suggested next step" onClick={dismiss}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
