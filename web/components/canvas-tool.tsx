"use client";

import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { Download, FilePlus2, Maximize2, Send, Shapes, Sparkles } from 'lucide-react';
import { parseGeneratedVisual, parseGeneratedVisualRef, parseVisualArtifact } from '@/lib/generated-visual';
import { WORKSPACE_ASK_EVENT, askWorkspacePassage } from '@/lib/workspace-events';
import { Button } from './ui/button';
import { PassageSelection } from './passage-selection';
import { noteVisualMarkdown } from './visualization-reference';
import styles from './canvas-tool.module.css';

const Visualization = dynamic(() => import('./visualization').then(module => module.Visualization), { loading: () => <div className={styles.loading} role="status">Loading visual…</div> });

const EXAMPLES = [
  'Show me how a pendulum swings',
  'Graph y = x² and its derivative',
  'Diagram the water cycle',
  'Timeline of the French Revolution',
];

type CanvasItem = { key: string; title: string; value: unknown };

/** Put a request in Buddy's chat box. Falls back to closing the panel when the chat is hidden. */
function askBuddy(text: string): 'chat' | 'panel-closed' {
  const chat = document.querySelector<HTMLTextAreaElement>('[id="chat-message"]');
  if (!chat || chat.offsetParent === null) { askWorkspacePassage(text); return 'panel-closed'; }
  window.dispatchEvent(new CustomEvent<string>(WORKSPACE_ASK_EVENT, { detail: text }));
  window.setTimeout(() => chat.focus(), 0);
  return 'chat';
}

/** Copy computed paint onto an SVG clone so it renders the same outside the page's CSS. */
function inlineStyles(source: Element, target: Element) {
  const computed = getComputedStyle(source);
  const style = ['fill', 'stroke', 'stroke-width', 'opacity', 'font-family', 'font-size', 'font-weight', 'color'].map(name => `${name}:${computed.getPropertyValue(name)}`).join(';');
  target.setAttribute('style', `${target.getAttribute('style') || ''};${style}`);
  Array.from(source.children).forEach((child, index) => { if (target.children[index]) inlineStyles(child, target.children[index]); });
}

async function downloadImage(stage: HTMLElement, title: string): Promise<boolean> {
  const name = title.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'visual';
  const save = (href: string) => { const link = document.createElement('a'); link.href = href; link.download = `${name}.png`; link.click(); };
  const canvas = stage.querySelector('canvas');
  if (canvas) { save(canvas.toDataURL('image/png')); return true; }
  const svg = stage.querySelector('svg');
  if (!svg) return false;
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(Math.round(width)));
  clone.setAttribute('height', String(Math.round(height)));
  inlineStyles(svg, clone);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }));
  try {
    const image = new Image();
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
    const output = document.createElement('canvas');
    output.width = Math.max(1, Math.round(width * 2)); output.height = Math.max(1, Math.round(height * 2));
    const context = output.getContext('2d');
    if (!context) return false;
    context.fillStyle = getComputedStyle(stage).backgroundColor || '#ffffff';
    context.fillRect(0, 0, output.width, output.height);
    context.drawImage(image, 0, 0, output.width, output.height);
    save(output.toDataURL('image/png'));
    return true;
  } catch { return false; } finally { URL.revokeObjectURL(url); }
}

/**
 * Canvas shows what Buddy draws. Recent visuals stay one click away, and the open
 * one can be saved into a note, shown full screen, exported or revised with Buddy.
 */
