"use client";

import { useId } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronDown, RotateCcw, Zap } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import type { Gear } from '@/lib/api';
import styles from './explanation-depth.module.css';

const depths: { value: Gear; description: string }[] = [
  { value: 'Quick', description: 'The essentials, clearly and concisely.' },
  { value: 'Guided', description: 'Step by step, with helpful examples.' },
  { value: 'Deep', description: 'Explore the details and connections.' },
];

export function ExplanationDepth({ gear, onChange, disabled }: { gear: Gear; onChange: (gear: Gear) => void; disabled?: boolean }) {
  const reduceMotion = useAppReducedMotion();
  const descriptionId = useId();
  const index = Math.max(0, depths.findIndex(depth => depth.value === gear));
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" className={styles.trigger} disabled={disabled} aria-label={`Explanation depth: ${gear}`}>
        <Zap size={14} aria-hidden="true"/><span>Explain</span><strong>{gear}</strong><ChevronDown size={12} aria-hidden="true"/>
      </button>
    </PopoverTrigger>
    <PopoverContent side="top" align="start" sideOffset={12} className={styles.panel} aria-label="Explanation depth">
      <div className={styles.heading}>
        <Zap size={17} aria-hidden="true"/>
        <div><span>Explanation depth</span><div className={styles.value}><AnimatePresence mode="wait" initial={false}><motion.strong key={gear} initial={reduceMotion ? false : { opacity: 0, y: 5, filter: 'blur(3px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} exit={reduceMotion ? undefined : { opacity: 0, y: -5, filter: 'blur(3px)' }} transition={{ duration: .13 }}>{gear}</motion.strong></AnimatePresence></div></div>
        <button type="button" aria-label="Reset explanation depth to Quick" title="Reset to Quick" disabled={disabled || gear === 'Quick'} onClick={() => onChange('Quick')}><RotateCcw size={16}/></button>
      </div>
      <div className={styles.track}>
        <div className={styles.rail} aria-hidden="true"><motion.div className={styles.fill} initial={false} animate={{ width: `${index * 50}%` }} transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 34 }}/>{depths.map((depth, stop) => <span key={depth.value} className={styles.dot} data-active={stop <= index} style={{ left: `${stop * 50}%` }}/>)}<motion.span className={styles.thumb} initial={false} animate={{ left: `${index * 50}%` }} transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 30 }}/></div>
        <input type="range" min={0} max={2} step={1} value={index} disabled={disabled} aria-label="Explanation depth" aria-valuetext={gear} aria-describedby={descriptionId} onChange={event => onChange(depths[Number(event.target.value)].value)}/>
      </div>
      <div className={styles.stops}>{depths.map(depth => <button type="button" key={depth.value} aria-pressed={gear === depth.value} disabled={disabled} onClick={() => onChange(depth.value)}>{depth.value}</button>)}</div>
      <p id={descriptionId} className={styles.description}>{depths[index].description}</p>
    </PopoverContent>
  </Popover>;
}
