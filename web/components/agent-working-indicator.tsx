'use client';

import { AnimatePresence, motion } from 'motion/react';
import { Sparkles } from 'lucide-react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import styles from './agent-working-indicator.module.css';

export function AgentWorkingIndicator({ label }: { label: string }) {
  const reduceMotion = useAppReducedMotion();

  return (
    <div className={styles.indicator}>
      <span className={styles.mark} aria-hidden="true">
        <Sparkles size={15} />
      </span>
      <span className={styles.copy} aria-hidden="true">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={label}
            className={styles.label}
            initial={reduceMotion ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {label}
          </motion.span>
        </AnimatePresence>
      </span>
      <span className={styles.dots} aria-hidden="true">
        {[0, 1, 2].map(index => (
          <motion.span
            key={index}
            className={styles.dot}
            animate={reduceMotion ? undefined : { opacity: [0.35, 1, 0.35], y: [0, -2, 0] }}
            transition={reduceMotion ? undefined : { duration: 0.9, delay: index * 0.14, repeat: Infinity, ease: 'easeInOut' }}
          />
        ))}
      </span>
      <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">{label}</span>
    </div>
  );
}
