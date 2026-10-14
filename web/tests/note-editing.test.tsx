import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { markdownShortcut, matchSlashCommands, matchesNoteFilter, noteWordCount, relativeTime, slashQuery } from '@/lib/note-editing';
import { richNoteToMarkdown } from '@/lib/rich-note-markdown';
import { noteVisualMarkdown } from '@/components/visualization-reference';
import { WORKSPACE_ASK_EVENT } from '@/lib/workspace-events';

vi.mock('@/components/visualization', () => ({ Visualization: ({ value }: { value: { title?: string } }) => <div data-testid="visual">{value?.title}</div> }));
vi.mock('@/components/passage-selection', () => ({ PassageSelection: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

let root: Root, container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

it('detects slash queries and Markdown block markers typed at the caret', () => {
  expect(slashQuery('/')).toBe('');
  expect(slashQuery('Some text /chec')).toBe('chec');
  expect(slashQuery('a/b')).toBeNull();
  expect(matchSlashCommands('chec').map(command => command.id)).toEqual(['checklist']);
  expect(matchSlashCommands('diagram').map(command => command.id)).toEqual(['visual']);
  expect(markdownShortcut('#')).toBe('heading');
  expect(markdownShortcut('##')).toBe('subheading');
  expect(markdownShortcut('-')).toBe('bullet');
  expect(markdownShortcut('1.')).toBe('numbered');
  expect(markdownShortcut('[]')).toBe('checklist');
  expect(markdownShortcut('>')).toBe('quote');
  expect(markdownShortcut('hello')).toBeNull();
});

it('formats relative times, counts prose words and filters note kinds', () => {
  const now = new Date('2026-10-14T15:00:00').getTime();
  expect(relativeTime('2026-10-14T14:59:40', now)).toBe('Just now');
  expect(relativeTime('2026-10-14T14:20:00', now)).toBe('40m ago');
  expect(relativeTime('2026-10-14T09:00:00', now)).toBe('6h ago');
  expect(relativeTime('2026-10-13T09:00:00', now)).toBe('Yesterday');
  expect(noteWordCount('Two words\n\n```visualization-ref\n{"lessonId":"lesson_a"}\n```')).toBe(2);
  const lesson = { noteType: 'lesson', frontmatter: {} }, recording = { noteType: 'recording', frontmatter: {} }, mine = { noteType: 'manual', frontmatter: {} };
  expect([lesson, recording, mine].filter(note => matchesNoteFilter(note, 'lessons'))).toEqual([lesson]);
  expect([lesson, recording, mine].filter(note => matchesNoteFilter(note, 'classes'))).toEqual([recording]);
  expect([lesson, recording, mine].filter(note => matchesNoteFilter(note, 'personal'))).toEqual([mine]);
});

it('keeps code fence languages and embedded visuals when serializing the editor', () => {
  const editor = document.createElement('article');
  editor.innerHTML = '<p>Intro</p><pre><code class="language-python">print(1)\n</code></pre><figure data-note-visual=\'{"lessonId":"lesson_a","visualizationId":"v1"}\' data-note-visual-lang="visualization-ref"><figcaption>Visual</figcaption></figure>';
  expect(richNoteToMarkdown(editor)).toBe('Intro\n\n```python\nprint(1)\n```\n\n```visualization-ref\n{"lessonId":"lesson_a","visualizationId":"v1"}\n```');
});

it('stores lesson visuals as references and generated visuals as small refs', () => {
  const generated = { version: 2, type: 'generated_ui_ref', id: 'vis_1', revision: 3, title: 'Pendulum', runId: 'run_1', blockIndex: 0, afterParagraph: 0 };
  expect(noteVisualMarkdown(generated)).toBe('```visual-artifact\n' + JSON.stringify({ version: 2, type: 'generated_ui_ref', id: 'vis_1', revision: 3, title: 'Pendulum', blockIndex: 0, afterParagraph: 0, runId: 'run_1' }) + '\n```');
  expect(noteVisualMarkdown({ nothing: true })).toBeNull();
});

it('offers clickable example prompts on an empty canvas and adds a visual to the note', async () => {
  const { CanvasTool } = await import('@/components/canvas-tool');
  const chat = document.createElement('textarea'); chat.id = 'chat-message'; document.body.appendChild(chat);
  Object.defineProperty(chat, 'offsetParent', { get: () => document.body });
  const asked = vi.fn(); window.addEventListener(WORKSPACE_ASK_EVENT, asked);
  const added = vi.fn();
  act(() => root.render(<CanvasTool value={null} header={actions => <div>{actions}</div>} onAddToNote={added}/>));
  act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Diagram the water cycle')!.click());
  expect((asked.mock.calls[0][0] as CustomEvent).detail).toBe('Diagram the water cycle');
  const visual = { version: 2, type: 'generated_ui_ref', id: 'vis_1', revision: 1, title: 'Water cycle', runId: '', blockIndex: 0, afterParagraph: 0 };
  await act(async () => root.render(<CanvasTool value={visual} header={actions => <div>{actions}</div>} onAddToNote={added}/>));
  act(() => [...container.querySelectorAll('button')].find(button => button.textContent === 'Add to note')!.click());
  expect(added).toHaveBeenCalledWith(expect.stringContaining('```visual-artifact'), 'Water cycle');
  window.removeEventListener(WORKSPACE_ASK_EVENT, asked); chat.remove();
});