export function CanvasTool({ value, header, onAddToNote }: { value: unknown; header: (actions: ReactNode) => ReactNode; onAddToNote: (markdown: string, title: string) => void }) {
  const [history, setHistory] = useState<CanvasItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [seen, setSeen] = useState<unknown>(undefined);
  const [notice, setNotice] = useState('');
  const [edit, setEdit] = useState('');
  const stage = useRef<HTMLDivElement>(null);
  // Adopt each new visual from the chat as the current one and remember it.
  if (value !== seen) {
    setSeen(value);
    const visual = parseVisualArtifact(value);
    if (visual) {
      const key = `${visual.id}:${'revision' in visual ? visual.revision : ''}`;
      setHistory(current => [{ key, title: visual.title || 'Visual', value }, ...current.filter(item => item.key !== key)].slice(0, 12));
      setSelected(key);
      setNotice('');
    }
  }
  const current = history.find(item => item.key === selected) || history[0];
  const visual = current ? parseVisualArtifact(current.value) : null;
  const generated = current ? Boolean(parseGeneratedVisual(current.value) || parseGeneratedVisualRef(current.value)) : false;
  const noteMarkdown = current ? noteVisualMarkdown(current.value) : null;

  const fullScreen = () => {
    const element = stage.current;
    if (!element) return;
    if (document.fullscreenElement) { void document.exitFullscreen(); return; }
    if (element.requestFullscreen) element.requestFullscreen().catch(() => setNotice('Full screen is not available here.'));
    else setNotice('Full screen is not available here.');
  };
  const exportImage = async () => {
    if (!stage.current || !current) return;
    setNotice(await downloadImage(stage.current, current.title) ? '' : 'This visual can’t be saved as an image yet.');
  };
  const submitEdit = (event: FormEvent) => {
    event.preventDefault();
    const text = edit.trim();
    if (!text || !current) return;
    askBuddy(`Update the visual “${current.title}”: ${text}`);
    setEdit('');
    setNotice('Your request is in the chat box. Press Enter there to send it.');
  };

  const actions = current ? <>
    <Button type="button" size="sm" variant="outline" disabled={!noteMarkdown} title={noteMarkdown ? 'Add this visual to the open note' : 'This visual is too large to keep in a note'} onClick={() => { if (noteMarkdown) { onAddToNote(noteMarkdown, current.title); setNotice('Added to your note.'); } }}><FilePlus2 size={15}/>Add to note</Button>
    {!generated ? <Button type="button" size="icon-sm" variant="ghost" aria-label="Download as image" title="Download as image" onClick={() => void exportImage()}><Download size={16}/></Button> : null}
    <Button type="button" size="icon-sm" variant="ghost" aria-label="Show full screen" title="Full screen" onClick={fullScreen}><Maximize2 size={16}/></Button>
  </> : null;

  return <>
    {header(actions)}
    {current && visual ? <>
      {history.length > 1 ? <div className={styles.history} role="tablist" aria-label="Recent visuals">
        {history.map(item => <button key={item.key} type="button" role="tab" aria-selected={item.key === current.key} title={item.title} onClick={() => { setSelected(item.key); setNotice(''); }}><Shapes size={13} aria-hidden="true"/><span>{item.title}</span></button>)}
      </div> : null}
      <div ref={stage} className={styles.stage}>
        <PassageSelection title={current.title} itemContext={JSON.stringify(current.value)}><Visualization key={current.key} value={current.value} lessonId={visual.sourceLessonId}/></PassageSelection>
      </div>
      <form className={styles.edit} onSubmit={submitEdit}>
        <Sparkles size={15} aria-hidden="true"/>
        <input value={edit} onChange={event => setEdit(event.target.value)} placeholder="Ask Buddy to change this visual…" aria-label="Ask Buddy to change this visual" maxLength={600}/>
        <Button type="submit" size="icon-sm" variant="ghost" aria-label="Send to Buddy" disabled={!edit.trim()}><Send size={15}/></Button>
      </form>
      {notice ? <p className={styles.notice} role="status">{notice}</p> : null}
    </> : <div className="ol-card ol-empty">
      <Shapes aria-hidden="true"/>
      <h3>Nothing on the canvas yet</h3>
      <p>Ask Buddy to draw, graph or simulate something. Visuals from the chat open here.</p>
      <div className={styles.examples}>{EXAMPLES.map(example => <button key={example} type="button" onClick={() => askBuddy(example)}>{example}</button>)}</div>
    </div>}
  </>;
}
