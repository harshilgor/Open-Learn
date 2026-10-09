"use client";

import { useId } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Sparkles } from 'lucide-react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import styles from './web-research-activity.module.css';

export type AgentActivity =
  | {
      type: 'web_search';
      status: 'searching' | 'complete' | 'error';
      query?: string;
      sourceCount: number;
    }
  | {
      type: 'synthesizing';
    }
  | {
      type: 'writing';
    }
  | {
      type: 'visualizing';
    }
  | null;

/**
 * Predefined satellite positions around the 36x36 radar coordinate space (center 18, 18).
 * Distributed naturally across inner and outer radii.
 */
const SATELLITE_POSITIONS = [
  { x: 26, y: 11 }, // Quadrant 1
  { x: 10, y: 12 }, // Quadrant 2
  { x: 27, y: 24 }, // Quadrant 4
  { x: 9, y: 25 },  // Quadrant 3
  { x: 18, y: 4 },   // North
  { x: 18, y: 32 },  // South
  { x: 5, y: 18 },   // West
  { x: 31, y: 18 },  // East
];

function ResearchRadar({
  status,
  sourceCount,
  reduceMotion,
}: {
  status: 'searching' | 'complete' | 'error';
  sourceCount: number;
  reduceMotion: boolean | null;
}) {
  const maskId = useId();
  const visibleDots = SATELLITE_POSITIONS.slice(0, Math.min(sourceCount, SATELLITE_POSITIONS.length));

  if (status === 'error') {
    return (
      <div className={styles.visualWrapper} aria-hidden="true">
        <svg viewBox="0 0 36 36" className={styles.radarSvg}>
          <circle cx="18" cy="18" r="14" fill="none" stroke="#e8d5d3" strokeWidth="1.2" />
          <circle cx="18" cy="18" r="12" fill="#fdf5f4" />
          <path d="M18 11v9" stroke="#983b30" strokeWidth="2" strokeLinecap="round" />
          <circle cx="18" cy="24" r="1.2" fill="#983b30" />
        </svg>
      </div>
    );
  }

  if (status === 'complete') {
    return (
      <div className={styles.visualWrapper} aria-hidden="true">
        <svg viewBox="0 0 36 36" className={styles.radarSvg}>
          <motion.circle
            cx="18"
            cy="18"
            r="14"
            fill="#f1f6ed"
            stroke="#c4d5ba"
            strokeWidth="1.2"
            initial={reduceMotion ? false : { scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          />
          <motion.path
            d="M11 18.5l4.5 4.5 9.5-9.5"
            fill="none"
            stroke="#39522e"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduceMotion ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          />
        </svg>
      </div>
    );
  }

  return (
    <div className={styles.visualWrapper} aria-hidden="true">
      <svg viewBox="0 0 36 36" className={styles.radarSvg}>
        <defs>
          <linearGradient id={`${maskId}-sweep`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#4a6435" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#4a6435" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Concentric subtle radar rings */}
        <circle cx="18" cy="18" r="14" fill="none" stroke="#d5decb" strokeWidth="0.8" strokeDasharray="2 2" />
        <circle cx="18" cy="18" r="8" fill="none" stroke="#dbe3d3" strokeWidth="0.8" />

        {/* Subtle quadrant ticks */}
        <line x1="18" y1="2" x2="18" y2="5" stroke="#b8c6ae" strokeWidth="0.8" />
        <line x1="18" y1="31" x2="18" y2="34" stroke="#b8c6ae" strokeWidth="0.8" />
        <line x1="2" y1="18" x2="5" y2="18" stroke="#b8c6ae" strokeWidth="0.8" />
        <line x1="31" y1="18" x2="34" y2="18" stroke="#b8c6ae" strokeWidth="0.8" />

        {/* Rotating sweep line and faint wedge */}
        <motion.g
          style={{ originX: '18px', originY: '18px' }}
          animate={reduceMotion ? undefined : { rotate: 360 }}
          transition={
            reduceMotion
              ? undefined
              : { repeat: Infinity, duration: 2.2, ease: 'linear' }
          }
        >
          {/* Faint sweep beam */}
          <path
            d="M 18 18 L 18 4 A 14 14 0 0 1 29 10 Z"
            fill={`url(#${maskId}-sweep)`}
          />
          {/* Leading sweep line */}
          <line x1="18" y1="18" x2="18" y2="4" stroke="#4a6435" strokeWidth="1.2" strokeLinecap="round" />
        </motion.g>

        {/* Central beacon node */}
        <motion.circle
          cx="18"
          cy="18"
          r="4.5"
          fill="#526b3e"
          fillOpacity="0.18"
          animate={reduceMotion ? undefined : { scale: [1, 1.35, 1], opacity: [0.18, 0.35, 0.18] }}
          transition={
            reduceMotion
              ? undefined
              : { repeat: Infinity, duration: 1.8, ease: 'easeInOut' }
          }
          style={{ originX: '18px', originY: '18px' }}
        />
        <circle cx="18" cy="18" r="2.2" fill="#394f2c" />

        {/* Dynamically accumulated source nodes */}
        {visibleDots.map((pos, idx) => (
          <motion.circle
            key={idx}
            cx={pos.x}
            cy={pos.y}
            r="1.75"
            fill="#3e5730"
            stroke="#fcfdfa"
            strokeWidth="0.6"
            initial={reduceMotion ? false : { scale: 0, opacity: 0 }}
            animate={
              reduceMotion
                ? { scale: 1, opacity: 1 }
                : {
                    scale: [0, 1.3, 1],
                    opacity: 1,
                  }
            }
            transition={{ duration: 0.3, ease: 'easeOut' }}
            style={{ originX: `${pos.x}px`, originY: `${pos.y}px` }}
          />
        ))}
      </svg>
    </div>
  );
}

function SynthesizingVisual({ reduceMotion }: { reduceMotion: boolean | null }) {
  return (
    <div className={styles.visualWrapper} aria-hidden="true">
      <svg viewBox="0 0 36 36" className={styles.radarSvg}>
        <circle cx="18" cy="18" r="14" fill="#f8faf5" stroke="#dae3d2" strokeWidth="0.8" />
        {/* Converging nodes toward center */}
        {[
          { x: 18, y: 8, dx: 0, dy: 5 },
          { x: 18, y: 28, dx: 0, dy: -5 },
          { x: 8, y: 18, dx: 5, dy: 0 },
          { x: 28, y: 18, dx: -5, dy: 0 },
        ].map((node, i) => (
          <motion.circle
            key={i}
            cx={node.x}
            cy={node.y}
            r="1.8"
            fill="#526b3e"
            animate={
              reduceMotion
                ? undefined
                : {
                    x: [0, node.dx, 0],
                    y: [0, node.dy, 0],
                    opacity: [0.5, 1, 0.5],
                  }
            }
            transition={
              reduceMotion
                ? undefined
                : { repeat: Infinity, duration: 1.6, delay: i * 0.15, ease: 'easeInOut' }
            }
          />
        ))}
        {/* Central spark */}
        <motion.path
          d="M 18 13 Q 18 18 23 18 Q 18 18 18 23 Q 18 18 13 18 Q 18 18 18 13 Z"
          fill="#3b522c"
          animate={reduceMotion ? undefined : { scale: [0.85, 1.15, 0.85] }}
          transition={
            reduceMotion
              ? undefined
              : { repeat: Infinity, duration: 1.6, ease: 'easeInOut' }
          }
          style={{ originX: '18px', originY: '18px' }}
        />
      </svg>
    </div>
  );
}

function WritingVisual({ reduceMotion }: { reduceMotion: boolean | null }) {
  return (
    <div className={styles.visualWrapper} aria-hidden="true">
      <svg viewBox="0 0 36 36" className={styles.radarSvg}>
        <circle cx="18" cy="18" r="14" fill="#f9fbf7" stroke="#e0e7d9" strokeWidth="0.8" />
        {/* Three micro dots pulsing sequentially */}
        {[13, 18, 23].map((cx, i) => (
          <motion.circle
            key={i}
            cx={cx}
            cy="18"
            r="1.8"
            fill="#455e36"
            animate={
              reduceMotion
                ? undefined
                : {
                    opacity: [0.3, 1, 0.3],
                    scale: [0.85, 1.25, 0.85],
                  }
            }
            transition={
              reduceMotion
                ? undefined
                : {
                    repeat: Infinity,
                    duration: 1.1,
                    delay: i * 0.18,
                    ease: 'easeInOut',
                  }
            }
            style={{ originX: `${cx}px`, originY: '18px' }}
          />
        ))}
      </svg>
    </div>
  );
}

function VisualizingVisual({ reduceMotion }: { reduceMotion: boolean | null }) {
  return (
    <div className={styles.visualWrapper} aria-hidden="true">
      <motion.div
        animate={reduceMotion ? undefined : { rotate: [0, 12, -12, 0], scale: [1, 1.08, 1] }}
        transition={reduceMotion ? undefined : { duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
      >
        <Sparkles size={22} strokeWidth={1.7} />
      </motion.div>
    </div>
  );
}

export function WebResearchActivity({ activity }: { activity: AgentActivity }) {
  const reduceMotion = useAppReducedMotion();

  if (!activity) return null;

  // Derive screen reader accessible status text
  let accessibleStatus = '';
  if (activity.type === 'web_search') {
    if (activity.status === 'error') {
      accessibleStatus = "Search couldn't be completed. Continuing with available materials.";
    } else if (activity.status === 'complete') {
      accessibleStatus = `Research complete. ${activity.sourceCount} source${activity.sourceCount === 1 ? '' : 's'} found.`;
    } else if (activity.sourceCount > 0) {
      accessibleStatus = `Searching the web. ${activity.sourceCount} source${activity.sourceCount === 1 ? '' : 's'} found.`;
    } else {
      accessibleStatus = activity.query
        ? `Searching the web for ${activity.query}.`
        : 'Searching the web.';
    }
  } else if (activity.type === 'synthesizing') {
    accessibleStatus = 'Synthesizing findings into your lesson.';
  } else if (activity.type === 'writing') {
    accessibleStatus = 'Writing your explanation.';
  } else if (activity.type === 'visualizing') {
    accessibleStatus = 'Planning a visual to explain this.';
  }

  return (
    <motion.div
      role="status"
      className={styles.activityContainer}
      initial={reduceMotion ? false : { opacity: 0, y: 6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: -4, scale: 0.98 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
    >
      <span className="sr-only" aria-live="polite">
        {accessibleStatus}
      </span>

      {/* Visual icon for active state */}
      {activity.type === 'web_search' && (
        <ResearchRadar
          status={activity.status}
          sourceCount={activity.sourceCount}
          reduceMotion={reduceMotion}
        />
      )}
      {activity.type === 'synthesizing' && <SynthesizingVisual reduceMotion={reduceMotion} />}
      {activity.type === 'writing' && <WritingVisual reduceMotion={reduceMotion} />}
      {activity.type === 'visualizing' && <VisualizingVisual reduceMotion={reduceMotion} />}

      {/* Label and detailed progress text */}
      <div className={styles.textGroup}>
        <AnimatePresence mode="wait" initial={false}>
          {activity.type === 'web_search' && activity.status === 'searching' && (
            <motion.div
              key="searching"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}>
                <span>Searching the web</span>
                {activity.sourceCount > 0 && (
                  <span className={styles.sourceBadge}>
                    {activity.sourceCount} found
                  </span>
                )}
              </div>
              <p className={styles.subtitle}>
                {activity.sourceCount > 0
                  ? `${activity.sourceCount} source${activity.sourceCount === 1 ? '' : 's'} found…`
                  : activity.query
                  ? `“${activity.query}”`
                  : 'Finding relevant sources…'}
              </p>
            </motion.div>
          )}

          {activity.type === 'web_search' && activity.status === 'complete' && (
            <motion.div
              key="complete"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}>
                <span>Research complete</span>
                {activity.sourceCount > 0 && (
                  <span className={styles.sourceBadge}>
                    {activity.sourceCount} sources
                  </span>
                )}
              </div>
              <p className={styles.subtitle}>
                {activity.sourceCount > 0
                  ? `${activity.sourceCount} relevant sources gathered`
                  : 'Sources reviewed'}
              </p>
            </motion.div>
          )}

          {activity.type === 'web_search' && activity.status === 'error' && (
            <motion.div
              key="error"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}>
                <span className={styles.errorText}>Search couldn&apos;t be completed</span>
              </div>
              <p className={styles.subtitle}>Continuing with your course materials</p>
            </motion.div>
          )}

          {activity.type === 'synthesizing' && (
            <motion.div
              key="synthesizing"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}>
                <span>Synthesizing findings…</span>
              </div>
              <p className={styles.subtitle}>Connecting evidence to your lesson</p>
            </motion.div>
          )}

          {activity.type === 'writing' && (
            <motion.div
              key="writing"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}>
                <span>Writing your explanation…</span>
              </div>
              <p className={styles.subtitle}>Crafting step-by-step guidance</p>
            </motion.div>
          )}

          {activity.type === 'visualizing' && (
            <motion.div
              key="visualizing"
              initial={reduceMotion ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.titleRow}><span>Planning a visual…</span></div>
              <p className={styles.subtitle}>Adding a visual aid to the explanation</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
