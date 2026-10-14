"use client";

import { useEffect, useMemo, useState } from 'react';
import { learningApi } from '@/lib/api';
import { Visualization } from './visualization';
import { parseVisualArtifact } from '@/lib/generated-visual';
import { openWorkspaceCanvas } from '@/lib/workspace-events';
import styles from './visualization.module.css';

type Reference = { lessonId: string; visualizationId: string; title?: string };
function references(body: string): Reference[] {
  const found: Reference[] = [];
  for (const match of body.matchAll(/```visualization-ref\s*\n([^\n]+)\n```/g)) {
    try {
      const value = JSON.parse(match[1]) as Reference;
      if (/^lesson_[A-Za-z0-9_-]+$/.test(value.lessonId) && /^[A-Za-z0-9_-]+$/.test(value.visualizationId)
        && !found.some(item => item.lessonId === value.lessonId && item.visualizationId === value.visualizationId)) found.push(value);
    } catch { /* A learner may edit Markdown freely. */ }
  }
  return found.slice(0, 12);
}

export function NoteVisualReferences({ body }: { body: string }) {
  const refs = useMemo(() => references(body), [body]);
  const [loaded, setLoaded] = useState<Record<string, unknown>>({});
  useEffect(() => {
    let active = true;
    for (const reference of refs) {
      const key = `${reference.lessonId}:${reference.visualizationId}`;
      void learningApi.getLessonVisualization(reference.lessonId, reference.visualizationId)
        .then(value => { if (active) setLoaded(old => ({ ...old, [key]: value })); })
        .catch(() => { if (active) setLoaded(old => ({ ...old, [key]: null })); });
    }
    return () => { active = false; };
  }, [refs]);
  if (!refs.length) return null;
  return <div className={styles.noteVisuals} aria-label="Lesson visuals saved with this note">
    <strong>Lesson visuals</strong>
    {refs.map(reference => {
      const key = `${reference.lessonId}:${reference.visualizationId}`;
      return <details key={key}><summary>{reference.title || 'Open visualization'}</summary>
        {loaded[key] ? <Visualization value={loaded[key]} lessonId={reference.lessonId}/> : <p>Visualization unavailable or loading.</p>}
      </details>;
    })}
  </div>;
}

/** Fenced code languages that embed a visual in a note. */
export const NOTE_VISUAL_LANGUAGES = ['visualization-ref', 'visual-artifact'] as const;
type NoteVisualLanguage = typeof NOTE_VISUAL_LANGUAGES[number];
const MAX_EMBEDDED_VISUAL = 20000;

/**
 * The Markdown that stores a canvas visual in a note: a lesson reference, a
 * reference to a saved generated visual, or a small spec copied verbatim.
 * Returns null for a visual too large to keep inside a note.
 */
export function noteVisualMarkdown(value: unknown): string | null {
  const visual = parseVisualArtifact(value);
  if (!visual) return null;
  const fence = (language: NoteVisualLanguage, json: unknown) => `\`\`\`${language}\n${JSON.stringify(json)}\n\`\`\``;
  if ('type' in visual && (visual.type === 'generated_ui' || visual.type === 'generated_ui_ref')) {
    return fence('visual-artifact', { version: 2, type: 'generated_ui_ref', id: visual.id, revision: visual.revision, title: visual.title, sourceLessonId: visual.sourceLessonId, blockIndex: visual.blockIndex, afterParagraph: visual.afterParagraph, runId: 'runId' in visual ? visual.runId : '' });
  }
  if (visual.sourceLessonId) return fence('visualization-ref', { lessonId: visual.sourceLessonId, visualizationId: visual.id, title: visual.title });
  const json = JSON.stringify(visual);
  return json.length <= MAX_EMBEDDED_VISUAL ? fence('visual-artifact', visual) : null;
}

/** A visual embedded in a note body. It renders as one atomic, non-editable block. */
export function InlineNoteVisual({ language, source }: { language: string; source: string }) {
  const parsed = useMemo(() => { try { return JSON.parse(source) as unknown; } catch { return null; } }, [source]);
  const reference = language === 'visualization-ref' && parsed && typeof parsed === 'object' ? parsed as Reference : null;
  const [loaded, setLoaded] = useState<{ key: string; value: unknown } | null>(null);
  const lessonId = reference?.lessonId || '', visualizationId = reference?.visualizationId || '';
  const key = `${lessonId}:${visualizationId}`;
  useEffect(() => {
    if (!/^lesson_[A-Za-z0-9_-]+$/.test(lessonId) || !visualizationId) return;
    let active = true;
    void learningApi.getLessonVisualization(lessonId, visualizationId)
      .then(value => { if (active) setLoaded({ key: `${lessonId}:${visualizationId}`, value }); })
      .catch(() => { if (active) setLoaded({ key: `${lessonId}:${visualizationId}`, value: null }); });
    return () => { active = false; };
  }, [lessonId, visualizationId]);
  const value = reference ? (!/^lesson_[A-Za-z0-9_-]+$/.test(lessonId) ? null : loaded?.key === key ? loaded.value : undefined) : parsed;
  const title = (parsed && typeof parsed === 'object' && 'title' in parsed && typeof parsed.title === 'string' ? parsed.title : '') || 'Visual';
  return <figure className={styles.noteVisual} contentEditable={false} data-note-visual={source} data-note-visual-lang={language} aria-label={title}>
    <figcaption><span>Visual</span><strong>{title}</strong>{value ? <button type="button" onClick={() => openWorkspaceCanvas(value)}>Open in Canvas</button> : null}</figcaption>
    {value === undefined ? <p role="status">Loading visual…</p> : value && parseVisualArtifact(value) ? <Visualization value={value} lessonId={reference?.lessonId}/> : <p role="status">This visual is unavailable.</p>}
  </figure>;
}
