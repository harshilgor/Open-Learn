"use client";

import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { CircleHelp, GraduationCap, MessageCircleQuestion, Sparkles, X, ArrowRight, LoaderCircle } from 'lucide-react';
import type { ModeTransitionSuggestion } from '@/lib/api';
import styles from './mode-transition-card.module.css';

interface ModeTransitionCardProps {
  suggestion: ModeTransitionSuggestion;
  onAccept: (suggestion: ModeTransitionSuggestion) => void | Promise<void>;
  onDismiss: (suggestion: ModeTransitionSuggestion) => void | Promise<void>;
  disabled?: boolean;
}

export function ModeTransitionCard({
  suggestion,
  onAccept,
  onDismiss,
  disabled = false,
}: ModeTransitionCardProps) {
  const reduceMotion = useAppReducedMotion();
  const [busy, setBusy] = useState(false);

  const isLearn = suggestion.targetMode === 'learn';
  const accepted = suggestion.status === 'accepted';
  const isQuiz = suggestion.targetMode === 'quiz';
  const Icon = isLearn ? GraduationCap : isQuiz ? CircleHelp : MessageCircleQuestion;
  const topic = String(suggestion.context?.conceptTitle || 'this topic').replace(/[\u0000-\u001f<>]/g, '').slice(0, 100).trim() || 'this topic';
  const modeName = isLearn ? 'Learn' : isQuiz ? 'Quiz' : 'Ask';
  const modeStyle = isQuiz ? styles.quiz : styles.learn;
  const title = isLearn ? (suggestion.reason === 'persistent_concept_gap' ? `Review ${topic}?` : 'Switch to Learn?') : isQuiz ? 'Switch to Quiz?' : 'Switch to Ask?';
  const description = isLearn
    ? `Work through ${topic} step by step, then return to this conversation.`
    : isQuiz ? `Practice ${topic} using material from this conversation.` : 'Get a direct answer without the structured lesson.';
  const actionLabel = accepted
    ? (isLearn ? 'Continue in Learn' : isQuiz ? 'Continue to Quiz' : 'Continue in Ask')
    : (suggestion.reason === 'persistent_concept_gap'
      ? 'Review in Learn'
      : suggestion.actionLabel || (isLearn ? 'Continue in Learn' : 'Switch to Quiz'));

  const handleAccept = async () => {
    if (busy || disabled) return;
    setBusy(true);
    try {
      await onAccept(suggestion);
    } finally {
      setBusy(false);
    }
  };

  const handleDismiss = async () => {
    if (busy) return;
    setBusy(true);
    try { await onDismiss(suggestion); } finally { setBusy(false); }
  };

  return (
    <AnimatePresence>
      <motion.div
        className={`${styles.transitionCard} ${modeStyle}`}
        role="region"
        aria-label="Mode handoff suggestion"
        aria-live="polite"
        tabIndex={-1}
        onKeyDown={event => {
          if (!accepted && event.key === 'Escape' && event.currentTarget.contains(document.activeElement)) {
            event.preventDefault();
            void handleDismiss();
          }
        }}
        initial={reduceMotion ? false : { opacity: 0, y: 8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? undefined : { opacity: 0, y: -6, scale: 0.98 }}
        transition={{ duration: 0.22, ease: 'easeOut' }}
      >
        <div className={styles.header}>
          <span className={`${styles.iconTile} ${modeStyle}`}>
            <Icon size={14} />
          </span>
          <strong className={styles.title}>{title}</strong>
        </div>
        <p className={styles.description}>{accepted ? `Your switch is saved. Continue to open ${modeName}.` : description}</p>
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.primaryButton} ${modeStyle}`}
            disabled={disabled || busy}
            onClick={() => void handleAccept()}
          >
            <span>{busy ? 'Working…' : actionLabel}</span>
            {busy ? <LoaderCircle className={styles.spinner} size={13} aria-hidden="true" /> : <ArrowRight size={13} />}
          </button>
          {!accepted ? <button
            type="button"
            className={styles.dismissButton}
            disabled={disabled || busy}
            onClick={() => void handleDismiss()}
          >
            {suggestion.dismissLabel || 'Cancel'}
          </button> : null}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

interface OriginBadgeProps {
  summary: string;
  onDismiss: () => void;
}

export function OriginBadge({ summary, onDismiss }: OriginBadgeProps) {
  const reduceMotion = useAppReducedMotion();

  return (
    <motion.div
      className={styles.originBadge}
      role="status"
      initial={reduceMotion ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
    >
      <Sparkles size={12} />
      <span>{summary}</span>
      <button type="button" aria-label="Dismiss origin note" onClick={onDismiss}>
        <X size={12} />
      </button>
    </motion.div>
  );
}
