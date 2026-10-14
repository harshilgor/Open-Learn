"use client";

import type { ReactNode } from 'react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import styles from './practice-session.module.css';

/** Fields the learner types into keep every key; choice inputs (radio/checkbox) do not. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  return target instanceof HTMLInputElement && !['radio', 'checkbox', 'button', 'submit', 'reset'].includes(target.type);
}

/** A bare key press meant for a practice shortcut: no modifiers, no IME, not typing, not already handled. */
export function isShortcutEvent(event: KeyboardEvent): boolean {
  return !event.defaultPrevented && !event.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !isTypingTarget(event.target);
}

/** Space/Enter on a focused control keep their native activation so a key never does two things. */
export function isActivationTarget(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest('button, a[href], summary, [role="button"]');
}

/** Slim session progress: "Question 3 of 8" with a brand-coloured bar. */
export function SessionProgress({ label, value, max, children }: { label: string; value: number; max: number; children?: ReactNode }) {
  const reduceMotion = useAppReducedMotion();
  const percent = Math.round(Math.min(1, Math.max(0, value / Math.max(1, max))) * 100);
  return <div className={styles.progress}>
    <div className={styles.progressMeta}><span className={styles.progressLabel}>{label}</span>{children}</div>
    <div className={styles.progressTrack} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.min(value, max)} data-animate={reduceMotion ? undefined : ''}><span style={{ width: `${percent}%` }}/></div>
  </div>;
}

/** Keyboard hint shown only where a hardware keyboard is likely (fine pointer that can hover). */
export function KeyHint({ items }: { items: { keys: string[]; label: string }[] }) {
  return <p className={styles.keyHint}>{items.map((item, index) => <span key={item.label}>
    {index ? <span aria-hidden="true" className={styles.keyHintSep}>·</span> : null}
    {item.keys.map((key, keyIndex) => <span key={key}>{keyIndex ? '–' : ''}<kbd className={styles.kbd}>{key}</kbd></span>)} {item.label}
  </span>)}</p>;
}

/** Inline shortcut chip for a button label; the button carries aria-keyshortcuts for assistive tech. */
export function KeyChip({ children }: { children: ReactNode }) {
  return <kbd className={`${styles.kbd} ${styles.kbdInline}`} aria-hidden="true">{children}</kbd>;
}
