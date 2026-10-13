"use client";

import { Children, isValidElement, useState, type ReactNode } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import { readingRemarkPlugins as remarkPlugins, readingRehypePlugins as rehypePlugins } from '@/lib/markdown-rendering';
import 'katex/dist/katex.min.css';
import { normalizeMathMarkdown } from '@/lib/normalize-math-markdown';
import styles from './reading.module.css';
import { encodeConceptLinks, splitTutorContent } from '@/lib/tutor-format';
import { ExerciseCard } from './exercise-card';

function ConceptLink({ href, children, onSelect }: { href: string; children: ReactNode; onSelect?: (term: string) => void }) {
  const [open, setOpen] = useState(false);
  const parsed = new URL(href, 'https://local.invalid');
  const definition = parsed.searchParams.get('definition');
  let term = parsed.pathname;
  try { term = decodeURIComponent(term); } catch { /* Keep malformed links readable. */ }
  return <span className={styles.conceptWrap}><button type="button" className={styles.conceptLink} aria-expanded={definition ? open : undefined} onClick={() => { if (definition) setOpen(value => !value); onSelect?.(term); }} title={definition || 'Ask about this concept'}>{children}</button>{open && definition ? <span className={styles.conceptDefinition} role="note">{definition}</span> : null}</span>;
}

function CodeBlock({ children, onExplore, hideHtmlSource = false }: { children?: ReactNode; onExplore?: (raw: string, equation?: boolean) => void; hideHtmlSource?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  const child = Children.toArray(children)[0];
  const props = isValidElement<{ className?: string; children?: ReactNode }>(child) ? child.props : {};
  const language = props.className?.replace('language-', '') || 'text';
  const raw = String(props.children || '').replace(/\n$/, '');
  if (hideHtmlSource && /^(?:html?|xhtml)$/i.test(language)) return null;
  if (language === 'details') {
    const [title, ...body] = raw.split('\n');
    return (
      <details className={styles.detail}>
        <summary>{title || 'Details'}</summary>
        <RichContent body={body.join('\n')} onExplore={onExplore} />
      </details>
    );
  }
  return (
    <div className={styles.code}>
      <div className={styles.codeTop}>
        <span>{language}</span>
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(raw);
              setCopied(true);
              setError(false);
            } catch {
              setError(true);
            }
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>{children}</pre>
      {error && <span role="status">Copy unavailable. Select the text to copy it.</span>}
    </div>
  );
}

/**
 * Canonical renderer for all LLM-generated teaching content.
 * Persisted storage stays Markdown + LaTeX; this component typesets at presentation time.
 */
export function RichContent({ body, onExplore, onExerciseResolved, onConceptSelect, hideHtmlSource = false }: { body: string; onExplore?: (raw: string, equation?: boolean) => void; onExerciseResolved?: (id: string) => void; onConceptSelect?: (term: string) => void; hideHtmlSource?: boolean }) {
  const source = normalizeMathMarkdown(body);
  return (
    <div className={styles.rich}>
      {splitTutorContent(source).map((part, partIndex) => part.kind === 'exercise' ? <ExerciseCard key={`exercise-${part.exercise.id}-${partIndex}`} exercise={part.exercise} onResolved={onExerciseResolved}/> : part.kind === 'pending_exercise' || part.kind === 'invalid_exercise' ? <p key={`exercise-status-${partIndex}`} role="status">{part.kind === 'pending_exercise' ? 'Preparing practice question…' : 'This practice question could not be displayed.'}</p> : <ReactMarkdown
        key={`markdown-${partIndex}`}
        remarkPlugins={remarkPlugins as never}
        rehypePlugins={rehypePlugins as never}
        urlTransform={url => url.startsWith('concept:') ? url : defaultUrlTransform(url)}
        skipHtml
        components={{
          pre: ({ children }) => <CodeBlock onExplore={onExplore} hideHtmlSource={hideHtmlSource}>{children}</CodeBlock>,
          a: ({ href, children }) => href?.startsWith('concept:') ? <ConceptLink href={href} onSelect={onConceptSelect}>{children}</ConceptLink> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
          img: ({ alt }) => <span className={styles.imagePlaceholder}>{alt || 'Image reference'}</span>,
          table: ({ children }) => (
            <div className={styles.table}>
              <table>{children}</table>
            </div>
          ),
          span: ({ children, className, ...props }) => {
            if (className?.split(' ').includes('katex-display')) {
              return (
                <span className={styles.equation}>
                  <span className={styles.mathScroll}>
                    <span {...props} className={className}>{children}</span>
                  </span>
                </span>
              );
            }
            return <span {...props} className={className}>{children}</span>;
          },
          p: ({ node, children }) => (
            <p
              onMouseUp={event => {
                if (!onExplore) return;
                const selection = window.getSelection();
                const selected = selection?.toString().trim();
                if (!selected || !event.currentTarget.contains(selection!.anchorNode) || !event.currentTarget.contains(selection!.focusNode)) return;
                const raw = body.slice(node?.position?.start.offset ?? 0, node?.position?.end.offset ?? body.length);
                onExplore(raw.includes(selected) ? selected.slice(0, 1200) : raw.slice(0, 1200));
              }}
            >
              {children}
            </p>
          ),
        }}
      >
        {encodeConceptLinks('body' in part ? part.body : '')}
      </ReactMarkdown>)}
    </div>
  );
}
