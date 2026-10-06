"use client";

import { lazy, Suspense, useState, useEffect, type ComponentType } from 'react';
import { reportVoiceFocus, VOICE_REFRESH } from '@/lib/voice/client';
import { parseVisualization, type VisualizationSpec, type VisualType } from '@/lib/visualization-spec';
import { learningApi } from '@/lib/api';
import styles from './visualization.module.css';

type Renderer = ComponentType<{ spec: VisualizationSpec; onSaveParameters?: (values: Record<string, number>) => Promise<void> }>;
const charts = lazy(() => import('./visualization-chart').then(module => ({ default: module.ChartRenderer })));
const diagrams = lazy(() => import('./visualization-diagram').then(module => ({ default: module.DiagramRenderer })));
const science = lazy(() => import('./visualization-science').then(module => ({ default: module.ScienceRenderer })));
const timeline = lazy(() => import('./visualization-timeline').then(module => ({ default: module.TimelineRenderer })));
const simulations = lazy(() => import('./visualization-simulation').then(module => ({ default: module.SimulationRenderer })));

/** One registration point for every version-one visual type. */
export const rendererRegistry: Record<VisualType, Renderer> = {
  bar: charts, line: charts, scatter: charts, pie: charts, function: charts,
  distribution: charts, flow: diagrams, concept: diagrams, architecture: diagrams,
  science, timeline, simulation: simulations,
};

export function Visualization({ value, lessonId }: { value: unknown; lessonId?: string }) {
  const spec = parseVisualization(value);
  if (!spec) return null;
  return <VisualizationCard key={`${spec.id}:${spec.revision}`} initial={spec} lessonId={lessonId}/>;
}

function VisualizationCard({ initial, lessonId }: { initial: VisualizationSpec; lessonId?: string }) {
  const [spec, setSpec] = useState(initial);
  const focus = () => { if (lessonId) reportVoiceFocus({ lesson_id: lessonId, visualization_id: spec.id, expected_revision: spec.revision }); };
  useEffect(() => {
    const refresh = () => { if (lessonId) void learningApi.getLessonVisualization(lessonId, spec.id).then(value => { const parsed = parseVisualization(value); if (parsed) setSpec(parsed); }).catch(() => undefined); };
    window.addEventListener(VOICE_REFRESH, refresh);
    return () => window.removeEventListener(VOICE_REFRESH, refresh);
  }, [lessonId, spec.id]);
  const Renderer = rendererRegistry[spec.type];
  const saveParameters = async (values: Record<string, number>) => {
    if (!lessonId) return;
    let current = spec;
    for (const parameter of spec.parameters) {
      const value = values[parameter.id];
      if (value === undefined || value === parameter.initial) continue;
      const result = await learningApi.changeLessonVisualization(lessonId, spec.id, {
        operation: 'change_parameter', expectedRevision: current.revision,
        parameterId: parameter.id, value,
      });
      const parsed = parseVisualization(result);
      if (!parsed) throw new Error('The saved visualization could not be read.');
      current = parsed;
    }
    setSpec(current);
  };
  return <figure className={styles.card} onPointerDown={focus} onFocus={focus} data-visualization-type={spec.type} aria-label={spec.title}>
    <figcaption><span className={styles.eyebrow}>{spec.type.replace('_', ' ')}</span><strong>{spec.title}</strong>
      {spec.description && <p>{spec.description}</p>}</figcaption>
    <Suspense fallback={<div className={styles.placeholder} role="status">Preparing visualization…</div>}>
      <Renderer spec={spec} onSaveParameters={lessonId ? saveParameters : undefined}/>
    </Suspense>
    {spec.annotations.length > 0 && <ul className={styles.notes}>{spec.annotations.map((note, i) =>
      <li key={i}>{typeof note === 'string' ? note : note.label}</li>)}</ul>}
    {spec.provenance && <p className={styles.provenance}>
      {spec.provenance.kind === 'illustrative' ? 'Illustrative values' : spec.provenance.kind === 'calculated' ? 'Calculated' : spec.provenance.kind === 'user' ? 'From your data' : 'From a source'} · {spec.provenance.label}
    </p>}
  </figure>;
}

export function VisualizationList({ values }: { values: unknown[] }) {
  return <>{values.map((value, index) => {
    const spec = parseVisualization(value);
    return spec ? <Visualization key={spec.id || index} value={spec}/> : null;
  })}</>;
}

export function VisualizationPlaceholder() {
  return <div className={styles.placeholder} role="status" aria-live="polite">Preparing a useful visual…</div>;
}
