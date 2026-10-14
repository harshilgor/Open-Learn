"use client";

import { useState, useSyncExternalStore } from 'react';
import { ChevronRight } from 'lucide-react';
import { RichContent } from './rich-content';
import styles from './reading.module.css';
import answerStyles from './assistant/answer-reading.module.css';
import { shouldCollapseAnswer } from '@/lib/answer-reading';
import { Visualization, VisualizationPlaceholder } from './visualization';
import { openWorkspaceCanvas } from '@/lib/workspace-events';
import { parseVisualArtifact as parseVisualization } from '@/lib/generated-visual';
import { LessonVisualRuns } from './generated-visual/visual-runs';

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

export function LessonReader({ id, blocks, onSelect, visualPending = false, hideHtmlSource = false, lessonId, onExerciseResolved, onConceptSelect, redundantHeading, collapsible = false }: {
  redundantHeading?: string;
  /**
   * The answer is complete, so long answers may collapse later sections.
   * Leave false while streaming: every section then stays open.
   */
  collapsible?: boolean;
  id: string; blocks: ReadingBlock[]; visualPending?: boolean; hideHtmlSource?: boolean; lessonId?: string;
  onSelect?: (block: ReadingBlock, raw: string, equation?: boolean) => void;
  onExerciseResolved?: (id: string) => void;
  onConceptSelect?: (term: string) => void;
}) {
  const stored = useSyncExternalStore(subscribe, snapshot, () => defaults);
  const prefs = { size: 'standard', spacing: 'comfortable' };
  try { const parsed = JSON.parse(stored); if (['standard', 'large', 'larger'].includes(parsed.size)) prefs.size = parsed.size; if (['compact', 'comfortable', 'spacious'].includes(parsed.spacing)) prefs.spacing = parsed.spacing; } catch { /* Ignore malformed stored settings. */ }
  const size = prefs.size === 'large' ? '17px' : prefs.size === 'larger' ? '19px' : '15px';
  const leading = prefs.spacing === 'compact' ? '1.55' : prefs.spacing === 'spacious' ? '1.85' : '1.65';
  // An answer first seen while streaming keeps every section open once it
  // completes, so the text being read never collapses under the learner.
  const [seenStreaming] = useState(() => !collapsible);
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const collapsing = collapsible && shouldCollapseAnswer(blocks);
  const sectionCollapsible = (block: ReadingBlock, index: number) => collapsing && index > 0 && Boolean(block.heading?.trim());
  const sectionOpen = (block: ReadingBlock, index: number) => !sectionCollapsible(block, index) || (openSections[block.id] ?? (seenStreaming || index < 2));
  const collapsibleIds = blocks.filter(sectionCollapsible).map(block => block.id);
  const firstCollapsible = blocks.findIndex(sectionCollapsible);
  const anyCollapsed = blocks.some((block, index) => !sectionOpen(block, index));
  const setAllSections = (open: boolean) => setOpenSections(Object.fromEntries(collapsibleIds.map(blockId => [blockId, open])));
  return <div style={{ '--reading-size': size, '--reading-leading': leading } as React.CSSProperties}>
    {blocks.map((block, blockIndex) => {
      const canCollapse = sectionCollapsible(block, blockIndex);
      const open = sectionOpen(block, blockIndex);
      const bodyId = `${id}-${block.id}-body`;
      const content = readingParts(block).map((part, index) => <div key={part.key}>
        {part.text && <RichContent body={part.text} hideHtmlSource={hideHtmlSource || visualPending || Boolean(block.visualizations?.length)} onExplore={onSelect ? (raw, equation) => onSelect(block, raw, equation) : undefined} onExerciseResolved={onExerciseResolved} onConceptSelect={onConceptSelect}/>}
        {part.visual && <><button type="button" className="study-canvas-open" onClick={() => { if (part.visual) openWorkspaceCanvas({ ...part.visual, sourceLessonId: part.visual.sourceLessonId || lessonId }); }}>Open in Canvas</button><Visualization value={part.visual} lessonId={part.visual.sourceLessonId || lessonId}/></>}
        {visualPending && blockIndex === 0 && index === 0 && !(block.visualizations?.length) && <VisualizationPlaceholder/>}
      </div>);
      return <section key={block.id} id={`${id}-${block.id}`} tabIndex={-1} data-reading-block className={`${styles.block}${canCollapse && !open ? ` ${answerStyles.collapsedSection}` : ''}`} style={{ fontSize: size }}>
        {blockIndex === firstCollapsible ? <div className={answerStyles.sectionControls}>
          <button type="button" aria-label={anyCollapsed ? 'Expand all sections' : 'Collapse all sections'} onClick={() => setAllSections(anyCollapsed)}>{anyCollapsed ? 'Expand all' : 'Collapse all'}</button>
        </div> : null}
        {canCollapse ? <>
          <h2><button type="button" className={answerStyles.sectionToggle} aria-expanded={open} aria-controls={bodyId} onClick={() => setOpenSections(current => ({ ...current, [block.id]: !open }))}>
            <ChevronRight size={16} aria-hidden="true" className={answerStyles.sectionChevron} />
            <span>{block.heading}</span>
          </button></h2>
          <div id={bodyId} hidden={!open}>{content}</div>
        </> : <>
          {!(redundantHeading !== undefined && (!block.heading || (blockIndex === 0 && block.heading.trim().toLocaleLowerCase() === redundantHeading.trim().toLocaleLowerCase()))) ? <h2>{block.heading || 'Explore this idea'}</h2> : null}
          {content}
        </>}
      </section>;
    })}
    {!blocks.length && visualPending && <VisualizationPlaceholder/>}
    {lessonId?<LessonVisualRuns lessonId={lessonId} existingIds={blocks.flatMap(block=>(block.visualizations||[]).map(parseVisualization).filter(value=>value!==null).map(value=>value.id))}/>:null}
  </div>;
}
