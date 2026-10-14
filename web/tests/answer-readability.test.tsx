import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { RichContent } from '@/components/rich-content';
import { LessonReader, type ReadingBlock } from '@/components/lesson-reader';
import { CitationChip, CitationList } from '@/components/assistant/citation-chip';
import { encodeCitationMarkers, parseCitationHref, shouldCollapseAnswer } from '@/lib/answer-reading';
import { WORKSPACE_SOURCE_OPEN_EVENT } from '@/lib/workspace-events';

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
function render(node: ReactNode) { act(() => root.render(node)); }
function click(element: Element) { act(() => (element as HTMLElement).click()); }
function captureSourceOpens() {
  const opened: unknown[] = [];
  const receive = (event: Event) => opened.push((event as CustomEvent).detail);
  window.addEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive);
  return { opened, stop: () => window.removeEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive) };
}
const words = (count: number, seed: string) => Array.from({ length: count }, (_, index) => `${seed}${index}`).join(' ');

describe('citation markers', () => {
  it('encodes alias and span markers as citation links, leaving code and unknown markers alone', () => {
    expect(encodeCitationMarkers('Gradients flow [web:W1] and [material:M2, M3].')).toBe('Gradients flow [W1](citation:alias/W1) and [M2](citation:alias/M2) [M3](citation:alias/M3).');
    expect(encodeCitationMarkers('See [source:span-42].')).toBe('See [Source](citation:span/span-42).');
    expect(encodeCitationMarkers('`[web:W1]` and [web:not a valid alias!]')).toBe('`[web:W1]` and [web:not a valid alias!]');
    expect(encodeCitationMarkers('[web:W1](https://example.com)')).toBe('[web:W1](https://example.com)');
    expect(parseCitationHref('citation:span/span%2F1')).toEqual({ kind: 'span', spanId: 'span/1' });
    expect(parseCitationHref('citation:alias/W3')).toEqual({ kind: 'alias', alias: 'W3', origin: 'web' });
    expect(parseCitationHref('https://example.com')).toBeNull();
  });

  it('renders inline span citations as chips that dispatch the source-open event', () => {
    const capture = captureSourceOpens();
    render(<RichContent body="Cells divide by mitosis [source:span-7]. Also [web:W2]." />);
    const chip = container.querySelector<HTMLButtonElement>('button[aria-label^="Open cited passage"]');
    expect(chip).toBeTruthy();
    expect(container.textContent).not.toContain('[source:');
    click(chip!);
    expect(capture.opened).toEqual([{ spanId: 'span-7', versionId: undefined, title: undefined }]);
    // Alias markers have no openable span: they render as a static, labelled pill.
    const alias = [...container.querySelectorAll('span[title]')].find(item => item.getAttribute('title') === 'Web source W2');
    expect(alias?.textContent).toContain('W2');
    expect(container.textContent).not.toContain('[web:W2]');
    capture.stop();
  });

  it('shows a compact page label, exposes the full title and opens the passage from the keyboard', () => {
    const capture = captureSourceOpens();
    render(<CitationList label="Cited passages" sources={[{ spanId: 's1', versionId: 'v1', title: 'Campbell Biology, 12th edition', pageIndex: 3 }]} />);
    const list = container.querySelector('ul[aria-label="Cited passages"]');
    const chip = list!.querySelector('button')!;
    expect(chip.getAttribute('title')).toBe('Campbell Biology, 12th edition · Page 4');
    expect(chip.textContent).toContain('p. 4');
    expect(chip.type).toBe('button');
    chip.focus();
    expect(document.activeElement).toBe(chip);
    click(chip);
    expect(capture.opened).toEqual([{ spanId: 's1', versionId: 'v1', title: 'Campbell Biology, 12th edition' }]);
    capture.stop();
  });

  it('prefers a printed page label', () => {
    render(<CitationChip source={{ spanId: 's2', title: 'Notes', pageIndex: 9, pageLabel: 'xii' }} />);
    expect(container.textContent).toContain('p. xii');
  });
});

describe('collapsible long answers', () => {
  const longBlocks: ReadingBlock[] = [
    { id: 'b1', heading: 'Overview', body: words(120, 'a') },
    { id: 'b2', heading: 'Mechanism', body: words(120, 'b') },
    { id: 'b3', heading: 'Worked example', body: words(120, 'c') },
    { id: 'b4', heading: 'Common mistakes', body: words(120, 'd') },
  ];
  const toggle = (name: string) => [...container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]')].find(item => item.textContent === name)!;
  const expandAll = () => container.querySelector<HTMLButtonElement>('button[aria-label$="all sections"]');

  it('uses the long-answer threshold', () => {
    expect(shouldCollapseAnswer(longBlocks)).toBe(true);
    expect(shouldCollapseAnswer(longBlocks.slice(0, 2))).toBe(false);
    expect(shouldCollapseAnswer(longBlocks.map(block => ({ ...block, body: words(20, 'x') })))).toBe(false);
  });

  it('keeps the first two sections open, collapses the rest, and toggles all', () => {
    render(<LessonReader id="answer" blocks={longBlocks} collapsible />);
    expect(container.querySelectorAll('button[aria-expanded]')).toHaveLength(3);
    expect(toggle('Mechanism').getAttribute('aria-expanded')).toBe('true');
    expect(toggle('Worked example').getAttribute('aria-expanded')).toBe('false');
    const body = document.getElementById(toggle('Worked example').getAttribute('aria-controls')!)!;
    expect(body.hidden).toBe(true);
    expect(document.getElementById(toggle('Mechanism').getAttribute('aria-controls')!)!.hidden).toBe(false);

    click(toggle('Worked example'));
    expect(toggle('Worked example').getAttribute('aria-expanded')).toBe('true');
    expect(body.hidden).toBe(false);

    expect(expandAll()!.textContent).toBe('Expand all');
    click(expandAll()!);
    expect([...container.querySelectorAll('button[aria-expanded]')].every(item => item.getAttribute('aria-expanded') === 'true')).toBe(true);
    expect(expandAll()!.textContent).toBe('Collapse all');
    click(expandAll()!);
    expect([...container.querySelectorAll('button[aria-expanded]')].every(item => item.getAttribute('aria-expanded') === 'false')).toBe(true);
  });

  it('renders short answers exactly as before', () => {
    const short = longBlocks.map(block => ({ ...block, body: 'Short body.' }));
    render(<LessonReader id="answer" blocks={short} collapsible />);
    const collapsedMarkup = container.innerHTML;
    expect(container.querySelector('button[aria-expanded]')).toBeNull();
    expect(expandAll()).toBeNull();
    render(<LessonReader id="answer" blocks={short} />);
    expect(container.innerHTML).toBe(collapsedMarkup);
  });

  it('never collapses while streaming and keeps a streamed answer open once complete', () => {
    render(<LessonReader id="answer" blocks={longBlocks} />);
    expect(container.querySelector('button[aria-expanded]')).toBeNull();
    expect(container.querySelectorAll('h2')).toHaveLength(4);
    render(<LessonReader id="answer" blocks={longBlocks} collapsible />);
    expect(container.querySelectorAll('button[aria-expanded]')).toHaveLength(3);
    expect([...container.querySelectorAll('button[aria-expanded]')].every(item => item.getAttribute('aria-expanded') === 'true')).toBe(true);
    expect(expandAll()!.textContent).toBe('Collapse all');
  });
});
