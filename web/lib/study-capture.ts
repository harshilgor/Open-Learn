import { parseVisualArtifact as parseVisualization } from './generated-visual';

/** Keep durable visual references alongside editable explanation text. */
export function captureReadingBlocks(blocks: Array<{heading?: string | null; body?: string | null; visualizations?: unknown[]}>, lessonId?: string): string {
  return blocks.map(block => {
    const visuals = (block.visualizations || []).map(parseVisualization).filter(value => value !== null);
    const references = visuals.flatMap(visual => {
      const source = visual.sourceLessonId || lessonId;
      return source ? ['```visualization-ref\n' + JSON.stringify({lessonId:source,visualizationId:visual.id,title:visual.title}) + '\n```'] : [];
    });
    return [block.heading ? `## ${block.heading}` : '', block.body || '', ...references].filter(Boolean).join('\n\n');
  }).join('\n\n');
}
