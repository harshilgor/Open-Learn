import { describe, expect, it } from 'vitest';
import { parseGeneratedVisual, parseVisualArtifact } from '@/lib/generated-visual';
import { buildFinalFrameContent, PREVIEW_FRAME_CONTENT } from '@/components/generated-visual/upstream/frame-content';
import { IMPORTMAP } from '@/components/generated-visual/upstream/design-system';

const base = { version: 2, type: 'generated_ui', id: 'visual_1', revision: 1, title: 'Compare forces', renderer: 'a2ui' };
describe('generated visual boundary', () => {
  it('reads durable references and validates persisted control state', () => {
    expect(parseVisualArtifact({...base,type:'generated_ui_ref',runId:'run_1'})?.type).toBe('generated_ui_ref');
    const value={...base,renderer:'open_generative_ui',content:{html:['<p>Force</p>']},controls:[{id:'mass',label:'Mass',minimum:1,maximum:10,initial:2}],controlValues:{mass:5}};
    expect(parseGeneratedVisual(value)?.controlValues.mass).toBe(5);
    expect(parseGeneratedVisual({...value,controlValues:{mass:11}})).toBeNull();
    expect(parseGeneratedVisual({...value,controlValues:{unknown:5}})).toBeNull();
  });
  it('accepts a sourced table and rejects mismatched row widths', () => {
    const content = { title: 'Forces', columns: ['Force', 'Unit'], rows: [['Gravity', 'N']], source: 'Illustrative example' };
    expect(parseGeneratedVisual({ ...base, content })?.renderer).toBe('a2ui');
    expect(parseGeneratedVisual({ ...base, content: { ...content, rows: [['Gravity']] } })).toBeNull();
    expect(parseGeneratedVisual({ ...base, content: { ...content, source: '' } })).toBeNull();
  });
  it('rejects unsafe shape and excessive combined code payloads', () => {
    const visual = { ...base, renderer: 'open_generative_ui' };
    expect(parseGeneratedVisual({ ...visual, content: { html: [5] } })).toBeNull();
    expect(parseGeneratedVisual({ ...visual, content: { initialHeight: Infinity } })).toBeNull();
    expect(parseGeneratedVisual({ ...visual, content: { css: 'x'.repeat(300000), jsFunctions: 'x'.repeat(300000) } })).toBeNull();
    expect(parseGeneratedVisual({ ...visual, content: { externalUrl: 'https://example.com' } })).toBeNull();
  });
  it('applies the same network and navigation policy to preview and final frames', () => {
    const final = buildFinalFrameContent('<p>Example</p>');
    for (const frame of [PREVIEW_FRAME_CONTENT, final]) {
      expect(frame).toContain("connect-src 'none'");
      expect(frame).toContain("form-action 'none'");
      expect(frame).toContain('/visual-assets/');
    }
    for (const url of Object.values(IMPORTMAP.imports)) {
      expect(new URL(url).origin).toBe(window.location.origin);
      expect(url).not.toContain('${');
    }
  });
});
