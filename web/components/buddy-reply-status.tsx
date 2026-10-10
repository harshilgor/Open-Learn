'use client';

import type { Buddy } from '@/lib/buddies';
import { BuddyAvatar } from './buddies';
import styles from './buddy-reply-status.module.css';

export function BuddyReplyStatus({ buddy, label }: { buddy?: Buddy; label: string }) {
  return <div className={styles.status} role="status" aria-live="polite" aria-atomic="true">
    {buddy ? <BuddyAvatar buddy={buddy} expression="Thinking"/> : <span className={styles.fallback} aria-hidden="true">✦</span>}
    <span>{label}</span>
  </div>;
}
