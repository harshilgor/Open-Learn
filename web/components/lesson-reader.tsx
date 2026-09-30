"use client";

import { useSyncExternalStore } from 'react';
import { RichContent } from './rich-content';
import styles from './reading.module.css';
import { Visualization, VisualizationPlaceholder } from './visualization';
import { parseVisualization } from '@/lib/visualization-spec';

export type ReadingBlock = {
  id: string; heading?: string | null; body: string; visualizations?: unknown[];
  parts?: Array<{ kind: 'text' | 'visualization'; text?: string | null; visualizationId?: string | null }>;
};
const defaults = '{"size":"standard","spacing":"comfortable"}';
const memory = defaults;
function subscribe(callback: () => void) { window.addEventListener('storage', callback); window.addEventListener('forma-reading', callback); return () => { window.removeEventListener('storage', callback); window.removeEventListener('forma-reading', callback); }; }
function snapshot() { try { return window.localStorage.getItem('forma-reading') || memory; } catch { return memory; } }

function splitParagraphs(markdown: string): string[] {
  const groups: string[] = []; let lines: string[] = []; let fenced = false;
  for (const line of markdown.split('\n')) {
    if (line.trimStart().startsWith('```')) fenced = !fenced;
    if (!line.trim() && !fenced && lines.length) { groups.push(lines.join('\n').trim()); lines = []; }
    else lines.push(line);
  }
  if (lines.length) groups.push(lines.join('\n').trim());
  return groups.filter(Boolean);
}

function readingParts(block: ReadingBlock) {
  const visuals = (block.visualizations || []).map(parseVisualization).filter((v): v is NonNullable<typeof v> => !!v);
  if (block.parts?.length) {
    return block.parts.map((part, i) => ({
      key: `${part.kind}-${i}`, text: part.kind === 'text' ? part.text || '' : '',
      visual: part.kind === 'visualization' ? visuals.find(v => v.id === part.visualizationId) : null,
    }));
  }
  if (!visuals.length) return [{ key: 'text', text: block.body, visual: null }];
  const chunks = splitParagraphs(block.body);
  return chunks.flatMap((text, index) => [
    { key: `text-${index}`, text, visual: null },
    ...visuals.filter(v => Math.min(v.afterParagraph, chunks.length - 1) === index)
      .map(visual => ({ key: visual.id, text: '', visual })),
  ]);
}

export function LessonReader({ id, blocks, onSelect, visualPending = false, lessonId, onExerciseResolved, onConceptSelect }: {
  id: string; blocks: ReadingBlock[]; visualPending?: boolean; lessonId?: string;
  onSelect?: (block: ReadingBlock, raw: string, equation?: boolean) => void;
  onExerciseResolved?: (id: string) => void;
  onConceptSelect?: (term: string) => void;
}) {
  const stored = useSyncExternalStore(subscribe, snapshot, () => defaults);
  const prefs = { size: 'standard', spacing: 'comfortable' };
  try { const parsed = JSON.parse(stored); if (['standard', 'large', 'larger'].includes(parsed.size)) prefs.size = parsed.size; if (['compact', 'comfortable', 'spacious'].includes(parsed.spacing)) prefs.spacing = parsed.spacing; } catch { /* Ignore malformed stored settings. */ }
  const size = prefs.size === 'large' ? '17px' : prefs.size === 'larger' ? '19px' : '15px';
  const leading = prefs.spacing === 'compact' ? '1.55' : prefs.spacing === 'spacious' ? '1.85' : '1.65';
  return <div style={{ '--reading-size': size, '--reading-leading': leading } as React.CSSProperties}>
    {blocks.map((block, blockIndex) => <section key={block.id} id={`${id}-${block.id}`} tabIndex={-1} data-reading-block className={styles.block} style={{ fontSize: size }}>
      <h2>{block.heading || 'Explore this idea'}</h2>
      {readingParts(block).map((part, index) => <div key={part.key}>
        {part.text && <RichContent body={part.text} onExplore={onSelect ? (raw, equation) => onSelect(block, raw, equation) : undefined} onExerciseResolved={onExerciseResolved} onConceptSelect={onConceptSelect}/>}
        {part.visual && <Visualization value={part.visual} lessonId={part.visual.sourceLessonId || lessonId}/>}
        {visualPending && blockIndex === 0 && index === 0 && !(block.visualizations?.length) && <VisualizationPlaceholder/>}
      </div>)}
    </section>)}
    {!blocks.length && visualPending && <VisualizationPlaceholder/>}
  </div>;
}
