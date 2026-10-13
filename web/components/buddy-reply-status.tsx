'use client';

import type { Buddy } from '@/lib/buddies';
import { BuddyAvatar } from './buddies';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import styles from './buddy-reply-status.module.css';

export function BuddyReplyStatus({ buddy, label }: { buddy?: Buddy; label: string }) {
  const reduceMotion = useAppReducedMotion();
  return <div className={styles.status} role="status" aria-live="polite" aria-atomic="true">
    {buddy ? <BuddyAvatar buddy={buddy} expression="Thinking"/> : <span className={styles.fallback} aria-hidden="true">✦</span>}
    <span className={`${styles.wave} ${reduceMotion ? styles.still : ''}`} aria-hidden="true">{[0,1,2,3,4].map(index => <i key={index} style={{animationDelay:`${index * 120}ms`}}/>)}</span>
    <span>{label}</span>
  </div>;
}
